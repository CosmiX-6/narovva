"""Text-model fallback chain.

One article costs several LLM calls (analysis, caption, voice-over script). On a
free tier a single model's daily quota is gone after a few articles, and busy
models answer 503, which used to fail every article in the run. The chain tries
each configured model in order and remembers which ones are spent, so a dead
model costs one failed call per run, not one per article.

Free-tier quotas are per model, so several Gemini models are several pools;
OpenRouter's ':free' models and OpenAI are independent providers behind them.

Entries are written "provider[:model]" (model optional), e.g.
    gemini:gemini-flash-latest
    gemini:gemini-2.5-flash-lite
    openrouter:meta-llama/llama-3.3-70b-instruct:free
    openai:gpt-4o-mini
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import httpx
from poster_core.analysis.llm import GeminiChat, OpenAIChat, parse_json_response

from ..logsafe import redact

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MAX_QUICK_WAIT = 30.0     # a per-minute rate limit that clears in this long is waited out
_OVERLOAD_PAUSE = 2.0
_OVERLOAD_COOLDOWN = 120.0  # an overloaded model is skipped for this long, then tried again


class LLMUnavailable(RuntimeError):
    """Every model in the chain is exhausted or failing. Raised so the run can
    stop instead of burning attempts on every remaining article."""


def classify_error(exc: BaseException) -> str:
    """'quota' | 'overload' | 'auth' | 'bad_output' | 'other'."""
    text = f"{type(exc).__name__} {exc}".lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or any(k in text for k in ("resource_exhausted", "insufficient_quota", "quota", "rate limit", "rate_limit", " 429")):
        return "quota"
    if status in (500, 502, 503, 504) or any(k in text for k in ("unavailable", "overloaded", "high demand", "timed out", "timeout", "connection", " 503", " 500", " 502", " 504")):
        return "overload"
    if status in (401, 403) or any(k in text for k in ("api key", "api_key", "permission_denied", "unauthorized", "invalid_api_key", "no api key")):
        return "auth"
    if "json" in text or "analysiserror" in text:
        return "bad_output"
    return "other"


def retry_delay_seconds(exc: BaseException) -> float | None:
    """The wait a provider asked for ('Please retry in 20.5s', retryDelay '75586s')."""
    text = str(exc)
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", text, re.I)
    if m:
        h, mi, s = (float(g) if g else 0.0 for g in m.groups())
        return h * 3600 + mi * 60 + s
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", text)
    if m:
        return float(m.group(1))
    m = re.search(r"retry-after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", text, re.I)
    return float(m.group(1)) if m else None


class OpenRouterChat:
    """OpenRouter (OpenAI-compatible) chat completions. `:free` models cost
    nothing but are rate limited (about 20 requests/minute, 50/day, or 1000/day
    after a one-time $10 top-up) and vary in how well they follow JSON."""

    def __init__(self, model: str, api_key: str, timeout: float = 90.0):
        self.model, self._key, self._timeout = model, api_key, timeout

    def complete_json(self, system: str, user: str) -> dict:
        resp = httpx.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self._key}", "X-Title": "narovva"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system + "\n\nReply with a single JSON object and nothing else."},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            err = LLMHTTPError(resp.status_code, resp.text[:400])
            retry_after = resp.headers.get("retry-after")
            if retry_after:
                err.args = (f"{err.args[0]} retry-after: {retry_after}",)
            raise err
        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMHTTPError(502, f"unexpected OpenRouter response: {resp.text[:200]}") from exc
        return parse_json_response(content)


class LLMHTTPError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"HTTP {status_code}: {body}")
        self.status_code = status_code


@dataclass
class _Entry:
    name: str
    client: object
    dead_reason: str | None = None   # permanent for this process (spent quota, bad key)
    cooldown_until: float = 0.0


@dataclass
class FallbackLLM:
    """Implements poster_core's LLMClient protocol over an ordered chain."""

    entries: list[_Entry]
    sleep: object = field(default=time.sleep, repr=False)
    clock: object = field(default=time.monotonic, repr=False)
    failures: list[str] = field(default_factory=list)

    def complete_json(self, system: str, user: str) -> dict:
        failures: list[str] = []
        for entry in self.entries:
            if entry.dead_reason or self.clock() < entry.cooldown_until:
                continue
            for attempt in (1, 2):
                try:
                    return entry.client.complete_json(system, user)
                except Exception as exc:  # provider SDKs raise their own types
                    kind = classify_error(exc)
                    detail = redact(str(exc))[:240]
                    if kind == "quota":
                        wait = retry_delay_seconds(exc)
                        if attempt == 1 and wait is not None and wait <= _MAX_QUICK_WAIT:
                            logger.info("llm %s: rate limited, waiting %.0fs", entry.name, wait)
                            self.sleep(wait + 0.5)
                            continue
                        entry.dead_reason = f"quota exhausted ({detail})"
                        logger.warning("llm %s: quota exhausted; skipping it for the rest of the run", entry.name)
                    elif kind == "overload":
                        if attempt == 1:
                            self.sleep(_OVERLOAD_PAUSE)
                            continue
                        entry.cooldown_until = self.clock() + _OVERLOAD_COOLDOWN
                        logger.warning("llm %s: overloaded; trying the next model", entry.name)
                    elif kind == "auth":
                        entry.dead_reason = f"credentials rejected ({detail})"
                        logger.warning("llm %s: credentials rejected; skipping it", entry.name)
                    else:  # bad JSON or something unexpected: another model may do better
                        logger.warning("llm %s failed (%s): %s", entry.name, kind, detail)
                    failures.append(f"{entry.name}: {kind}")
                    break
        self.failures = failures
        raise LLMUnavailable(
            "no text model available (" + ("; ".join(failures) or "all models exhausted earlier in this run") + ")"
        )


def _split(spec: str) -> tuple[str, str | None]:
    provider, _, model = spec.partition(":")
    return provider.strip().lower(), (model.strip() or None)


def build_llm_chain(specs: list[str], keys: dict[str, str | None]) -> FallbackLLM:
    """Build the chain from "provider[:model]" strings. Entries whose provider
    has no API key are left out (logged), so a missing OPENROUTER_API_KEY just
    shortens the chain."""
    entries: list[_Entry] = []
    for spec in specs:
        provider, model = _split(spec)
        key = keys.get(provider)
        if not key:
            logger.info("llm chain: skipping %r (no API key for %s)", spec, provider)
            continue
        try:
            if provider == "gemini":
                client = GeminiChat(model=model, api_key=key) if model else GeminiChat(api_key=key)
            elif provider == "openai":
                client = OpenAIChat(model=model, api_key=key) if model else OpenAIChat(api_key=key)
            elif provider == "openrouter":
                client = OpenRouterChat(model or "meta-llama/llama-3.3-70b-instruct:free", key)
            else:
                logger.warning("llm chain: unknown provider in %r", spec)
                continue
        except Exception as exc:  # missing SDK extra, bad args
            logger.warning("llm chain: cannot build %r (%s)", spec, exc)
            continue
        entries.append(_Entry(spec, client))
    if not entries:
        raise LLMUnavailable("no text model is configured: set an API key for at least one llm_chain entry")
    return FallbackLLM(entries)
