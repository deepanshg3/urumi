"""Logging helpers with conservative redaction.

The services log operational metadata (tool name, resource id, status code,
latency) but never credentials, auth headers, customer email/phone/address or
raw upstream payloads.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(ck_[A-Za-z0-9]{6,})"),
    re.compile(r"(cs_[A-Za-z0-9]{6,})"),
    re.compile(r"(AIza[0-9A-Za-z_\-]{10,})"),
    re.compile(r"(lsv2_[A-Za-z0-9_\-]{10,})"),
]

_SENSITIVE_KEYS = {
    "consumer_key",
    "consumer_secret",
    "authorization",
    "password",
    "api_key",
    "secret",
    "token",
    "email",
    "phone",
    "billing",
    "shipping",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def redact(value: str) -> str:
    """Redact credential-looking substrings and email addresses from text."""
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return EMAIL_RE.sub("<redacted-email>", redacted)


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys and values in a shallow mapping (one level deep)."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            clean[key] = "<redacted>"
        elif isinstance(value, str):
            clean[key] = redact(value)
        else:
            clean[key] = value
    return clean


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def configure_logging(level: str = "INFO", *, service: str) -> logging.Logger:
    """Configure root logging once and return the service logger."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(_RedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; route them through the same config.
    # HTTP client logs include request URLs, so they stay at WARNING unless
    # DEBUG logging is explicitly requested.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "mcp"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    noisy_level = logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(noisy_level)

    return logging.getLogger(service)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
