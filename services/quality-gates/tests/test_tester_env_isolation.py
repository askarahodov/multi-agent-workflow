"""QA subprocesses may execute agent-created code but cannot inherit admin keys."""
from __future__ import annotations

import sys

from quality_gates.gates.tester import TesterGate


def test_qa_test_subprocess_environment_does_not_include_service_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("QG_QA_ATTESTATION_KEY", "hmac-private-test-value")
    monkeypatch.setenv("ADMIN_API_KEYS", "operator-private-test-value")
    monkeypatch.setenv("MAW_QA_ORCH_ADMIN_KEY_FILE", "/trusted/key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "provider-private-test-value")
    program = (
        "import os; assert all(key not in os.environ for key in "
        "('QG_QA_ATTESTATION_KEY','ADMIN_API_KEYS',"
        "'MAW_QA_ORCH_ADMIN_KEY_FILE','OPENROUTER_API_KEY'))"
    )
    result = TesterGate().execute(
        str(tmp_path),
        {"commands": {"unit": [sys.executable, "-B", "-c", program]}},
    )
    assert result.passed, result.summary
    assert len(result.findings) == 1
