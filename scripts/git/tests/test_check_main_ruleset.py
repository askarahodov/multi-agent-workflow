"""Offline safety regression tests for the GitHub main ruleset auditor (#44)."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "git" / "check_main_ruleset.py"
SPEC = importlib.util.spec_from_file_location("main_ruleset_audit", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

EXPECTED = mod.expected_contexts(ROOT / "tests/gitflow/required-checks.txt")


def safe_ruleset():
    return {
        "id": 26129824,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"}, {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews_on_push": True,
                "required_review_thread_resolution": True,
                "require_last_push_approval": True,
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": name} for name in sorted(EXPECTED)],
            }},
        ],
    }


def test_healthy_exact_main_ruleset_satisfies_policy():
    result = mod.audit_ruleset(safe_ruleset(), EXPECTED)
    assert result["ok"] is True
    assert not result["failures"]
    assert result["required_approvals"] == 1
    assert not result["warnings"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda d: d.update(enforcement="disabled"), "active"),
    (lambda d: d.update(target="tag"), "branches"),
    (lambda d: d["conditions"]["ref_name"].update(include=["refs/heads/develop"]), "main"),
    (lambda d: d["conditions"]["ref_name"].update(exclude=["refs/heads/main"]), "excluded"),
    (lambda d: d["conditions"]["ref_name"].update(exclude=["refs/heads/*"]), "excluded"),
    (lambda d: d["conditions"]["ref_name"].update(exclude=["refs/heads/m*"]), "excluded"),
    (lambda d: d["conditions"]["ref_name"].update(exclude=["refs/heads/**/main"]), "excluded"),
    (lambda d: d["conditions"]["ref_name"].update(exclude=["refs/heads/special/**"]), "excluded"),
    (lambda d: d["conditions"]["ref_name"].update(exclude=[{"invalid": True}]), "malformed"),
    (lambda d: d.update(bypass_actors=[{"actor_type": "Team", "actor_id": 42}]), "bypass"),
    (lambda d: d["rules"].pop(0), "deletion"),
    (lambda d: d["rules"].pop(1), "non_fast_forward"),
    (lambda d: d["rules"][2]["parameters"].update(required_approving_review_count=0), "approval"),
    (lambda d: d["rules"][2]["parameters"].update(required_approving_review_count=True), "approval"),
    (lambda d: d["rules"][2]["parameters"].update(dismiss_stale_reviews_on_push=False), "stale"),
    (lambda d: d["rules"][2]["parameters"].update(required_review_thread_resolution=False), "threads"),
    (lambda d: d["rules"][3]["parameters"]["required_status_checks"].pop(0), "absent"),
    (lambda d: d["rules"][3]["parameters"].update(required_status_checks=[]), "absent"),
    (lambda d: d["rules"][3]["parameters"]["required_status_checks"].append({"context": "not-produced-ghost-check"}), "unexpected"),
])
def test_unsafe_ruleset_must_fail(mutation, reason):
    data = safe_ruleset()
    mutation(data)
    report = mod.audit_ruleset(data, EXPECTED)
    assert report["ok"] is False, (reason, report)
    assert any(reason in item for item in report["failures"]), report


def test_multiple_rule_types_are_not_accepted_as_unambiguous():
    data = safe_ruleset()
    data["rules"].append(copy.deepcopy(data["rules"][2]))
    assert mod.audit_ruleset(data, EXPECTED)["ok"] is False


def test_malformed_response_and_checks_fail_closed():
    assert mod.audit_ruleset(None, EXPECTED)["ok"] is False
    data = safe_ruleset()
    data["rules"][3]["parameters"]["required_status_checks"] = [None]
    assert mod.audit_ruleset(data, EXPECTED)["ok"] is False


def test_snapshot_mode_is_never_claimed_as_live(tmp_path, capsys):
    source = tmp_path / "ruleset.json"
    source.write_text(json.dumps(safe_ruleset()), encoding="utf-8")
    rc = mod.main(["--snapshot", str(source),
                   "--required-checks-file", str(ROOT / "tests/gitflow/required-checks.txt")])
    output = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert output["mode"] == "offline_snapshot_NOT_live_evidence"


def test_repository_supplied_2026_10_29_ruleset_is_correctly_flagged():
    baseline = ROOT / "evidence/ruleset-main-protection-payload.json"
    data = json.loads(baseline.read_text(encoding="utf-8"))
    report = mod.audit_ruleset(data, EXPECTED)
    assert not report["ok"]
    assert any("independent PR approval" in text for text in report["failures"])
    assert report["missing_checks"] == []
    assert report["unexpected_checks"] == []


def test_read_errors_do_not_leak_gh_token(monkeypatch, capsys):
    class Result:
        returncode = 1
        stdout = "token=SECRET"
        stderr = "unauthorized token=SECRET"

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(RuntimeError, match="ruleset read failed") as exc:
        mod.load_live(mod.REPO, 26129824)
    assert "SECRET" not in str(exc.value)


def test_required_contexts_inventory_must_be_complete_and_unique(tmp_path):
    file = tmp_path / "required.txt"
    file.write_text("quality gate\nquality gate\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicates"):
        mod.expected_contexts(file)
