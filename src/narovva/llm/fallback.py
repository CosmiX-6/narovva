"""Text-model fallback chain.

One article costs several LLM calls (analysis, caption, voice-over script). On a
free tier a single model's daily quota is gone after a few articles, and busy
models answer 503, which used to fail every article in the run. The chain tries
each configured model in order and remembers which ones are spent, so a dead
model costs one failed call per run, not one per article.

Free-tier quotas are per model, so several Gemini models are several pools;
OpenRouter's ':free' models and OpenAI are independent providers behind them.

Entries are written "provider[:model]" (model optional), e.g.
    claude-code:claude-sonnet-5-5     (a claude.ai plan's token, through the Claude Code CLI)
    anthropic:claude-sonnet-5-5       (a Console API key)
    gemini:gemini-flash-latest
    gemini:gemini-2.5-flash-lite
    openrouter:meta-llama/llama-3.3-70b-instruct:free
    openai:gpt-4o-mini
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

import httpx
from poster_core.analysis.llm import GeminiChat, OpenAIChat, parse_json_response

from ..logsafe import redact

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_CLAUDE = "claude-sonnet-5-5"
_MAX_QUICK_WAIT = 30.0     # a per-minute rate limit that clears in this long is waited out
_OVERLOAD_PAUSE = 2.0
_OVERLOAD_COOLDOWN = 120.0  # an overloaded model is skipped for this long, then tried again


class LLMUnavailable(RuntimeError):
    """Every model in the chain is exhausted or failing. Raised so the run can
    stop instead of burning attempts on every remaining article."""


def classify_error(exc: BaseException) -> str:
    """'quota' | 'overload' | 'gone' | 'auth' | 'bad_output' | 'other'."""
    text = f"{type(exc).__name__} {exc}".lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or any(k in text for k in ("resource_exhausted", "insufficient_quota", "quota", "rate limit", "rate_limit", " 429",
                                                "credit balance is too low", "usage limit", "hit your limit",
                                                "limit reached")):
        return "quota"
    if status in (500, 502, 503, 504, 529) or any(k in text for k in ("unavailable", "overloaded", "high demand", "timed out", "timeout", "connection", " 503", " 500", " 502", " 504", " 529")):
        return "overload"
    if status == 404 or any(k in text for k in ("not_found", "no longer available", "is not found", "does not exist", "model_not_found")):
        return "gone"  # retired or misspelled model id: it will fail identically for every article
    if status in (401, 403) or any(k in text for k in ("api key", "api_key", "permission_denied", "unauthorized", "invalid_api_key", "no api key",
                                                       "/login", "oauth token", "not logged in")):
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


class AnthropicChat:
    """Claude through the official Anthropic SDK (`anthropic` package, ANTHROPIC_API_KEY).

    A paid key, so no daily free-tier quota: the primary model. The system prompt is cached (the storyboard, director
    and analysis prompts are long and the same for every article), the reply is streamed (a long storyboard would
    otherwise risk the request timeout) and JSON is asked for in the prompt, as the other providers do -- each caller
    validates its own shape. The SDK retries 429/5xx itself before the chain sees an error."""

    def __init__(self, model: str, api_key: str, *, effort: str | None = "medium", max_tokens: int = 16000,
                 timeout: float = 300.0, client=None):
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=3)
        self._client = client

    def complete_json(self, system: str, user: str) -> dict:
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system + "\n\nReply with a single JSON object and nothing else.",
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
        }
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        with self._client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise LLMHTTPError(422, f"refusal: {getattr(details, 'category', None)}")   # 'other': next model
        if message.stop_reason == "max_tokens":
            raise LLMHTTPError(422, "reply cut off at max_tokens (bad json)")
        text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        return parse_json_response(text)


class ClaudeCodeChat:
    """Claude through the Claude Code CLI in headless mode (`claude -p`), signed in with a claude.ai subscription's
    long-lived token (`claude setup-token` -> CLAUDE_CODE_OAUTH_TOKEN). Runs on the plan's usage, not API billing.

    Only Claude Code accepts that token (the Messages API does not), hence the subprocess. The call is made inert: no
    tools, no MCP servers, no slash commands or skills, no saved session -- a single JSON reply to one prompt. The
    system prompt goes through a file and the user prompt through stdin (both are too long for a command line).
    ANTHROPIC_API_KEY is removed from the child's environment: Claude Code prefers it over the token, which would
    silently bill the API instead of the plan. When the plan's usage limit is hit the reply is an error the chain
    reads as spent quota, and the next model answers for the rest of the run."""

    def __init__(self, model: str, token: str, *, effort: str | None = "medium", timeout: float = 600.0,
                 binary: str | None = None, run=None, tools: tuple[str, ...] = (), cwd: str | None = None):
        import shutil

        self.model, self.effort, self._token, self._timeout = model, effort, token, timeout
        # tools: built-in Claude Code tools this call may use (and is pre-approved for), e.g. ("WebSearch",
        # "WebFetch") or ("Read",). Nothing else is available -- no Bash, no writes. File tools only see `cwd`.
        self.tools, self.cwd = tuple(tools), cwd
        self.binary = binary or os.environ.get("CLAUDE_BIN") or shutil.which("claude")
        if not self.binary:
            raise LLMHTTPError(401, "no api key: the claude CLI is not installed (npm i -g @anthropic-ai/claude-code)")
        self._run = run or subprocess.run

    def complete_json(self, system: str, user: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as f:
            f.write(system + "\n\nReply with a single JSON object and nothing else.")
            sys_file = f.name
        cmd = [self.binary, "-p", "--output-format", "json", "--model", self.model, "--system-prompt-file", sys_file,
               "--tools", ",".join(self.tools), "--no-session-persistence", "--strict-mcp-config",
               "--disable-slash-commands"]
        if self.tools:
            cmd += ["--allowedTools", *self.tools]
        if self.effort:
            cmd += ["--effort", self.effort]
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        if self._token:   # (empty: the CLI's own sign-in, for local trials)
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._token
        try:
            proc = self._run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", env=env,
                             timeout=self._timeout, **({"cwd": self.cwd} if self.cwd else {}))
        except subprocess.TimeoutExpired as exc:
            raise LLMHTTPError(504, f"claude CLI timed out after {self._timeout:.0f}s") from exc
        finally:
            try:
                os.unlink(sys_file)
            except OSError:
                pass
        try:
            data = json.loads(proc.stdout or "")
        except ValueError:
            raise LLMHTTPError(502, f"claude CLI exit {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}") from None
        if not isinstance(data, dict):
            raise LLMHTTPError(502, f"unexpected claude CLI output: {str(data)[:200]}")
        result = str(data.get("result") or "")
        if data.get("is_error") or proc.returncode:
            raise LLMHTTPError(int(data.get("api_error_status") or 500), f"claude CLI: {result[:300]}")
        if data.get("stop_reason") == "refusal":
            raise LLMHTTPError(422, "refusal")
        if data.get("stop_reason") == "max_tokens":
            raise LLMHTTPError(422, "reply cut off at max_tokens (bad json)")
        return parse_json_response(result)


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
    rejected: int = 0                # replies a caller found unusable: asked last on later checked calls


@dataclass
class FallbackLLM:
    """Implements poster_core's LLMClient protocol over an ordered chain."""

    entries: list[_Entry]
    sleep: object = field(default=time.sleep, repr=False)
    clock: object = field(default=time.monotonic, repr=False)
    failures: list[str] = field(default_factory=list)

    # complete_json takes `accept` (callers check this flag; poster_core's clients do not take it)
    takes_accept = True

    def complete_json(self, system: str, user: str, accept=None, max_rejects: int = 2) -> dict:
        """The first model's reply. With `accept(reply) -> reason | None`, a reply that parses but is no use (a weak
        model's storyboard that fails validation) is set aside and the next model asked -- at most `max_rejects`
        times, so a bad day does not spend every quota on one call. If no reply is accepted, the first one set
        aside is returned (the caller still salvages what it can); if none came back at all, LLMUnavailable."""
        failures: list[str] = []
        spare, rejects = None, 0
        # a model that already gave an unusable reply this run is asked last when the reply will be checked again
        order = sorted(self.entries, key=lambda e: e.rejected > 0) if accept else self.entries
        for entry in order:
            if entry.dead_reason or self.clock() < entry.cooldown_until:
                continue
            if spare is not None and rejects >= max_rejects:
                break
            for attempt in (1, 2):
                try:
                    reply = entry.client.complete_json(system, user)
                    reason = accept(reply) if accept else None
                    if not reason:
                        return reply
                    rejects += 1
                    entry.rejected += 1
                    spare = reply if spare is None else spare
                    logger.warning("llm %s: reply not usable (%s); asking the next model", entry.name,
                                   str(reason)[:160])
                    failures.append(f"{entry.name}: rejected")
                    break
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
                    elif kind == "gone":
                        entry.dead_reason = f"model unavailable ({detail})"
                        # the provider's answer often names the replacement model: keep it in the log
                        logger.warning("llm %s: model not available (retired or misspelled id?); skipping it (%s)",
                                       entry.name, str(detail)[:300])
                    else:  # bad JSON or something unexpected: another model may do better
                        logger.warning("llm %s failed (%s): %s", entry.name, kind, detail)
                    failures.append(f"{entry.name}: {kind}")
                    break
        self.failures = failures
        if spare is not None:
            return spare
        raise LLMUnavailable(
            "no text model available (" + ("; ".join(failures) or "all models exhausted earlier in this run") + ")"
        )


def _split(spec: str) -> tuple[str, str | None]:
    provider, _, model = spec.partition(":")
    return provider.strip().lower(), (model.strip() or None)


def _beta_for_aliases(client, key: str) -> None:
    """Google serves the moving model aliases ("gemini-flash-latest") only on its v1beta API,
    while newer google-genai SDKs call v1, where the alias answers 404 and the chain skipped
    its best model. Point an alias's client at v1beta (pinned model ids stay as they are)."""
    if not str(getattr(client, "model", "")).endswith("-latest"):
        return
    try:
        from google import genai

        client._client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    except Exception as exc:  # an older SDK without http_options: leave the default
        logger.warning("llm chain: could not select v1beta for %s (%s)", client.model, exc)


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
                _beta_for_aliases(client, key)
            elif provider == "openai":
                client = OpenAIChat(model=model, api_key=key) if model else OpenAIChat(api_key=key)
            elif provider == "openrouter":
                client = OpenRouterChat(model or "meta-llama/llama-3.3-70b-instruct:free", key)
            elif provider == "anthropic":
                client = AnthropicChat(model or DEFAULT_CLAUDE, key)
            elif provider == "claude-code":
                client = ClaudeCodeChat(model or DEFAULT_CLAUDE, key)
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
