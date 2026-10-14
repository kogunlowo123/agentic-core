"""JSON logging with correlation IDs and sensitive-key scrubbing."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

from agentic_core.domain.identifiers import new_id

_correlation: ContextVar[str | None] = ContextVar("correlation_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "private_key",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)


def correlation_id() -> str | None:
    return _correlation.get()


@contextmanager
def bind_correlation_id(value: str | None = None) -> Iterator[str]:
    """Bind a correlation ID for the current async context."""
    cid = value or new_id()
    token = _correlation.set(cid)
    try:
        yield cid
    finally:
        _correlation.reset(token)


def _add_correlation(
    _logger: Any, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    cid = _correlation.get()
    if cid is not None:
        event.setdefault("correlation_id", cid)
    return event


def scrub_sensitive(
    _logger: Any, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event[key] = "[REDACTED]"
        elif isinstance(event[key], dict):
            event[key] = _scrub_mapping(event[key])
    return event


def _scrub_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (
            "[REDACTED]"
            if k.lower() in SENSITIVE_KEYS
            else _scrub_mapping(v) if isinstance(v, dict) else v
        )
        for k, v in value.items()
    }


def configure_logging(*, service: str, environment: str, level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_correlation,
            scrub_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service, environment=environment)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
