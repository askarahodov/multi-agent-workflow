"""Pydantic request/response schemas for the orchestration REST API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, StrictInt, field_validator

T = TypeVar("T")


# --- cursor-based pagination (ADR-101: CursorPage everywhere on the wire) ---


class CursorParams(BaseModel):
    """Query parameters for cursor-based pagination: `?after=<cursor>&limit=<n>`."""

    after: Optional[str] = Field(default=None, description="Opaque cursor from the previous page's `next_cursor`.")
    limit: Optional[int] = Field(
        default=50, ge=1, le=200, description="Maximum number of items to return."
    )


class CursorPage(BaseModel, Generic[T]):
    """Uniform list envelope: `{items: [...], next_cursor: string|null}`."""

    items: list[T]
    next_cursor: Optional[str] = None


# --- workflow definitions / versions (design-time domain, ADR-102) ---


class WorkflowDefinitionDTO(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    definition: dict[str, Any]
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    version: int

    model_config = {"from_attributes": True}


class CreateWorkflowRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    definition: dict[str, Any]


class UpdateWorkflowRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    definition: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class WorkflowVersionDTO(BaseModel):
    id: str
    workflow_definition_id: str
    version_number: int
    definition_snapshot: dict[str, Any]
    changelog: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CreateVersionRequest(BaseModel):
    definition_snapshot: dict[str, Any]
    changelog: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WorkspaceCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=255)
    path: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class WorkspaceResponse(BaseModel):
    id: str
    project_id: str
    name: str
    path: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    version: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ContractCreate(BaseModel):
    project_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    # Exposed as "schema" on the wire; the python name avoids shadowing
    # BaseModel.schema (Pydantic emits a warning otherwise).
    schema_: dict[str, Any] = Field(..., alias="schema")

    model_config = {"populate_by_name": True}


class ContractResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    schema_: dict[str, Any] = Field(..., alias="schema")
    version: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class AgentRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    metadata: Optional[dict[str, Any]] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    status: str
    # Read from the ORM attribute ``agent_metadata`` (column "metadata") and
    # serialize as "metadata". Only a serialization alias is used, because a
    # validation alias "metadata" would resolve to SQLAlchemy's MetaData.
    agent_metadata: Optional[dict[str, Any]] = Field(
        default=None, serialization_alias="metadata"
    )
    version: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskSpec(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    node_id: Optional[str] = None
    description: Optional[str] = None
    contract_id: Optional[str] = None
    input_data: Optional[dict[str, Any]] = None
    priority: int = 0
    # Zero-based prerequisites in the submitted task list. Only earlier tasks
    # may be referenced; the engine persists canonical task IDs.
    depends_on: list[StrictInt] = Field(default_factory=list, max_length=16)


class RunCreate(BaseModel):
    project_id: str
    workspace_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=255)
    triggered_by: Optional[str] = None
    input_data: Optional[dict[str, Any]] = None
    retry_policy: Optional[dict[str, Any]] = None
    tasks: list[TaskSpec] = Field(default_factory=list)


class RunResponse(BaseModel):
    id: str
    project_id: str
    workspace_id: Optional[str] = None
    name: str
    status: str
    input_data: Optional[dict[str, Any]] = None
    output_data: Optional[dict[str, Any]] = None
    triggered_by: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    version: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: str
    workflow_run_id: str
    node_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    contract_id: Optional[str] = None
    input_data: Optional[dict[str, Any]] = None
    output_data: Optional[dict[str, Any]] = None
    priority: int
    attempt_count: int
    max_attempts: int
    retry_at: Optional[datetime] = None
    assigned_agent_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    version: int
    created_at: Optional[datetime] = None

    @field_validator("retry_at")
    @classmethod
    def normalize_retry_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite drops tzinfo even for DateTime(timezone=True). The engine
        # treats these values as UTC; expose the same unambiguous contract
        # to separately deployed workers.
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    model_config = {"from_attributes": True}


class AttemptResponse(BaseModel):
    id: str
    task_id: str
    attempt_number: int
    agent_id: Optional[str] = None
    status: str
    input_data: Optional[dict[str, Any]] = None
    output_data: Optional[dict[str, Any]] = None
    verification_result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    version: int

    model_config = {"from_attributes": True}


class ClaimRequest(BaseModel):
    agent_id: str


class ClaimAttemptResponse(AttemptResponse):
    """Only the claim response may carry the one-time opaque capability."""
    lease_token: Optional[str] = Field(default=None, json_schema_extra={"readOnly": True})
    lease_generation: Optional[int] = None
    lease_expires_at: Optional[datetime] = None


class AttemptLeaseRenewRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    lease_token: str = Field(..., min_length=20, max_length=128, json_schema_extra={"writeOnly": True})


class AttemptLeaseResponse(BaseModel):
    generation: int
    expires_at: datetime


class SubmitRequest(BaseModel):
    output: dict[str, Any] = ...


class FailRequest(BaseModel):
    error: str = Field(..., min_length=1)


class BlockRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ReconciliationRequest(BaseModel):
    """Operator attests evidence metadata, never supplies a task transition."""
    decision: Literal[
        "UNKNOWN", "CONFIRMED_SIDE_EFFECT", "CONFIRMED_NO_SIDE_EFFECT",
    ]
    evidence_ref: str = Field(
        ..., min_length=3, max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$",
    )
    evidence_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class ReconciliationResponse(BaseModel):
    task_id: str
    decision: str
    evidence_ref: str
    evidence_sha256: str
    operator_subject: str
    decided_at: datetime

    model_config = {"from_attributes": True}



class RedactedToolLedgerEntry(BaseModel):
    call_ref: str
    tool: str
    state: Literal["CLAIMED", "SUCCEEDED", "DENIED"]


class InterruptedAttemptLedger(BaseModel):
    attempt_id: str
    record_status: Literal["RECORDS", "NO_RECORDS"]
    entries: list[RedactedToolLedgerEntry]


class RecoveryLedgerReport(BaseModel):
    task_id: str
    ledger_status: Literal["AVAILABLE"]
    attempts: list[InterruptedAttemptLedger]



class ApiStatus(BaseModel):
    status: str
    recovered_attempts: int = 0
    recovered_tasks: int = 0
    pending_due_tasks: int = 0


class ProblemDetail(BaseModel):
    """RFC 9457 Problem Details document returned by every error response."""

    type: str
    title: str
    status: int
    detail: str
    instance: Optional[str] = None
    errors: Optional[dict[str, list[str]]] = None