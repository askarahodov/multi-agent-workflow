"""Operator cutover guard prevents unsafe in-process test execution."""
from __future__ import annotations

import pytest

from quality_gates.gates import tester


@pytest.mark.parametrize("commands", [
    {"unit": ["python", "--version"]},
    {"unit": "sh -c 'echo bypass'"},
    {"lint": ["true"]},
])
def test_operator_denial_precedes_any_subprocess(monkeypatch, tmp_path, commands):
    monkeypatch.setenv("MAW_QG_DENY_INPROCESS_TESTER", "1")
    monkeypatch.setattr(tester, "_run", lambda *a, **k: pytest.fail("command executed"))
    result = tester.TesterGate().execute(
        str(tmp_path), {"commands": commands, "MAW_QG_DENY_INPROCESS_TESTER": "0"}
    )
    assert not result.passed
    assert result.findings and not result.findings[0].passed
    assert result.findings[0].category == "isolation"
    assert "disabled" in result.summary
