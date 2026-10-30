"""Domain exceptions rendered as RFC 9457 Problem Details documents.

The REST API surfaces every error as a structured Problem Details document with a
stable ``type`` URI, a HTTP ``status``, a human ``title``, a ``detail`` message and
optional field-level ``errors`` information. Providers also raise a subset of these
errors (e.g. ``ProviderError``, ``TokenizationError``) so boundaries stay consistent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class AgentManagementError(Exception):
    """Base class for all agent-management errors."""

    status_code: int = 500
    title: str = "Internal error"
    type_uri: str = "about:blank"

    def __init__(
        self,
        detail: str,
        *,
        errors: Optional[Dict[str, List[str]]] = None,
        instance: Optional[str] = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors
        self.instance = instance
        self.extra = extra

    def to_problem(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "type": self.type_uri,
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
        }
        if self.instance:
            doc["instance"] = self.instance
        if self.errors:
            doc["errors"] = self.errors
        doc.update(self.extra)
        return doc


class NotFoundError(AgentManagementError):
    status_code = 404
    title = "Resource not found"
    type_uri = "urn:agent-management:error:not-found"


class ValidationError(AgentManagementError):
    status_code = 400
    title = "Validation failed"
    type_uri = "urn:agent-management:error:validation"


class BusinessRuleError(AgentManagementError):
    status_code = 422
    title = "Business rule violation"
    type_uri = "urn:agent-management:error:business-rule"


class ConflictError(AgentManagementError):
    status_code = 409
    title = "Conflict"
    type_uri = "urn:agent-management:error:conflict"


class OptimisticLockError(ConflictError):
    """Raised when an update targets a stale ``version`` (concurrent writer)."""

    title = "Optimistic lock conflict"
    type_uri = "urn:agent-management:error:optimistic-lock"


class DuplicateKeyError(ConflictError):
    title = "Duplicate key"
    type_uri = "urn:agent-management:error:duplicate-key"


class StateTransitionError(BusinessRuleError):
    """Raised when a lifecycle transition is not allowed by the state machine."""

    title = "Illegal state transition"
    type_uri = "urn:agent-management:error:state-transition"


class ToolPolicyDenied(AgentManagementError):
    """Raised when a tool action is refused by the agent's tool policy."""

    status_code = 403
    title = "Tool action denied"
    type_uri = "urn:agent-management:error:tool-policy-denied"


class ProviderError(AgentManagementError):
    """Base for all LLM provider adapter failures."""

    status_code = 502
    title = "Provider error"
    type_uri = "urn:agent-management:error:provider"


class ProviderNotFoundError(NotFoundError):
    """Raised when no adapter is registered for a provider type."""

    title = "Provider adapter not found"
    type_uri = "urn:agent-management:error:provider-adapter-not-found"


class TokenUsageError(AgentManagementError):
    """Raised when a provider returns no usable usage accounting."""

    status_code = 422
    title = "Token usage accounting failed"
    type_uri = "urn:agent-management:error:token-usage"