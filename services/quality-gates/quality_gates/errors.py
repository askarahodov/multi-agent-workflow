"""Domain errors for the quality-gates subsystem.

Centralises the error types the gates, evidence store and pipeline raise, so
the API layer can translate them into consistent HTTP responses and the
orchestrator can classify failures without string matching.
"""

from __future__ import annotations


class QualityGateError(Exception):
    """Base class for all quality-gates errors."""


class GateNotFoundError(QualityGateError):
    """A requested gate definition does not exist."""


class GateExecutionError(QualityGateError):
    """A gate failed at the infrastructure level (could not run)."""


class GateFailedError(QualityGateError):
    """A gate ran and reported failures in its findings."""


class TaskNotFoundError(QualityGateError):
    """The referenced upstream task/workspace is unknown."""


class ReleaseNotFoundError(QualityGateError):
    """A requested release candidate does not exist."""


class ReleaseNotAwaitingApprovalError(QualityGateError):
    """Release approval/rejection attempted on a candidate not in awaiting state."""


class TransitionForbiddenError(QualityGateError):
    """A workflow transition was refused because a required gate has not passed."""


class EvidenceStorageError(QualityGateError):
    """Evidence could not be persisted or retrieved reliably."""
