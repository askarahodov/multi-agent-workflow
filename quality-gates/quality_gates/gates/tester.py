"""Tester gate: runs unit/integration tests and lint, reports evidence.

The tester shells out to the configured test runner (default ``pytest``) against
a workspace and captures per-category results. A failing test suite or lint
failure fails the gate.

The exact command set is configurable via ``context["commands"]`` so projects
can customise runners; sensible defaults target ``pytest``.
"""

from __future__ import annotations

import os
import signal
import shlex
import subprocess
import time
from typing import Any

from .base import Finding, Gate, GateResult, GATE_REGISTRY


def _run(cmd: list[str], cwd: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    # Run QA commands in a separate POSIX session. Killing only the direct
    # process on timeout leaves descendants running against trusted mounts.
    if os.name != "posix":
        try:
            return subprocess.run(
                cmd, cwd=cwd, env=_sanitized_env(), stdin=subprocess.DEVNULL,
                shell=False, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, "", "QA test timed out")
        except FileNotFoundError:
            return subprocess.CompletedProcess(cmd, 127, "", "command not found")
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=_sanitized_env(), stdin=subprocess.DEVNULL,
            shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True, close_fds=True,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "command not found")
    try:
        out, err = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        # Signal the whole process group, not only the test runner PID.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()  # Reap the leader; never expose partial output.
        return subprocess.CompletedProcess(cmd, 124, "", "QA test timed out")


def _sanitized_env() -> dict[str, str]:
    return {
        **{name: os.environ[name] for name in (
            "PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT",
            "WINDIR", "TMP", "TEMP",
        ) if name in os.environ},
        "HOME": "/nonexistent" if os.name != "nt" else os.environ.get("TEMP", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
    }



class TesterGate:
    name = "tester"
    description = "Runs unit/integration tests and lint, reporting evidence."

    def execute(self, workspace: str, context: dict[str, Any] | None = None) -> GateResult:
        ctx = context or {}
        commands = ctx.get("commands") or {
            "unit": ["pytest", "-q"],
            "integration": ["pytest", "-q", "-m", "integration"],
            "lint": ["python", "-m", "flake8", "."],
        }
        started = time.perf_counter()
        findings: list[Finding] = []
        all_passed = True
        summaries: list[str] = []

        for category, cmd in commands.items():
            parsed = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
            proc = _run(parsed, workspace)
            passed = proc.returncode == 0
            all_passed = all_passed and passed
            detail = {
                "command": shlex.join(parsed),
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-2000:],
            }
            findings.append(
                Finding(
                    category=category,
                    key=f"{category}:{shlex.join(parsed)}",
                    passed=passed,
                    summary=f"{category}: {'passed' if passed else 'failed'} (exit {proc.returncode})",
                    detail=detail,
                )
            )
            summaries.append(findings[-1].summary)

        duration_ms = (time.perf_counter() - started) * 1000
        return GateResult(
            gate=self.name,
            passed=all_passed,
            summary="; ".join(summaries) or "no checks configured",
            findings=findings,
            duration_ms=duration_ms,
        )


GATE_REGISTRY.register(TesterGate)
