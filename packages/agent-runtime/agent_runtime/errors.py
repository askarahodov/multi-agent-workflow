"""Error taxonomy for the native agent runtime (ADR-104 §3.1).

Every failure in the runtime is represented as a :class:`PlatformError` carrying
an :class:`ErrorKind`. The kind encodes two normative facts the rest of the
system relies on:

* ``code`` — a stable, machine-readable string used in structured events/logs.
* ``retryable`` — whether the failure is transient (retry / requeue without a
  failure tick) or terminal (block / needs input).

Keeping the taxonomy in one place prevents call sites from inventing their own
ad-hoc booleans (``ADR-104`` R8: *no silent failures*).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ErrorKind(Enum):
    """Canonical error kinds with ``(code, retryable)`` semantics."""

    # Provider errors
    PROVIDER_TIMEOUT = ("provider_timeout", True)
    PROVIDER_RATE_LIMIT = ("provider_rate_limit", True)  # requeue without failure tick
    PROVIDER_AUTH = ("provider_auth", False)  # block -> needs_input
    PROVIDER_SERVER = ("provider_server", True)
    PROVIDER_BAD_MODEL = ("provider_bad_model", False)  # pin to a live model

    # Tool errors
    TOOL_TIMEOUT = ("tool_timeout", True)
    TOOL_POLICY_DENIED = ("tool_policy_denied", False)  # block the run
    TOOL_CONTAINER_CRASH = ("tool_container_crash", True)
    TOOL_OOM = ("tool_oom", True)

    # Agent run errors
    BUDGET_EXHAUSTED = ("budget_exhausted", False)  # terminate the run
    CONTRACT_VERIFICATION_FAILED = ("verification_failed", False)
    HUMAN_APPROVAL_TIMEOUT = ("approval_timeout", True)

    # Orchestration errors
    GATE_UNAVAILABLE = ("gate_unavailable", True)  # block, never pass
    GATE_FAILED = ("gate_failed", False)
    CLAIM_RACE = ("claim_race", True)
    CLAIM_DENIED = ("claim_denied", False)  # prerequisite not completed
    DB_DEADLOCK = ("db_deadlock", True)

    # Coordination errors
    WORKER_CRASH = ("worker_crash", True)
    HEARTBEAT_STALE = ("heartbeat_stale", True)
    PROTOCOL_VIOLATION = ("protocol_violation", True)
    UNKNOWN_ASSIGNEE = ("unknown_assignee", False)

    # Configuration / isolation errors (fail-closed, ADR-107 §3.4)
    CONFIG_ERROR = ("config_error", False)
    ISOLATION_UNAVAILABLE = ("isolation_unavailable", False)  # no unisolated fallback
    NOT_FOUND = ("not_found", False)
    VALIDATION_ERROR = ("validation_error", False)

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def retryable(self) -> bool:
        return self.value[1]

    @classmethod
    def from_code(cls, code: str) -> "ErrorKind":
        for kind in cls:
            if kind.code == code:
                return kind
        raise KeyError(code)


class PlatformError(Exception):
    """Base class for every runtime failure (ADR-104 §3.1).

    ``retryable`` is derived from the kind unless explicitly overridden, which
    lets a concrete call site tighten (never loosen) the default.
    """

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        retryable: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = kind.retryable if retryable is None else retryable
        self.context: dict[str, Any] = dict(context or {})

    @property
    def code(self) -> str:
        return self.kind.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "context": self.context,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PlatformError(kind={self.kind.name}, message={self.message!r}, retryable={self.retryable})"


@dataclass(frozen=True)
class RedactionNote:
    """Placeholder marking a redacted field in an event payload (never logged raw)."""

    field: str
    note: str = "***REDACTED***"


def is_retryable(exc: BaseException) -> bool:
    """Return True when *exc* is a transient :class:`PlatformError`."""
    if isinstance(exc, PlatformError):
        return exc.retryable
    return False


def _kind(kind: ErrorKind, message: str, **context: Any) -> PlatformError:
    return PlatformError(kind, message, context=context or None)


def policy_denied(action: str, resource: str = "", reason: str = "") -> PlatformError:
    msg = reason or f"tool action {action!r} denied by policy"
    if resource:
        msg = f"{msg} for resource {resource!r}"
    return _kind(ErrorKind.TOOL_POLICY_DENIED, msg, action=action, resource=resource)


def budget_exhausted(violations: list[str]) -> PlatformError:
    return _kind(
        ErrorKind.BUDGET_EXHAUSTED,
        f"budget exhausted: {', '.join(violations)}",
        violations=list(violations),
    )


def gate_unavailable(gate: str, reason: str = "") -> PlatformError:
    return _kind(
        ErrorKind.GATE_UNAVAILABLE,
        f"quality gate {gate!r} unavailable (fail-closed): {reason}".strip(),
        gate=gate,
    )


def gate_failed(gate: str, findings: list[str] | None = None) -> PlatformError:
    return _kind(
        ErrorKind.GATE_FAILED,
        f"quality gate {gate!r} failed",
        gate=gate,
        findings=list(findings or []),
    )


def claim_denied(task_id: str, reason: str) -> PlatformError:
    return _kind(ErrorKind.CLAIM_DENIED, reason, task_id=task_id)


def validation_error(message: str, **context: Any) -> PlatformError:
    return _kind(ErrorKind.VALIDATION_ERROR, message, **context)


def isolation_unavailable(message: str, **context: Any) -> PlatformError:
    return _kind(ErrorKind.ISOLATION_UNAVAILABLE, message, **context)


def config_error(message: str, **context: Any) -> PlatformError:
    return _kind(ErrorKind.CONFIG_ERROR, message, **context)


@dataclass
class ErrorRecord:
    """Structured, serialisable snapshot of an error for events/logs (ADR-106)."""

    code: str
    message: str
    retryable: bool
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_exception(cls, exc: BaseException) -> "ErrorRecord":
        if isinstance(exc, PlatformError):
            return cls(exc.code, exc.message, exc.retryable, dict(exc.context))
        return cls(
            ErrorKind.VALIDATION_ERROR.code,
            str(exc),
            False,
            {"exception_type": type(exc).__name__},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "context": self.context,
        }
