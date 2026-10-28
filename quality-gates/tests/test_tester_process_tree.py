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
