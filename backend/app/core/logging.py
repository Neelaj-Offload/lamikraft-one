"""Structured logging with redaction.

Logs never carry tokens, passwords, cookies, provider keys, personal message bodies or restricted
fields (e.g. costing). Field guards registered by modules add their field names to the deny list.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|authorization|cookie|api[_-]?key|csrf|otp|totp|signature|session_id|"
    r"recovery|private|body_text|message_body|transcript)",
    re.IGNORECASE,
)
_restricted_fields: set[str] = set()
_MAX_STRING = 512


def register_restricted_log_fields(names: Iterable[str]) -> None:
    _restricted_fields.update(n.lower() for n in names)


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "<depth>"
    if isinstance(value, dict):
        return {k: ("[redacted]" if _is_sensitive(k) else _scrub(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in value]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + "…"
    return value


def _is_sensitive(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    return bool(_SENSITIVE_KEY.search(key)) or key.lower() in _restricted_fields


def redact_processor(_logger: Any, _name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event_dict.keys()):
        if key in ("event", "level", "timestamp", "logger"):
            continue
        if _is_sensitive(key):
            event_dict[key] = "[redacted]"
        else:
            event_dict[key] = _scrub(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    for noisy in ("sqlalchemy.engine", "httpx", "anthropic", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
