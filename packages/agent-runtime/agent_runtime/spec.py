"""AgentSpec resolution: role → definition → instance → model/policy (ADR-108).

The configuration plane is represented with plain dataclasses and an in-memory
store. The runtime resolves an immutable :class:`AgentSpec` at run start and
never reads config again mid-run (ADR-108 §3.6, ADR-102 §3.4).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence

from .errors import ErrorKind, PlatformError, config_error
from .limits import (
    DEFAULT_MINIMAL_LIMITS,
    Budget,
    DEFAULT_PRICING,
    ResourceLimits,
    limits_for_tier,
)
from .permissions import ToolPolicy

# ---------------------------------------------------------------------------
# Configuration entities (ADR-108 §3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 1000


@dataclass(frozen=True)
class ModelProfile:
    id: str
    provider_id: str
    model_id: str
    display_name: str = ""
    version: int = 1
    parameters: Mapping[str, Any] = field(default_factory=dict)
    context_window: int = 8192
    cost_per_1k_input: float = DEFAULT_PRICING["input_per_1k"]
    cost_per_1k_output: float = DEFAULT_PRICING["output_per_1k"]
    capabilities: tuple[str, ...] = ()
    is_default: bool = False
    fallback_model_id: Optional[str] = None
    fallback_provider_id: Optional[str] = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    budget: Budget = field(default_factory=Budget.zero)

    def cost_for(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1000.0) * self.cost_per_1k_input + (
            output_tokens / 1000.0
        ) * self.cost_per_1k_output

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "version": self.version,
            "context_window": self.context_window,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "capabilities": list(self.capabilities),
            "fallback_model_id": self.fallback_model_id,
            "fallback_provider_id": self.fallback_provider_id,
        }


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    description: str = ""
    version: int = 1
    system_prompt: str = ""
    default_model_profile_id: Optional[str] = None
    default_tool_policy_id: Optional[str] = None
    capabilities: tuple[str, ...] = ()
    config_schema: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "default_model_profile_id": self.default_model_profile_id,
            "default_tool_policy_id": self.default_tool_policy_id,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class AgentInstance:
    """Configuration only — never runtime status (ADR-102 §3.3)."""

    id: str
    definition_id: str
    model_profile_id: Optional[str] = None
    tool_policy_id: Optional[str] = None
    config: Mapping[str, Any] = field(default_factory=dict)
    config_status: str = "synced"
    config_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "definition_id": self.definition_id,
            "model_profile_id": self.model_profile_id,
            "tool_policy_id": self.tool_policy_id,
            "config_status": self.config_status,
            "config_version": self.config_version,
        }


@dataclass(frozen=True)
class Role:
    name: str
    description: str = ""
    default_definition_id: str = ""
    allowed_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextPolicy:
    """What the model may see (ADR-108 §3.4)."""

    memory_levels: tuple[str, ...] = ("agent", "task")
    max_context_tokens: int = 8192
    max_upstream_summary_chars: int = 2000

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_levels": list(self.memory_levels),
            "max_context_tokens": self.max_context_tokens,
            "max_upstream_summary_chars": self.max_upstream_summary_chars,
        }


# ---------------------------------------------------------------------------
# Resolved runtime contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentSpec:
    """The immutable, reproducible runtime contract (ADR-108 §3.2)."""

    role: str
    agent_instance_id: str
    system_prompt: str
    model_profile: ModelProfile
    tool_policy: ToolPolicy
    budget: Budget
    resource_limits: ResourceLimits
    context_policy: ContextPolicy
    capabilities: tuple[str, ...]
    spec_version: str
    definition_id: str = ""
    max_turns: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "agent_instance_id": self.agent_instance_id,
            "system_prompt": self.system_prompt,
            "model_profile": self.model_profile.to_dict(),
            "tool_policy": {
                "name": self.tool_policy.name,
                "permissions": dict(self.tool_policy.permissions),
                "requires_approval": list(self.tool_policy.requires_approval),
                "version": self.tool_policy.version,
            },
            "budget": self.budget.to_dict(),
            "resource_limits": self.resource_limits.to_dict(),
            "context_policy": self.context_policy.to_dict(),
            "capabilities": list(self.capabilities),
            "spec_version": self.spec_version,
            "definition_id": self.definition_id,
            "max_turns": self.max_turns,
        }


def compute_spec_version(payload: Mapping[str, Any]) -> str:
    """Deterministic hash of the resolution inputs (ADR-108 §3.2, R5)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# In-memory configuration store + Profile Manager
