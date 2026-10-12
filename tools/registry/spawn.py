"""Spawn-agent tool (PRD §13 / ADR-012 §3.4).

``spawn_agent`` lets an agent request the creation of a *child* agent run. The
child can never expand the parent's rights: its policy must be a subset of the
parent's (enforced here, ownership lives in orchestration), and the child
execution context is strictly narrower (see
:meth:`ExecutionContext.child_for_spawn`).

This module ships the policy subset check; the actual child-run creation is a
post-v1 orchestration integration.
"""

from __future__ import annotations

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolPolicyDeniedError,
    ToolSpec,
)


def _is_subset(child: dict, parent: dict) -> bool:
    """True when every grant in ``child`` is also present in ``parent``."""
    for kind, allowlist in child.items():
        parent_list = parent.get(kind, [])
        if "*" in parent_list:
            continue
        for item in allowlist:
            if item in parent_list:
                continue
            if any(parent_item.endswith("**") and item.startswith(parent_item.rstrip("**")) for parent_item in parent_list):
                continue
            return False
    return True


async def _spawn_agent(params: dict, context: ExecutionContext) -> dict:
    child_policy = params.get("policy", {})
    parent_policy = params.get("_parent_policy", params.get("parent_policy", {}))
    if not _is_subset(child_policy or {}, parent_policy or {}):
        raise ToolPolicyDeniedError("child policy is not a subset of the parent policy")
    if context.parent_run_id is not None:
        raise ToolPolicyDeniedError("spawn is not allowed from a child agent run")
    # v1: the registry records the request; orchestration integration creates the
    # child run. Return a structured pending-request handle.
    return {
        "status": "pending",
        "agent_definition_id": params.get("agent_definition_id"),
        "run_id": context.run_id,
        "policy": child_policy,
    }


def register_spawn(registry) -> None:
    registry.register(
        ToolSpec(
            name="spawn_agent",
            category=ToolCategory.SPAWN,
            description="Request a child agent run with a strictly-subset policy (v1: pending handle).",
            params_schema={
                "type": "object",
                "properties": {
                    "agent_definition_id": {"type": "string"},
                    "policy": {"type": "object"},
                    "parent_policy": {"type": "object"},
                },
                "required": ["agent_definition_id"],
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "agent_definition_id": {"type": ["string", "null"]},
                    "run_id": {"type": "string"},
                    "policy": {"type": "object"},
                },
                "required": ["status", "run_id"],
            },
            required_policy=["spawn"],
            default_timeout_ms=5000,
            is_destructive=True,
        ),
        handler=_spawn_agent,
    )