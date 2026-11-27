"""Shared role identity invariants; no profile authorization or role registry."""

import re

INDEPENDENT_QA_ROLES = frozenset(("tester", "reviewer", "security"))
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def valid_role_identity(value: object) -> bool:
    """Use persisted AgentDefinition role syntax, including custom roles."""
    return type(value) is str and _ROLE.fullmatch(value) is not None

# Persisted profile identities and revisions must use identical bounds on
# the exporter, graph binding and private worker snapshot boundaries.
PROFILE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def valid_profile_uuid(value: object) -> bool:
    return type(value) is str and PROFILE_UUID.fullmatch(value) is not None


def valid_profile_revision_number(value: object) -> bool:
    return type(value) is int and 1 <= value <= 2147483647
