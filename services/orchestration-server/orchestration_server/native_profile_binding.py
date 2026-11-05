"""Trusted *identity* preflight for compiled workflow tasks.

A published task carries profile UUIDs as provenance, NOT as authorization.
The operator pins those IDs in private native-worker configuration. Exact
matching is necessary to claim such a task, but never grants provider/tool
rights; the existing fixed runner caps and gateway remain authoritative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
PROFILE_KEYS = ("agent_definition_id", "model_profile_id", "tool_policy_id")
ENV_KEYS = ("MAW_NATIVE_PROFILE_AGENT_ID", "MAW_NATIVE_PROFILE_MODEL_ID", "MAW_NATIVE_PROFILE_POLICY_ID")


class ProfileBindingError(ValueError):
    """Sanitized configuration/metadata error: no identifiers or secrets."""


@dataclass(frozen=True, repr=False)
class TrustedProfileBinding:
    agent_definition_id: str
    model_profile_id: str
    tool_policy_id: str

    def __repr__(self) -> str:
        return "TrustedProfileBinding(<redacted>)"

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not UUID.fullmatch(value)
            for value in (self.agent_definition_id, self.model_profile_id, self.tool_policy_id)
        ):
            raise ProfileBindingError("Trusted profile binding requires three valid UUIDs")

    def matches(self, refs: dict[str, str]) -> bool:
        return (
            refs["agent_definition_id"].lower() == self.agent_definition_id.lower()
            and refs["model_profile_id"].lower() == self.model_profile_id.lower()
            and refs["tool_policy_id"].lower() == self.tool_policy_id.lower()
        )


def binding_from_env(env: Mapping[str, str]) -> TrustedProfileBinding | None:
    values = [env.get(key) for key in ENV_KEYS]
    if not any(value is not None for value in values):
        return None
    if any(value is None for value in values):
        raise ProfileBindingError("Trusted profile binding must set all three UUIDs")
    return TrustedProfileBinding(*values)  # type: ignore[arg-type]


def task_matches_binding(task: Mapping[str, Any], binding: TrustedProfileBinding | None) -> bool:
    """Return False for a task belonging to another trusted profile.

    Bad server data or a published profile with no trusted local binding is a
    terminal pre-claim error. Plain legacy tasks remain eligible only for an
    explicitly unbound legacy worker; a profile-bound worker never takes them.
    """
    data = task.get("input_data")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ProfileBindingError("Malformed task input data")
    if "workflow_agent_reference" not in data:
        if "workflow_node_id" in data:
            raise ProfileBindingError("Published task lacks its agent profile reference")
        return binding is None
    refs = data["workflow_agent_reference"]
    if (
        not isinstance(refs, dict)
        or set(refs) != set(PROFILE_KEYS)
        or any(not isinstance(refs[key], str) or not UUID.fullmatch(refs[key]) for key in PROFILE_KEYS)
    ):
        raise ProfileBindingError("Malformed published agent profile reference")
    if binding is None:
        raise ProfileBindingError("Published task requires an operator-bound agent profile")
    return binding.matches(refs)
