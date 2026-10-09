"""Pydantic request/response schemas for the orchestration REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


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
    assigned_agent_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    version: int
    created_at: Optional[datetime] = None

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


class SubmitRequest(BaseModel):
    output: dict[str, Any] = ...


class FailRequest(BaseModel):
    error: str = Field(..., min_length=1)


class BlockRequest(BaseModel):
    reason: str = Field(..., min_length=1)


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