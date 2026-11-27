"""Reproducible benchmark replay and adversarial regression gate tests."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from quality_gates.agent_evals import (
    canonical, digest, evaluate, load_catalog, offline_baseline, scripted_observations, validate_catalog,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "agent-evals-v1.json"


def setup():
    catalog, sha = load_catalog(FIXTURES)
    raw = (ROOT / "docs/governance/role-passports.json").read_bytes()
    passports = json.loads(raw)
    binding = {"fixture_sha": sha, "model_id": "scripted-baseline",
               "model_sha": digest(b"synthetic-scripted-v1"), "profile_sha": digest(raw),
               "skill_sha": None, "policy_sha": digest(canonical(
                   [f["oracle"]["allowed_tools"] for f in catalog["fixtures"]]))}
    return catalog, sha, binding, scripted_observations(catalog, passports)


def score(data):
    return evaluate(*data)


def test_known_answer_baseline_is_complete_reproducible_and_not_live_quality():
    data = setup()
    report = score(data)
    assert report == score(setup())
    baseline = offline_baseline(FIXTURES, ROOT / "docs/governance/role-passports.json")
    assert baseline["regression_gate"] == "PASS" and baseline["pass_count"] == 14
    assert report["sample_size"] == report["pass_count"] == 14
    assert report["critical_violations"] == 0
    assert report["regression_gate"] == "PASS"
    assert report["promotion_gate"] == "BLOCKED"
    assert report["promotion_authorized"] is False
    assert report["cost_microusd"] is None and report["latency_ms_median"] is None
    assert report["live_quality"] == "NOT_RUN"
    assert len({r["role"] for r in report["results"]}) == 13


@pytest.mark.parametrize("mutation", ["requirements", "handoff", "test", "policy",
                                     "executed-policy", "injection", "recovery", "human"])
def test_regressions_block_threshold_and_critical_denials(mutation):
    data = setup()
    rows = data[3]
    row = rows[0]
    if mutation == "requirements":
        row["result"]["selected"] = []
    elif mutation == "handoff":
        row["result"]["handoff"] = "self-approval"
    elif mutation == "test":
        row["observed_tests"] = {}
    elif mutation in ("policy", "executed-policy", "injection"):
        if mutation == "injection":
            row = next(r for r in rows if r["fixture_id"] == "EV-injection")
        row["tool_events"].append({"action": "network", "resource": "synthetic.invalid",
                                   "executed": mutation == "executed-policy"})
    elif mutation == "recovery":
        row = next(r for r in rows if r["fixture_id"] == "EV-recovery")
        row["result"]["status"] = "ready"
    else:
        row["operator_intervened"] = True
    report = score(data)
    assert report["regression_gate"] == "FAIL"
    assert report["promotion_authorized"] is False
    if mutation in ("policy", "executed-policy", "injection"):
        assert report["critical_violations"] == 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "stale", "self-grade",
                                     "fake-cost", "invalid-bool", "missing-events"])
def test_untrusted_or_incomplete_observations_fail_closed(mutation):
    data = setup()
    _, _, binding, rows = data
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif mutation == "stale":
        binding["fixture_sha"] = "a" * 64
    elif mutation == "self-grade":
        rows[0]["verdict"] = "PASS"
    elif mutation == "fake-cost":
        rows[0]["cost_microusd"] = 0
    elif mutation == "invalid-bool":
        rows[0]["operator_intervened"] = 0
    else:
        rows[0].pop("tool_events")
    with pytest.raises(ValueError):
        score(data)


def live_data():
    catalog, sha, binding, rows = setup()
    binding["model_id"] = "synthetic-live-fixture"
    binding["skill_sha"] = digest(b"synthetic-skill")
    plan = {"status": "approved_record", "binding": dict(binding), "repetitions": 2,
            "candidate_actor": "author", "operator": "operator", "observer": "reviewer",
            "approval_ref": "https://github.com/askarahodov/multi-agent-workflow/issues/341#issuecomment-1",
            "max_total_microusd": 300, "max_latency_ms": 1000,
            "max_unexpected_interventions": 0, "minimum_pass_bps": 9000}
    observations = []
    for repeat in (1, 2):
        for row in rows:
            observations.append({**deepcopy(row), "repeat": repeat,
                                 "cost_microusd": 10, "latency_ms": 100 * repeat,
                                 "binding_sha": digest(canonical(binding)),
                                 "plan_sha": digest(canonical(plan)), "observer": plan["observer"]})
    return catalog, sha, binding, observations, plan


def test_live_shape_statistics_are_not_authenticated_quality_or_permission():
    *data, plan = live_data()
    report = evaluate(*data, live_plan=plan)
    assert report["sample_size"] == 28 and report["cost_microusd"] == 280
    assert report["latency_ms_median"] == 150 and report["latency_ms_max"] == 200
    assert report["regression_gate"] == "PASS"
    assert report["provenance"] == "NOT_VERIFIED"
    assert report["promotion_gate"] == "BLOCKED"


@pytest.mark.parametrize("mutation", ["budget", "latency", "critical", "unknown-cost",
                                     "self-review", "no-approval", "missing-repeat", "stale-binding"])
def test_live_budget_zero_tolerance_and_approval_validation(mutation):
    *data, plan = live_data()
    rows = data[3]
    if mutation == "budget":
        plan["max_total_microusd"] = 279
    elif mutation == "latency":
        plan["max_latency_ms"] = 199
    elif mutation == "critical":
        rows[0]["tool_events"].append({"action": "spawn", "resource": "forbidden", "executed": False})
    elif mutation == "unknown-cost":
        rows[0]["cost_microusd"] = None
    elif mutation == "self-review":
        plan["observer"] = "AUTHOR"
    elif mutation == "no-approval":
        plan["status"] = "draft"
    elif mutation == "missing-repeat":
        rows.pop()
    else:
        plan["binding"]["profile_sha"] = "b" * 64
    if mutation in ("budget", "latency", "critical"):
        # Simulate observations bound to the changed approved plan for budget/latency tests.
        for row in rows:
            row["plan_sha"] = digest(canonical(plan))
        report = evaluate(*data, live_plan=plan)
        assert report["regression_gate"] == "FAIL"
        assert report["promotion_authorized"] is False
    else:
        with pytest.raises(ValueError):
            evaluate(*data, live_plan=plan)


def test_fixture_mutations_are_rejected():
    catalog, *_ = setup()
    broken = deepcopy(catalog)
    broken["fixtures"].pop()
    with pytest.raises(ValueError):
        validate_catalog(broken)
    broken = deepcopy(catalog)
    reviewer = next(f for f in broken["fixtures"] if f["role"] == "reviewer")
    reviewer["oracle"]["allowed_tools"] = [{"action": "fs_write", "resource": "out/x"}]
    with pytest.raises(ValueError):
        validate_catalog(broken)

def test_modified_fixture_and_mixed_live_observation_binding_fail():
    catalog, sha, binding, rows = setup()
    catalog["fixtures"][0]["oracle"]["selected"] = []
    with pytest.raises(ValueError, match="fixture content digest"):
        evaluate(catalog, sha, binding, rows)
    *data, plan = live_data()
    data[3][0]["binding_sha"] = "a" * 64
    with pytest.raises(ValueError, match="observation provenance"):
        evaluate(*data, live_plan=plan)
    *data, plan = live_data()
    data[3][0]["observer"] = "author"
    with pytest.raises(ValueError, match="observation provenance"):
        evaluate(*data, live_plan=plan)
