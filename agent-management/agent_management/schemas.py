"""Pydantic v2 schemas for the agent-management REST API.

Request DTOs validate incoming payloads; response DTOs render persisted state.
Secret material in ``Provider.auth_config`` is never echoed back in responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .tool_policy import VALID_KINDS

# --------------------------------------------------------------------------- providers


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(default="openrouter", description="Adapter type: openrouter|huggingface|custom|mock")
    base_url: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    rate_limits: Optional[Dict[str, Any]] = None
    is_active: bool = True

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("openrouter", "huggingface", "custom", "mock"):
            raise ValueError("type must be one of: openrouter, huggingface, custom, mock")
        return v


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    base_url: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None
    rate_limits: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    version: Optional[int] = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    base_url: Optional[str] = None
    rate_limits: Optional[Dict[str, Any]] = None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ProviderListResponse(BaseModel):
    items: List[ProviderResponse]
    total: int


# ----------------------------------------------------------------------- model profiles


class ModelProfileCreate(BaseModel):
    provider_id: str
    name: str = Field(min_length=1, max_length=255)
    model_id: str = Field(min_length=1, max_length=255)
    display_name: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)
    context_window: Optional[int] = None
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    capabilities: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("context_window")
    @classmethod
    def _nonneg_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("context_window must be >= 0")
        return v

    @field_validator("cost_per_1k_input", "cost_per_1k_output")
    @classmethod
    def _nonneg_float(cls, v: float) -> float:
        if v < 0:
            raise ValueError("cost must be >= 0")
        return v


class ModelProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    model_id: Optional[str] = None
    display_name: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    context_window: Optional[int] = None
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None
    capabilities: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None
    version: Optional[int] = None


class ModelProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: str
    name: str
    model_id: str
    display_name: Optional[str] = None
    parameters: Dict[str, Any] = {}
    context_window: Optional[int] = None
    cost_per_1k_input: float
    cost_per_1k_output: float
    capabilities: Dict[str, Any] = {}
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ModelProfileListResponse(BaseModel):
    items: List[ModelProfileResponse]
    total: int


# ------------------------------------------------------------------------- tool policies


class ToolPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    permissions: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(v) - set(VALID_KINDS)
        if unknown:
            raise ValueError(f"Unknown permission kinds: {sorted(unknown)}")
        for kind in VALID_KINDS:
            raw = v.get(kind, [])
            if raw is None:
                raw = []
            if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
                raise ValueError(f"Permission kind '{kind}' must be a list of strings")
        return v


class ToolPolicyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    permissions: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None
    version: Optional[int] = None


class ToolPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    permissions: Dict[str, Any] = {}
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ToolPolicyListResponse(BaseModel):
    items: List[ToolPolicyResponse]
    total: int


# ----------------------------------------------------------------------- agent definitions


class AgentDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    default_model_profile_id: Optional[str] = None
    default_tool_policy_id: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = Field(default_factory=dict)
    config_schema: Optional[Dict[str, Any]] = None


class AgentDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    default_model_profile_id: Optional[str] = None
    default_tool_policy_id: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    config_schema: Optional[Dict[str, Any]] = None
    version: Optional[int] = None


class AgentDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    default_model_profile_id: Optional[str] = None
    default_tool_policy_id: Optional[str] = None
    capabilities: Dict[str, Any] = {}
    config_schema: Optional[Dict[str, Any]] = None
    version: int
    created_at: datetime
    updated_at: datetime


class AgentDefinitionListResponse(BaseModel):
    items: List[AgentDefinitionResponse]
    total: int


# ----------------------------------------------------------------------- agent instances


class AgentInstanceCreate(BaseModel):
    # Either reference an existing definition by id, or pass an inline definition
    # that is used to (transiently) instantiate the instance. At least one is required.
    agent_definition_id: Optional[str] = None
    name: Optional[str] = Field(
        default=None,
        description="Inline definition name when no agent_definition_id is given",
    )
    system_prompt: Optional[str] = None
    model_profile_id: Optional[str] = None
    tool_policy_id: Optional[str] = None
    runtime_config: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("agent_definition_id")
    @classmethod
    def _not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v == "":
            raise ValueError("agent_definition_id cannot be empty")
        return v


class AgentInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_definition_id: str
    model_profile_id: Optional[str] = None
    tool_policy_id: Optional[str] = None
    status: str
    runtime_config: Dict[str, Any] = {}
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    version: int
    created_at: datetime
    updated_at: datetime


class AgentInstanceListResponse(BaseModel):
    items: List[AgentInstanceResponse]
    total: int


class LifecycleAction(BaseModel):
    """Optional metadata accompanying a lifecycle transition."""
    note: Optional[str] = None


# --------------------------------------------------------------------------- token usage


class TokenUsageResponse(BaseModel):
    id: str
    agent_instance_id: Optional[str] = None
    provider_id: Optional[str] = None
    model_profile_id: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    est_cost: float
    currency: str
    request_id: Optional[str] = None
    created_at: datetime


class UsageSummaryResponse(BaseModel):
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_est_cost: float
    currency: str = "USD"
    request_count: int
    by_model: Dict[str, Dict[str, Any]]
    by_provider: Dict[str, Dict[str, Any]]


class UsageListResponse(BaseModel):
    items: List[TokenUsageResponse]
    total: int


class CompleteRequest(BaseModel):
    """Call a provider through the API for introspection/testing."""
    provider_id: str
    model_profile_id: Optional[str] = None
    agent_instance_id: Optional[str] = None
    messages: List[Dict[str, str]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class CompleteResponse(BaseModel):
    content: str
    model: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    est_cost: float = 0.0
    usage_record_id: Optional[str] = None
    metadata: Dict[str, Any] = {}