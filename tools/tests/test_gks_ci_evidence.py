"""Fail-closed required-check regression suite for GitHub ↔ Kanban (#192)."""
from __future__ import annotations

import pytest

from tools.github_kanban_sync.ci_evidence import (
    check_run_state,
    classify_ci_state,
    observed_ci_state,
    required_ci_state,
)
from tools.github_kanban_sync.config import Settings


@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        ([], "unknown"),
        (["success"], "success"),
        (["success", "success"], "success"),
        (["success", None], "unknown"),
        (["success", "neutral"], "unknown"),
        (["success", "new_status"], "unknown"),
        (["success", "skipped"], "failure"),
        (["success", "stale"], "failure"),
        (["success", "cancelled"], "failure"),
        (["success", "failure"], "failure"),
        (["success", "queued"], "pending"),
        (["success", "in_progress"], "pending"),
        (["success", "waiting"], "pending"),
    ],
)
def test_only_explicit_complete_success_is_green(observations, expected):
    assert classify_ci_state(observations) == expected


def test_incomplete_check_has_pending_status_not_success():
    assert check_run_state({"status": "in_progress", "conclusion": None}) == "in_progress"
    assert observed_ci_state(
        {"statuses": [{"state": "success"}]},
        {"check_runs": [{"name": "quality gate", "status": "in_progress", "conclusion": None}]},
    ) == "pending"


def _payload(*, quality="success", policy="success", total=1):
    combined = {"statuses": [{"context": "gitflow policy validation", "state": policy}]}
    checks = {"total_count": total, "check_runs": [{
        "name": "quality gate", "status": "completed", "conclusion": quality
    }]}
    return combined, checks


def test_exact_required_status_and_check_run_must_both_be_success():
    combined, runs = _payload()
    assert required_ci_state(
        combined, runs, ["quality gate", "gitflow policy validation"]
    ) == "success"


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        ("failure", "failure"),
        ("skipped", "failure"),
        ("cancelled", "failure"),
        ("neutral", "unknown"),
        ("stale", "failure"),
        (None, "unknown"),
    ],
)
def test_required_check_never_accepts_non_success_conclusion(quality, expected):
    combined, runs = _payload(quality=quality)
    assert required_ci_state(combined, runs, ["quality gate"]) == expected


def test_required_check_in_progress_takes_precedence_over_missing_conclusion():
    combined, runs = _payload(quality=None)
    runs["check_runs"][0]["status"] = "in_progress"
    assert required_ci_state(combined, runs, ["quality gate"]) == "pending"


def test_missing_or_misspelled_required_context_rejected():
    combined, runs = _payload()
    assert required_ci_state(combined, runs, ["quality-gate"]) == "unknown"
    assert required_ci_state(combined, runs, []) == "unknown"


def test_truncated_or_malformed_check_run_page_rejected():
    combined, runs = _payload(total=2)
    assert required_ci_state(combined, runs, ["quality gate"]) == "unknown"
    combined, runs = _payload()
    del runs["total_count"]
    assert required_ci_state(combined, runs, ["quality gate"]) == "unknown"
    assert required_ci_state(combined, {"check_runs": "bad", "total_count": 1}, ["quality gate"]) == "unknown"
    assert required_ci_state({"statuses": None}, runs, ["quality gate"]) == "unknown"


def test_conflicting_duplicate_check_runs_fail_closed():
    combined, runs = _payload()
    runs["check_runs"].append({"name": "quality gate", "status": "completed",
                               "conclusion": "failure"})
    runs["total_count"] = 2
    assert required_ci_state(combined, runs, ["quality gate"]) == "failure"


def test_unrelated_success_cannot_hide_required_failure():
    combined, runs = _payload(quality="failure")
    runs["check_runs"].append({"name": "documentation", "status": "completed",
                               "conclusion": "success"})
    runs["total_count"] = 2
    assert required_ci_state(combined, runs, ["quality gate"]) == "failure"


def test_required_check_configuration_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("GKS_REQUIRED_CHECKS", raising=False)
    assert Settings.from_env().required_checks == ()
    monkeypatch.setenv("GKS_REQUIRED_CHECKS", " quality gate , gitflow policy validation ,, ")
    assert Settings.from_env().required_checks == (
        "quality gate", "gitflow policy validation"
    )


def test_missing_check_run_status_cannot_authorize_closure():
    combined, runs = _payload()
    del runs["check_runs"][0]["status"]
    assert check_run_state(runs["check_runs"][0]) is None
    assert required_ci_state(combined, runs, ["quality gate"]) == "unknown"


@pytest.mark.parametrize("status", [None, "", "success", "failure", "complete", "bogus"])
def test_invalid_lifecycle_status_with_success_conclusion_is_unknown(status):
    combined, runs = _payload()
    runs["check_runs"][0]["status"] = status
    runs["check_runs"][0]["conclusion"] = "success"
    assert required_ci_state(combined, runs, ["quality gate"]) == "unknown"


def test_invalid_lifecycle_status_cannot_override_failed_conclusion():
    combined, runs = _payload(quality="failure")
    runs["check_runs"][0]["status"] = "success"
    assert required_ci_state(combined, runs, ["quality gate"]) == "unknown"
