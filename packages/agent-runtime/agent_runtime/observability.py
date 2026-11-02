"""Structured logging, event hooks and metrics (ADR-106).

Every log line and event is one JSON object with the required correlation fields.
Sensitive keys are redacted before serialisation, so a mis-typed context can
never leak a secret into the log stream (ADR-106 §3.1, R6).
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping, Optional

#: Keys redacted anywhere they appear in a log/event context (ADR-106 §3.1).
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "auth_config",
        "authorization",
        "cookie",
        "lease",
        "lease_id",
        "workspace_root",
        "private_key",
        "credentials",
    }
)
_REDACTED = "***REDACTED***"

_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)


def new_id(prefix: str = "id") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def sanitize_context(ctx: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive keys, returning a fresh structure."""

    def _sanitize(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            out: dict[str, Any] = {}
            for key, value in obj.items():
                if str(key).lower() in SENSITIVE_KEYS:
                    out[key] = _REDACTED
                else:
                    out[key] = _sanitize(value)
            return out
        if isinstance(obj, (list, tuple)):
            return [_sanitize(v) for v in obj]
        return obj

    return _sanitize(dict(ctx))


@contextlib.contextmanager
def correlation(
    *,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
) -> Iterator[dict[str, Optional[str]]]:
    """Bind correlation fields for the duration of the ``with`` block."""
    tokens = []
    if correlation_id is not None:
        tokens.append((_correlation_id, _correlation_id.set(correlation_id)))
    if trace_id is not None:
        tokens.append((_trace_id, _trace_id.set(trace_id)))
    if span_id is not None:
        tokens.append((_span_id, _span_id.set(span_id)))
    try:
        yield current_ids()
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_ids() -> dict[str, Optional[str]]:
    return {
        "correlation_id": _correlation_id.get(),
        "trace_id": _trace_id.get(),
        "span_id": _span_id.get(),
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LogRecord:
    level: str
    service: str
    logger: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_timestamp)
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "service": self.service,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "logger": self.logger,
            "message": self.message,
            "context": self.context,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class StructuredLogger:
    """Emits one redacted JSON object per log call (ADR-106 §3.1).

    ``sink`` receives each serialised record; the default writes to the standard
    ``logging`` module. Records are always retained in :attr:`records` for tests
    and in-process diagnostics.
    """

    def __init__(
        self,
        service: str,
        *,
        sink: Optional[Callable[[str], None]] = None,
        min_level: str = "DEBUG",
    ) -> None:
        self.service = service
        self._sink = sink
        self.min_level = min_level
        self.records: list[LogRecord] = []
        self._order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

    def _emit(self, level: str, logger: str, message: str, context: Mapping[str, Any]) -> LogRecord:
        ids = current_ids()
        record = LogRecord(
            level=level,
            service=self.service,
            logger=logger,
            message=message,
            context=sanitize_context(context),
            correlation_id=ids["correlation_id"],
            trace_id=ids["trace_id"],
            span_id=ids["span_id"],
        )
        self.records.append(record)
        if self._order[level] >= self._order.get(self.min_level, 0):
            line = record.to_json()
            if self._sink is not None:
                self._sink(line)
            else:  # pragma: no cover - default routing
                logging.getLogger(logger).log(self._order[level], line)
        return record

    def debug(self, logger: str, message: str, **context: Any) -> LogRecord:
        return self._emit("DEBUG", logger, message, context)

    def info(self, logger: str, message: str, **context: Any) -> LogRecord:
        return self._emit("INFO", logger, message, context)

    def warning(self, logger: str, message: str, **context: Any) -> LogRecord:
        return self._emit("WARNING", logger, message, context)

    def error(self, logger: str, message: str, **context: Any) -> LogRecord:
        return self._emit("ERROR", logger, message, context)

    def critical(self, logger: str, message: str, **context: Any) -> LogRecord:
        return self._emit("CRITICAL", logger, message, context)


# ---------------------------------------------------------------------------
# Event bus / observability hooks
# ---------------------------------------------------------------------------


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_timestamp)
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "payload": sanitize_context(self.payload),
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


class EventBus:
    """Synchronous pub/sub used as the runtime's observability hook surface.

    Handlers must never break the run: an exception in a subscriber is swallowed
    (and recorded on ``failed_handlers``) so observability cannot fail the work.
    """

    def __init__(self) -> None:
        self._handlers: list[Callable[[Event], None]] = []
        self.events: list[Event] = []
        self.failed_handlers: list[tuple[str, str]] = []

    def subscribe(self, handler: Callable[[Event], None]) -> None:
        self._handlers.append(handler)

    def publish(self, event_type: str, payload: Optional[Mapping[str, Any]] = None) -> Event:
        ids = current_ids()
        event = Event(
            type=event_type,
            payload=dict(payload or {}),
            correlation_id=ids["correlation_id"],
            trace_id=ids["trace_id"],
            span_id=ids["span_id"],
        )
        self.events.append(event)
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - observability never fails the run
                self.failed_handlers.append((event_type, str(exc)))
        return event

    def types(self) -> list[str]:
        return [e.type for e in self.events]


# ---------------------------------------------------------------------------
# Metrics (ADR-106 §3.3, Prometheus text format)
# ---------------------------------------------------------------------------


class MetricsRegistry:
    """A tiny counter registry rendering Prometheus text exposition."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        self._counters[key] = self._counters.get(key, 0.0) + amount

    def value(self, name: str, **labels: str) -> float:
        return self._counters.get((name, tuple(sorted(labels.items()))), 0.0)

    def render(self) -> str:
        lines: list[str] = []
        for (name, labels), value in sorted(self._counters.items()):
            label_str = ""
            if labels:
                label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
            lines.append(f"{name}{label_str} {value:g}")
        return "\n".join(lines)
