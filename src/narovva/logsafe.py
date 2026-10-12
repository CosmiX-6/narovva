"""Keep credentials out of logs and stored error text.

httpx logs every request URL at INFO, and the Instagram Graph API takes the
access token as a query parameter, so a plain `logging.basicConfig(INFO)` printed
live tokens into the (readable) Actions logs. Two layers: the HTTP client
loggers are held at WARNING, and every log record passes through `redact`."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    # query/form parameters and JSON-ish key: value pairs
    (re.compile(r"(?i)((?:access_token|client_secret|app_secret|api[_-]?key|token|secret|password|sig|jwt)=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"(?i)((?:access_token|client_secret|api_key)['\"]?\s*:\s*['\"])[^'\"]+"), r"\1***"),
    # headers / bearer credentials
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1***"),
    (re.compile(r"(?i)(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_-]{12,}"), r"\1***"),
    # Instagram / Facebook / OpenAI-style token shapes, wherever they appear
    (re.compile(r"\bIG[A-Za-z0-9]{40,}"), "IG***"),
    (re.compile(r"\bEAA[A-Za-z0-9]{40,}"), "EAA***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "sk-***"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"), "AIza***"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: leave the record as is
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


def install(level: int = logging.INFO) -> None:
    """Configure logging with redaction. Call once at process start."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactFilter) for f in handler.filters):
            handler.addFilter(RedactFilter())
    if level > logging.DEBUG:
        # Request URLs carry credentials; WARNING keeps failures, drops the per-request lines.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
