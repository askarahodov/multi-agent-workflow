"""POSIX timeout must stop descendants, not just the test runner."""
from __future__ import annotations

import os
import sys

import pytest
from quality_gates.gates.tester import _run


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_timeout_kills_child_process_group(tmp_path):
    # Child keeps its inherited stdout pipe open even when parent exits.
    # A one-process-only kill would leave communicate() stuck until the child exits.
    child = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "time.sleep(60)"
    )
    result = _run([sys.executable, "-c", child], str(tmp_path), timeout=1)
    assert result.returncode == 124
    assert result.stdout == ""
    assert result.stderr == "QA test timed out"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_successful_process_still_returns_output(tmp_path):
    result = _run([sys.executable, "-c", "print('ok')"], str(tmp_path), timeout=5)
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_timeout_drops_partial_sensitive_output(tmp_path):
    # Output emitted before a timeout must not reach findings or logs.
    code = "import sys,time; print('TOP_SECRET',flush=True); time.sleep(60)"
    result = _run([sys.executable, "-c", code], str(tmp_path), timeout=1)
    assert result.returncode == 124
    assert result.stdout == ""
    assert "TOP_SECRET" not in result.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_timed_out_tester_gate_is_failed(tmp_path, monkeypatch):
    from quality_gates.gates import tester
    real_run = tester._run
    monkeypatch.setattr(tester, "_run", lambda cmd, cwd: real_run(cmd, cwd, timeout=1))
    result = tester.TesterGate().execute(
        str(tmp_path),
        {"commands": {"unit": [sys.executable, "-c", "import time; time.sleep(60)"]}},
    )
    assert result.passed is False
    assert result.findings[0].detail["returncode"] == 124
