"""Domain exceptions and RFC 9457 Problem Details helpers.

Every error surfaced through the REST API is rendered as a Problem Details
document (RFC 9457): ``type``, ``title``, ``status``, ``detail``, ``instance``
plus an optional ``errors`` map for field-level validation details.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class OrchestrationError(Exception):
    """Base class for all platform-owned orchestration errors."""

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


class NotFoundError(OrchestrationError):
    status_code = 404
    title = "Resource not found"
    type_uri = "urn:orchestration:error:not-found"


class ValidationError(OrchestrationError):
    status_code = 400
    title = "Validation failed"
    type_uri = "urn:orchestration:error:validation"


class BusinessRuleError(OrchestrationError):
    status_code = 422
    title = "Business rule violation"
    type_uri = "urn:orchestration:error:business-rule"


class ConflictError(OrchestrationError):
    status_code = 409
    title = "Conflict"
    type_uri = "urn:orchestration:error:conflict"


class OptimisticLockError(ConflictError):
    """Raised when an update targets a stale ``version`` (concurrent writer)."""

    title = "Optimistic lock conflict"
    type_uri = "urn:orchestration:error:optimistic-lock"


class DuplicateKeyError(ConflictError):
    title = "Duplicate key"
    type_uri = "urn:orchestration:error:duplicate-key"


class StateTransitionError(BusinessRuleError):
    """Raised when a transition is not allowed by the platform state machine."""

    title = "Illegal state transition"
    type_uri = "urn:orchestration:error:state-transition"


class ContractVerificationError(BusinessRuleError):
    """Raised when submitted output does not satisfy the task contract."""

    title = "Contract verification failed"
    type_uri = "urn:orchestration:error:contract-verification"


class AuthenticationError(OrchestrationError):
    status_code = 401
    title = "Unauthorized"
    type_uri = "urn:orchestration:error:unauthorized"
