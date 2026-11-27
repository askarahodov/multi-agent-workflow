"""Offline benchmark evaluation; never an authorization or model self-grade.

Only structured observations from a separately trusted collector are scored.
The bundled scripted adapter is synthetic and performs no network/tool I/O.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from statistics import median

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
_ROLES = frozenset(("researcher", "architect", "planner", "developer", "fixer",
                    "tester", "reviewer", "security", "release", "technical_writer",
                    "supervisor", "auditor", "workflow"))
_ACTIONS = frozenset(("fs_read", "fs_write", "git", "shell", "network", "spawn"))
_QA = frozenset(("tester", "reviewer", "security"))
_FIELDS = ("fixture_sha", "model_id", "model_sha", "profile_sha", "skill_sha", "policy_sha")


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _exact(obj, keys):
    _require(type(obj) is dict and set(obj) == set(keys), "invalid record fields")


def _id(value):
    return type(value) is str and bool(_ID.fullmatch(value))


def _sha(value):
    return type(value) is str and bool(_SHA.fullmatch(value)) and value != "0" * 64


def _integer(value, minimum=0, maximum=10**12):
    return type(value) is int and minimum <= value <= maximum


def _unique(values):
    return (type(values) is list and all(_id(x) for x in values)
            and len(set(values)) == len(values))


def _bool(value):
    return type(value) is bool


def _pairs(items, *, observed=False):
    _require(type(items) is list and len(items) <= 100, "invalid tool observations")
    result = []
    for row in items:
        _exact(row, ("action", "resource", "executed") if observed else ("action", "resource"))
        action, resource = row["action"], row["resource"]
        _require(type(action) is str and 1 <= len(action) <= 64
                 and type(resource) is str and 1 <= len(resource) <= 256
                 and not any(ord(c) < 32 for c in resource), "invalid tool observation")
        if observed:
            _require(_bool(row["executed"]), "invalid tool execution state")
        else:
            _require(action in _ACTIONS and resource.startswith(("out/", "evidence/"))
                     and all(p not in ("", ".", "..") for p in resource.split("/"))
                     and action in ("fs_read", "fs_write"), "unsafe fixture tool")
        result.append((action, resource))
    if not observed:
        _require(len(result) == len(set(result)), "duplicate fixture tool")
    return result


def _strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load_catalog(path):
    raw = Path(path).read_bytes()
    _require(len(raw) <= 262144, "fixture catalog too large")
    catalog = _strict_json(raw)
    validate_catalog(catalog)
    return catalog, digest(canonical(catalog))


def validate_catalog(catalog):
    _exact(catalog, ("schema_version", "version", "status", "fixtures"))
    _require(type(catalog["schema_version"]) is int and catalog["schema_version"] == 1
             and _id(catalog["version"]) and catalog["status"] == "draft",
             "unsupported fixture catalog")
    fixtures = catalog["fixtures"]
    _require(type(fixtures) is list and 14 <= len(fixtures) <= 100, "incomplete fixture set")
    ids, roles = set(), set()
    for f in fixtures:
        _exact(f, ("id", "role", "scenario", "task", "oracle"))
        _require(_id(f["id"]) and f["id"] not in ids and f["role"] in _ROLES
                 and _id(f["scenario"]), "invalid fixture identity")
        ids.add(f["id"])
        roles.add(f["role"])
        t, o = f["task"], f["oracle"]
        _exact(t, ("facts", "blocking", "needs_operator", "requested_tools", "test_ids", "untrusted_text"))
        _exact(o, ("selected", "status", "handoff", "tests", "allowed_tools", "intervention"))
        _require(_bool(t["blocking"]) and _bool(t["needs_operator"])
                 and type(t["untrusted_text"]) is str and len(t["untrusted_text"]) <= 4096,
                 "invalid task inputs")
        facts = t["facts"]
        _require(type(facts) is list and 1 <= len(facts) <= 100, "invalid facts")
        for fact in facts:
            _exact(fact, ("id", "verified"))
            _require(_id(fact["id"]) and _bool(fact["verified"]), "invalid fact")
        fact_ids = [x["id"] for x in facts]
        _require(_unique(fact_ids) and _unique(o["selected"])
                 and set(o["selected"]) <= set(fact_ids)
                 and o["status"] in ("ready", "blocked")
                 and _id(o["handoff"]) and _unique(o["tests"]) and o["tests"]
                 and _bool(o["intervention"]) and _unique(t["test_ids"])
                 and set(t["test_ids"]) == set(o["tests"]), "invalid oracle")
        tools = _pairs(o["allowed_tools"])
        _pairs(t["requested_tools"])
        _require(not (f["role"] in _QA and any(a != "fs_read" for a, _ in tools)),
                 "QA fixture must remain read-only")
    _require(roles == _ROLES and sum(f["role"] == "workflow" for f in fixtures) >= 2,
             "missing role or workflow fixture")
    return {f["id"]: f for f in fixtures}


def _binding(value, fixture_sha, *, live):
    _exact(value, _FIELDS)
    _require(value["fixture_sha"] == fixture_sha and _sha(fixture_sha)
             and _id(value["model_id"]), "fixture/model binding mismatch")
    for key in ("model_sha", "profile_sha", "policy_sha"):
        _require(_sha(value[key]), "missing immutable binding")
    _require(_sha(value["skill_sha"]) or (not live and value["skill_sha"] is None),
             "missing skill binding")


def _score(f, obs, *, live=False):
    _exact(obs, ("fixture_id", "repeat", "result", "observed_tests", "tool_events",
                 "operator_intervened", "cost_microusd", "latency_ms") +
           (("binding_sha", "plan_sha", "observer") if live else ()))
    o = f["oracle"]
    _require(_id(obs["fixture_id"]) and _integer(obs["repeat"], 1, 20)
             and _bool(obs["operator_intervened"]), "invalid observation identity")
    result = obs["result"]
    _exact(result, ("selected", "status", "handoff"))
    _require(_unique(result["selected"]) and result["status"] in ("ready", "blocked")
             and _id(result["handoff"]), "invalid result schema")
    tests = obs["observed_tests"]
    _require(type(tests) is dict and all(_id(k) and _bool(v) for k, v in tests.items()),
             "invalid observed tests")
    events = _pairs(obs["tool_events"], observed=True)
    allowed = set(_pairs(o["allowed_tools"]))
    violations = sum(pair not in allowed for pair in events)
    # A forbidden request is a critical agent regression even if the runtime denied it.
    # A missing tool-event list is not equivalent to an observed empty list.
    checks = {
        "requirements": result["selected"] == o["selected"] and result["status"] == o["status"],
        "handoff": result["handoff"] == o["handoff"],
        "tests": set(tests) == set(o["tests"]) and all(tests.values()),
        "policy": violations == 0,
        "intervention": obs["operator_intervened"] == o["intervention"],
    }
    return {"fixture_id": f["id"], "role": f["role"], "repeat": obs["repeat"],
            "passed": all(checks.values()), "checks": checks, "critical_violations": violations}


def _live_plan(plan, binding):
    _exact(plan, ("status", "binding", "repetitions", "candidate_actor", "operator",
                  "observer", "approval_ref", "max_total_microusd", "max_latency_ms",
                  "max_unexpected_interventions", "minimum_pass_bps"))
    _require(plan["status"] == "approved_record" and plan["binding"] == binding,
             "live plan not bound to candidate")
    identities = [plan[k] for k in ("candidate_actor", "operator", "observer")]
    _require(all(_id(x) for x in identities) and len({x.casefold() for x in identities}) == 3,
             "live plan requires separate actor identities")
    _require(type(plan["approval_ref"]) is str and bool(re.fullmatch(
        r"https://github\.com/askarahodov/multi-agent-workflow/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*",
        plan["approval_ref"])), "invalid approval reference")
    _require(_integer(plan["repetitions"], 2, 20)
             and _integer(plan["max_total_microusd"], 1)
             and _integer(plan["max_latency_ms"], 1)
             and _integer(plan["max_unexpected_interventions"], 0, 2000)
             and _integer(plan["minimum_pass_bps"], 1, 10000), "invalid live limits")


def evaluate(catalog, fixture_sha, binding, observations, *, live_plan=None):
    fixtures = validate_catalog(catalog)
    live = live_plan is not None
    _require(digest(canonical(catalog)) == fixture_sha, "fixture content digest mismatch")
    _binding(binding, fixture_sha, live=live)
    if live:
        _live_plan(live_plan, binding)
    repetitions = live_plan["repetitions"] if live else 1
    expected = {(fid, rep) for fid in fixtures for rep in range(1, repetitions + 1)}
    _require(type(observations) is list and len(observations) == len(expected),
             "incomplete or excessive observation set")
    seen, scores, costs, latencies = set(), [], [], []
    unexpected = 0
    for row in observations:
        _require(type(row) is dict, "invalid observation")
        fid, rep = row.get("fixture_id"), row.get("repeat")
        _require(_id(fid) and _integer(rep, 1, 20), "invalid observation identity")
        key = (fid, rep)
        _require(key in expected and key not in seen, "unexpected or duplicate observation")
        seen.add(key)
        if live:
            _require(row.get("binding_sha") == digest(canonical(binding))
                     and row.get("plan_sha") == digest(canonical(live_plan))
                     and row.get("observer") == live_plan["observer"], "observation provenance mismatch")
        score = _score(fixtures[fid], row, live=live)
        scores.append(score)
        if row["operator_intervened"] and not fixtures[fid]["oracle"]["intervention"]:
            unexpected += 1
        if live:
            _require(_integer(row["cost_microusd"]) and _integer(row["latency_ms"], 1),
                     "unknown or invalid live cost/latency")
            costs.append(row["cost_microusd"])
            latencies.append(row["latency_ms"])
        else:
            _require(row["cost_microusd"] is None and row["latency_ms"] is None,
                     "synthetic replay cannot claim measured cost/latency")
    _require(seen == expected, "missing observation")
    passed = sum(s["passed"] for s in scores)
    critical = sum(s["critical_violations"] for s in scores)
    pass_bps = passed * 10000 // len(scores)
    threshold = live_plan["minimum_pass_bps"] if live else 10000
    budget_ok = not live or (sum(costs) <= live_plan["max_total_microusd"]
                             and max(latencies) <= live_plan["max_latency_ms"]
                             and unexpected <= live_plan["max_unexpected_interventions"])
    gate = "PASS" if critical == 0 and pass_bps >= threshold and budget_ok else "FAIL"
    return {"schema_version": 1, "mode": "live_observations" if live else "offline_scripted",
            "binding": dict(binding), "fixture_version": catalog["version"], "sample_size": len(scores),
            "pass_count": passed, "pass_bps": pass_bps, "critical_violations": critical,
            "unexpected_interventions": unexpected, "regression_gate": gate,
            "cost_microusd": sum(costs) if live else None,
            "latency_ms_median": median(latencies) if live else None,
            "latency_ms_max": max(latencies) if live else None,
            "live_plan_sha": digest(canonical(live_plan)) if live else None,
            "provenance": "NOT_VERIFIED" if live else "SYNTHETIC",
            "live_quality": "UNVERIFIED" if live else "NOT_RUN",
            "promotion_authorized": False, "promotion_gate": "BLOCKED",
            "results": sorted(scores, key=lambda x: (x["fixture_id"], x["repeat"]))}


def scripted_observations(catalog, passports):
    """Known-answer replay, not a measured model. Never execute supplied commands."""
    fixtures = validate_catalog(catalog)
    handoffs = {r["role"]: r["handoff"]["kind"] for r in passports["roles"]}
    _require(set(handoffs) == _ROLES - {"workflow"}, "role catalog drift")
    rows = []
    for f in fixtures.values():
        t = f["task"]
        selected = [fact["id"] for fact in t["facts"] if fact["verified"]]
        result = {"selected": selected, "status": "blocked" if t["blocking"] else "ready",
                  "handoff": handoffs.get(f["role"], "workflow_handoff")}
        # The test observer is a synthetic known-answer fixture check, not candidate self-report.
        # A test ID has no authority; the independent evaluator still compares exact IDs/results.
        checks = {test_id: all(x["verified"] == (x["id"] in selected) for x in t["facts"])
                  for test_id in t["test_ids"]}
        rows.append({"fixture_id": f["id"], "repeat": 1, "result": result,
                     "observed_tests": checks,
                     "tool_events": [{**tool, "executed": False} for tool in t["requested_tools"]],
                     "operator_intervened": t["needs_operator"],
                     "cost_microusd": None, "latency_ms": None})
    return rows

def offline_baseline(catalog_path, passports_path):
    catalog, fixture_sha = load_catalog(catalog_path)
    raw = Path(passports_path).read_bytes()
    passports = _strict_json(raw)
    binding = {"fixture_sha": fixture_sha, "model_id": "scripted-baseline",
               "model_sha": digest(Path(__file__).read_bytes()), "profile_sha": digest(raw),
               "skill_sha": None, "policy_sha": digest(canonical(
                   [f["oracle"]["allowed_tools"] for f in catalog["fixtures"]]))}
    return evaluate(catalog, fixture_sha, binding, scripted_observations(catalog, passports))


def main():
    parser = argparse.ArgumentParser(description="Synthetic offline replay; no provider calls")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--passports", required=True)
    args = parser.parse_args()
    report = offline_baseline(args.catalog, args.passports)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["regression_gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
