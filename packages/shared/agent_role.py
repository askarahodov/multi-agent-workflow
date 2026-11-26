"""Shared role identity invariants; no profile authorization or role registry."""

import re

INDEPENDENT_QA_ROLES = frozenset(("tester", "reviewer", "security"))
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def valid_role_identity(value: object) -> bool:
    """Use persisted AgentDefinition role syntax, including custom roles."""
    return type(value) is str and _ROLE.fullmatch(value) is not None