# ---------------------------------------------------------------------------


class ConfigStore:
    """In-memory configuration plane (Agent Management owns this in production)."""

    def __init__(self) -> None:
        self.roles: dict[str, Role] = {}
        self.definitions: dict[str, AgentDefinition] = {}
        self.instances: dict[str, AgentInstance] = {}
        self.model_profiles: dict[str, ModelProfile] = {}
        self.tool_policies: dict[str, ToolPolicy] = {}

    # -- registration helpers (used by tests and by the API layer) ----------
    def add_role(self, role: Role) -> None:
        self.roles[role.name] = role

    def add_definition(self, definition: AgentDefinition) -> None:
        self.definitions[definition.id] = definition

    def add_instance(self, instance: AgentInstance) -> None:
        self.instances[instance.id] = instance

    def add_model_profile(self, profile: ModelProfile) -> None:
        self.model_profiles[profile.id] = profile

    def add_tool_policy(self, policy: ToolPolicy) -> None:
        self.tool_policies[policy.name] = policy
        self.tool_policies.setdefault(f"id:{policy.name}", policy)


class ProfileManager:
    """Resolves a role (and optional instance) into an immutable :class:`AgentSpec`."""

    def __init__(self, store: ConfigStore) -> None:
        self.store = store

    def resolve(
        self,
        role_name: str,
        *,
        instance_id: Optional[str] = None,
        definition_id: Optional[str] = None,
    ) -> AgentSpec:
        store = self.store
        role = store.roles.get(role_name)
        if role is None:
            raise config_error(f"unknown role {role_name!r}", role=role_name)

        instance: Optional[AgentInstance] = None
        if instance_id is not None:
            instance = store.instances.get(instance_id)
            if instance is None:
                raise config_error(f"unknown agent instance {instance_id!r}", instance_id=instance_id)

        resolved_definition_id = (
            instance.definition_id if instance else (definition_id or role.default_definition_id)
        )
        definition = store.definitions.get(resolved_definition_id)
        if definition is None:
            raise config_error(
                f"unknown agent definition {resolved_definition_id!r}",
                definition_id=resolved_definition_id,
            )

        # --- model resolution (ADR-108 §3.5): instance → definition → fail ---
        model_profile_id = (
            (instance.model_profile_id if instance else None)
            or definition.default_model_profile_id
        )
        if not model_profile_id or model_profile_id not in store.model_profiles:
            raise config_error(
                "no model profile resolved (refusing silent permissive fallback)",
                role=role_name,
                definition_id=definition.id,
                requested_model_profile_id=model_profile_id,
            )
        model_profile = store.model_profiles[model_profile_id]

        # --- tool policy resolution: instance → definition → deny-all --------
        policy_id = (instance.tool_policy_id if instance else None) or definition.default_tool_policy_id
        if policy_id and policy_id in store.tool_policies:
            tool_policy = store.tool_policies[policy_id]
        elif policy_id and f"id:{policy_id}" in store.tool_policies:
            tool_policy = store.tool_policies[f"id:{policy_id}"]
        else:
            # Missing policy = deny all (ADR-108 §3.3 rule 3).
            tool_policy = ToolPolicy.deny_all()

        # --- capabilities = role ∩ definition (intersection, never union) ----
        capabilities = tuple(
            c for c in role.allowed_capabilities if c in set(definition.capabilities)
        )

        # --- budget / limits -------------------------------------------------
        config = dict(instance.config) if instance else {}
        budget = _budget_from_config(config, model_profile)
        resource_limits = _limits_from_config(config)

        context_policy = ContextPolicy(
            max_context_tokens=min(
                int(config.get("max_context_tokens", model_profile.context_window)),
                model_profile.context_window,
            )
        )

        spec_payload = {
            "role": role_name,
            "definition": definition.to_dict(),
            "instance": instance.to_dict() if instance else None,
            "model": model_profile.to_dict(),
            "policy": {
                "name": tool_policy.name,
                "permissions": dict(tool_policy.permissions),
                "version": tool_policy.version,
            },
            "capabilities": list(capabilities),
            "budget": budget.to_dict(),
            "limits": resource_limits.to_dict(),
        }
        spec_version = compute_spec_version(spec_payload)

        return AgentSpec(
            role=role_name,
            agent_instance_id=instance.id if instance else f"role:{role_name}",
            system_prompt=definition.system_prompt,
            model_profile=model_profile,
            tool_policy=tool_policy,
            budget=budget,
            resource_limits=resource_limits,
            context_policy=context_policy,
            capabilities=capabilities,
            spec_version=spec_version,
            definition_id=definition.id,
            max_turns=int(config.get("max_turns", 50)),
        )


