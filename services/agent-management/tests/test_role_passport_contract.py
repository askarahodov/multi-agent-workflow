"""Validate normative passports against the existing agent-management boundary.

This is a documentation contract test, not dispatcher authorization.
"""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from agent_management.tool_policy import (
    INDEPENDENT_QA_ROLES,
    VALID_KINDS,
    ToolPolicyEngine,
    role_accepts_policy,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "docs/governance/role-passports.json"
SCHEMA = ROOT / "docs/governance/role-passports.schema.json"


@pytest.fixture
def contract():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return json.loads(CATALOG.read_text(encoding="utf-8")), Draft202012Validator(schema)


def test_catalog_is_valid_and_does_not_grant_runtime_permissions(contract):
    catalog, validator = contract
    validator.validate(catalog)
    assert catalog["runtime_authorization"] is False
    assert {r["role"] for r in catalog["roles"] if r["independent_qa"]} == INDEPENDENT_QA_ROLES
    for role in catalog["roles"]:
        assert role["allowed_tools"] == []
        assert all(not ToolPolicyEngine.allow({}, kind, "example") for kind in VALID_KINDS)
        if role["independent_qa"]:
            assert role_accepts_policy(role["role"], {"fs_read": ["/evidence/**"]})
            for kind in set(VALID_KINDS) - {"fs_read"}:
                assert not role_accepts_policy(role["role"], {kind: ["*"]})


@pytest.mark.parametrize("mutation", [
    "duplicate", "missing", "unknown", "extra_privilege", "runtime_authority",
    "qa_role_drift", "qa_write", "self_acceptance", "delegate", "budget_increase",
    "missing_binding", "missing_stop", "wrong_handoff", "evidence_missing",
])
def test_catalog_rejects_unsafe_or_incomplete_normative_contract(contract, mutation):
    original, validator = contract
    catalog = copy.deepcopy(original)
    roles = catalog["roles"]
    tester = next(r for r in roles if r["role"] == "tester")
    if mutation == "duplicate":
        roles[-1] = copy.deepcopy(roles[0])
    elif mutation == "missing":
        roles.pop()
    elif mutation == "unknown":
        roles[0]["role"] = "unknown_role"
    elif mutation == "extra_privilege":
        tester["allowed_tools"] = ["fs_read"]
    elif mutation == "runtime_authority":
        catalog["runtime_authorization"] = True
    elif mutation == "qa_role_drift":
        tester["independent_qa"] = False
    elif mutation == "qa_write":
        tester["tool_ceiling"] = ["fs_write"]
    elif mutation == "self_acceptance":
        tester["separation_of_duties"]["self_acceptance"] = True
    elif mutation == "delegate":
        tester["separation_of_duties"]["authorize_delegation"] = True
    elif mutation == "budget_increase":
        tester["budget"]["self_increase"] = True
    elif mutation == "missing_binding":
        tester["scope"]["binding"].remove("profile_version")
    elif mutation == "missing_stop":
        tester["stop_conditions"].remove("ambiguous_side_effect")
    elif mutation == "wrong_handoff":
        tester["handoff"]["recipient"] = "developer"
    elif mutation == "evidence_missing":
        tester["handoff"]["evidence"] = []
    else:
        pytest.fail("Unknown mutation")
    with pytest.raises(ValidationError):
        validator.validate(catalog)
