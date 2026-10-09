"""Tester gate: runs unit/integration tests and lint, reports evidence.

The tester shells out to the configured test runner (default ``pytest``) against
a workspace and captures per-category results. A failing test suite or lint
failure fails the gate.

The exact command set is configurable via ``context["commands"]`` so projects
can customise runners; sensible defaults target ``pytest``.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from typing import Any

from .base import Finding, Gate, GateResult, GATE_REGISTRY


def _run(cmd: list[str], cwd: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        # Runner binary does not exist; report as a failed check, not an infra crash.
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr="command not found")


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