def _budget_from_config(config: Mapping[str, Any], model_profile: ModelProfile) -> Budget:
    raw = config.get("budget")
    if raw is None:
        return model_profile.budget
    if isinstance(raw, Budget):
        return raw
    if isinstance(raw, Mapping):
        return Budget(
            max_steps=int(raw.get("max_steps", 0)),
            max_tokens=int(raw.get("max_tokens", 0)),
            max_cost_usd=float(raw.get("max_cost_usd", 0.0)),
            max_wall_time_ms=int(raw.get("max_wall_time_ms", 0)),
        )
    raise config_error("budget config must be a mapping")


def _limits_from_config(config: Mapping[str, Any]) -> ResourceLimits:
    tier = config.get("resource_tier")
    if tier is not None:
        return limits_for_tier(str(tier))
    raw = config.get("resource_limits")
    if raw is None:
        return DEFAULT_MINIMAL_LIMITS
    if isinstance(raw, ResourceLimits):
        return raw
    if isinstance(raw, Mapping):
        base = DEFAULT_MINIMAL_LIMITS
        return replace(base, **{k: int(v) for k, v in raw.items()})
    raise config_error("resource_limits config must be a mapping")


# ---------------------------------------------------------------------------
# Context construction (ADR-108 §3.4, ADR-111)
# ---------------------------------------------------------------------------

#: Fields that must never reach the model prompt (ADR-108 §3.4, ADR-111).
FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "lease",
        "lease_id",
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "workspace_root",
        "tool_policy",
        "policy",
        "git_credentials",
        "credentials",
        "auth_config",
        "authorization",
    }
)


def build_model_context(
    spec: AgentSpec,
    *,
    task_title: str,
    task_description: str = "",
    task_input: Optional[Mapping[str, Any]] = None,
    upstream: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Build the user-level message history the model may see.

    Only user-level task data and the bounded, service-generated upstream
    handoff are included; authority (lease/key/workspace-root/policy) never is.
    The result is validated against :data:`FORBIDDEN_CONTEXT_KEYS` and raises if
    a forbidden key slipped in.
    """
    messages: list[dict[str, Any]] = []
    if spec.system_prompt:
        messages.append({"role": "system", "content": spec.system_prompt})

    parts = [f"Task: {task_title}"]
    if task_description:
        parts.append(task_description)
    if task_input:
        safe_input = _strip_forbidden(dict(task_input))
        parts.append("Input: " + json.dumps(safe_input, sort_keys=True))
    if upstream:
        summaries = []
        budget = spec.context_policy.max_upstream_summary_chars
        for entry in upstream:
            summary = str(entry.get("summary", ""))[:budget]
            summaries.append({"prev_task_id": entry.get("prev_task_id"), "summary": summary})
        if summaries:
            parts.append("Upstream: " + json.dumps(summaries, sort_keys=True))
    messages.append({"role": "user", "content": "\n\n".join(parts)})

    _assert_no_forbidden(messages)
    return messages


def _strip_forbidden(data: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in FORBIDDEN_CONTEXT_KEYS:
            continue
        if isinstance(value, Mapping):
            clean[key] = _strip_forbidden(value)
        else:
            clean[key] = value
    return clean


def _assert_no_forbidden(messages: Sequence[Mapping[str, Any]]) -> None:
    def _walk(obj: Any) -> None:
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                if str(key).lower() in FORBIDDEN_CONTEXT_KEYS:
                    raise PlatformError(
                        ErrorKind.CONFIG_ERROR,
                        f"forbidden field {key!r} must never enter the model context",
                        context={"field": key},
                    )
                _walk(value)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _walk(item)

    _walk(messages)
