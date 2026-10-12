"""Test-suite runner for the unified CI pipeline (task item (a)).

Discovers and executes the backend test suites of every subsystem module and
returns a structured result. This is the mechanical core of the unified CI
pipeline — "run all existing backend tests" — wired into
:class:`tools.ci.pipeline.CIPipeline`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# The platform modules that ship a backend test suite. The CI pipeline invokes
# each of these in turn (a "unified" SDLC run per ADR-016 / EPIC-INT).
BACKEND_MODULES: tuple[str, ...] = (
    "orchestration-server",
    "agent-management",
    "quality-gates",
    "runtime-hardening",
    "tools",
)


class TestRunnerError(RuntimeError):
    """Raised when the test runner cannot function at all."""


@dataclass
class SuiteResult:
    """Outcome of running one module's pytest suite."""

    module: str
    passed: int = 0
    failed: int = 0
    error: int = 0
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    collected: int = 0
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.error == 0

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "passed": self.passed,
            "failed": self.failed,
            "error": self.error,
            "collected": self.collected,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 3),
            "ok": self.ok,
        }


def discover_test_dir(repo_root: str | os.PathLike, module: str) -> Optional[Path]:
    """Return the module's ``tests/`` directory, or None if absent."""
    candidate = Path(repo_root) / module / "tests"
    return candidate if candidate.is_dir() else None


def run_pytest_suite(
    repo_root: str | os.PathLike,
    module: str,
    *,
    python: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> SuiteResult:
    """Run ``pytest`` for one module's test suite and summarise the result.

    ``python`` defaults to ``sys.executable``. ``extra_args`` lets callers pass
    pytest flags (e.g. ``["-x"]``, ``["-p", "no:warnings"]``).

    ``tools`` is special-cased because its tests import from the repo root (the
    package ``pythonpath`` in ``tools/pyproject.toml`` points at ``..``); we run
    it from the repo root so ``import tools`` resolves.
    """
    import time

    test_dir = discover_test_dir(repo_root, module)
    if test_dir is None:
        return SuiteResult(module=module, exit_code=None, log=[f"no tests/ dir for {module}"])

    interpreter = python or sys.executable
    # NOTE: we intentionally do NOT pass -q here — several modules (e.g.
    # runtime-hardening) already set addopts="-q" in pyproject.toml, so adding
    # another -q would turn it into -qq which suppresses the "N passed" summary
    # line that this parser relies on.
    argv = [interpreter, "-m", "pytest", str(test_dir), "--no-header", "-p", "no:warnings"]
    if extra_args:
        argv.extend(extra_args)
    cwd = str(Path(repo_root))
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=900
        )
    except subprocess.TimeoutExpired as exc:
        return SuiteResult(module=module, error=1, exit_code=None, duration_s=900.0, log=["pytest timed out", str(exc)])
    duration = time.monotonic() - started
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    result = SuiteResult(
        module=module,
        exit_code=proc.returncode,
        duration_s=duration,
        log=out.splitlines()[:50],
    )
    # Parse the pytest summary line, e.g. "123 passed, 2 failed in 9.10s".
    result.collected = _extract_int(out, "test", "tests")
    result.passed = _extract_int(out, "passed")
    result.failed = _extract_int(out, "failed")
    result.error = _extract_int(out, "error")
    return result


def _extract_int(text: str, *labels: str) -> int:
    """Pull the integer count preceding any of ``labels`` (e.g. 'passed')."""
    tokens = text.split()
    for i, tok in enumerate(tokens[:-1]):
        if tok.isdigit() and any(lb in tokens[i + 1] for lb in labels):
            return int(tok)
    return 0


def run_all_backend_suites(
    repo_root: str | os.PathLike,
    *,
    modules: Optional[tuple[str, ...]] = None,
    extra_args: Optional[list[str]] = None,
) -> list[SuiteResult]:
    """Run every backend suite and return results in module order."""
    modules = modules or BACKEND_MODULES
    return [run_pytest_suite(repo_root, m, extra_args=extra_args) for m in modules]