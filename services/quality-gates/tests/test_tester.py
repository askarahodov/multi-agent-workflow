"""Tests for the Tester gate (unit/integration/lint via real subprocess)."""

from __future__ import annotations

import sys

from quality_gates.gates.tester import TesterGate


def _make_pytest_workspace(tmp_path, *, failing: bool):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n\n"
        "def test_bad():\n    assert False\n"
        if failing
        else "def test_ok():\n    assert True\n"
    )
    return ws


def test_tester_passes_clean_suite(tmp_path):
    ws = _make_pytest_workspace(tmp_path, failing=False)
    result = TesterGate().execute(
        str(ws),
        {"commands": {"unit": [sys.executable, "-m", "pytest", "-q", "--no-header"]}},
    )
    unit = [f for f in result.findings if f.category == "unit"][0]
    assert unit.passed is True
    assert result.passed is True


def test_tester_fails_on_failing_suite(tmp_path):
    ws = _make_pytest_workspace(tmp_path, failing=True)
    result = TesterGate().execute(
        str(ws),
        {"commands": {"unit": [sys.executable, "-m", "pytest", "-q", "--no-header"]}},
    )
    unit = [f for f in result.findings if f.category == "unit"][0]
    assert unit.passed is False
    assert result.passed is False
    # evidence captures the failing returncode
    assert unit.detail["returncode"] != 0


def test_tester_missing_runner_is_failure_not_silent(tmp_path):
    ws = _make_pytest_workspace(tmp_path, failing=False)
    result = TesterGate().execute(
        str(ws),
        {"commands": {"unit": ["definitely-not-a-real-runner-xyz"]}},
    )
    unit = [f for f in result.findings if f.category == "unit"][0]
    assert unit.passed is False
    assert result.passed is False


def test_tester_reports_all_categories(tmp_path):
    ws = _make_pytest_workspace(tmp_path, failing=False)
    result = TesterGate().execute(
        str(ws),
        {
            "commands": {
                "unit": [sys.executable, "-m", "pytest", "-q", "--no-header"],
                "integration": [sys.executable, "-m", "pytest", "-q", "--no-header", "-m", "integration"],
                "lint": [sys.executable, "-m", "pytest", "-q", "--no-header", "--collect-only"],
            }
        },
    )
    cats = {f.category for f in result.findings}
    assert {"unit", "integration", "lint"} <= cats
