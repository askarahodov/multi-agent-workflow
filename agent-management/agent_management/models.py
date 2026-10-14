"""SQLAlchemy async models for the agent-management subsystem.

Covers the agent/provider portion of the canonical 23-entity architecture:
``providers``, ``model_profiles``, ``agent_definitions``, ``agent_instances``,
``tool_policies`` and ``token_usage``. IDs are UUID strings (matching the
orchestration server convention), mutable entities carry a ``version`` column for
optimistic locking, and flexible attributes are stored as JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (
        CheckConstraint(
            "type IN ('openrouter','huggingface','custom','mock')",
            name="ck_provider_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="openrouter")
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    auth_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rate_limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    model_profiles = relationship("ModelProfile", back_populates="provider")


class ModelProfile(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (
        UniqueConstraint("provider_id", "name", name="uq_model_profile_provider_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_per_1k_input: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_per_1k_output: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    provider: Mapped["Provider"] = relationship(back_populates="model_profiles")


class ToolPolicy(Base):
    __tablename__ = "tool_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # permissions JSON: {fs_read: [paths...], fs_write: [paths...], git: [...],
    #                    shell: [...], network: [...]}
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint("name", name="uq_agent_definition_name"),
        Index("ix_agent_definition_default_model", "default_model_profile_id"),
        Index("ix_agent_definition_default_tool", "default_tool_policy_id"),
        CheckConstraint("max_concurrency >= 1", name="ck_agent_max_concurrency_ge1"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id"), nullable=True
    )
    default_tool_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_policies.id"), nullable=True
    )
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ADR-017 profile fields (t_662e8363 adjudicated deltas — ACCEPT)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="generalist")
    max_concurrency: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        server_default="1"
    )
    output_contract_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    supported_stages: Mapped[str | None] = mapped_column(
        String, nullable=False, default="[]", server_default="'[]'"
    )
    skills: Mapped[str | None] = mapped_column(
        String, nullable=False, default="[]", server_default="'[]'"
    )
    budget_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    config_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    instances = relationship("AgentInstance", back_populates="definition")


class AgentInstance(Base):
    __tablename__ = "agent_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','terminated')",
            name="ck_agent_instance_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_definition_id: Mapped[str] = mapped_column(
        ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    model_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id"), nullable=True
    )
    tool_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_policies.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    runtime_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    definition: Mapped["AgentDefinition"] = relationship(back_populates="instances")


class TokenUsage(Base):
    __tablename__ = "token_usage"
    __table_args__ = (
        Index("ix_token_usage_agent_instance", "agent_instance_id"),
        Index("ix_token_usage_provider", "provider_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_instances.id"), nullable=True, index=True
    )
    provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("providers.id"), nullable=True, index=True
    )
    model_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    est_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )