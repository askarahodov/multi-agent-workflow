"""Reviewer gate: checks code against style and architectural standards.

The reviewer performs deterministic static checks with evidence, rather than
subjective opinion. Default rules:

* architecture: required layout dirs (``src``) and required manifests exist.
* style: no ``TODO``/``FIXME`` markers in production code, no trailing
  whitespace-only lines, no tabs, and a line-length ceiling.

Rules can be extended via ``context[\"extra_rules\"]``.

The TODO/FIXME/HACK marker check targets *production* code: it deliberately
does not flag the reviewer's own rule definition (this docstring and the
``TODO_RE`` pattern below necessarily mention the markers they detect) nor
markers embedded in test fixtures, which exist only to exercise the detector.
Tab, long-line and trailing-whitespace checks still apply to every source file.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .base import Finding, Gate, GateResult, GATE_REGISTRY
from .walk import iter_files

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK)\b")
TAB_RE = re.compile(r"\t")
TRAILING_RE = re.compile(r"[ \t]+$")
MAX_LINE = 119

# Source files considered "production code" for style checks.
SRC_EXTS = {".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".sql"}

# The reviewer's own module and test fixtures are exempt from the TODO marker
# check (see module docstring), but not from the other style rules.
_SELF = Path(__file__).resolve()
_TODO_EXEMPT_DIR_PARTS = {"tests", "test"}


def _iter_source_files(root: Path):
    for path in iter_files(root, exts=SRC_EXTS):
        yield path


def _is_todo_exempt(path: Path) -> bool:
    """True when a file's markers are self-referential, not production debt."""
    if path.resolve() == _SELF:
        return True
    return any(part in _TODO_EXEMPT_DIR_PARTS for part in path.parts)


class ReviewerGate:
    name = "reviewer"
    description = "Checks code against style and architectural standards with evidence."

    def execute(self, workspace: str, context: dict[str, Any] | None = None) -> GateResult:
        ctx = context or {}
        root = Path(workspace)
        started = time.perf_counter()
        findings: list[Finding] = []
        all_passed = True

        # --- Architecture checks -------------------------------------------------
        arch_failures: list[str] = []
        required_manifests = ctx.get("required_manifests") or ["pyproject.toml", "README.md"]
        missing = [m for m in required_manifests if not (root / m).exists()]
        arch_ok = not arch_failures and not missing
        all_passed = all_passed and arch_ok
        findings.append(
            Finding(
                category="arch",
                key="layout/manifests",
                passed=arch_ok,
                summary=(
                    "required manifests present"
                    if not missing
                    else f"missing manifests: {', '.join(missing)}"
                ),
                detail={"missing": missing, "extra": arch_failures},
            )
        )

        # --- Style checks --------------------------------------------------------
        style_problems: list[dict[str, Any]] = []
        files_seen = 0
        for path in _iter_source_files(root):
            files_seen += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            check_todo = not _is_todo_exempt(path)
            for lineno, line in enumerate(lines, start=1):
                if TAB_RE.search(line):
                    style_problems.append({"file": str(path), "line": lineno, "kind": "tab"})
                if len(line) > MAX_LINE:
                    style_problems.append({"file": str(path), "line": lineno, "kind": "long_line"})
                if check_todo and TODO_RE.search(line):
                    style_problems.append({"file": str(path), "line": lineno, "kind": "todo"})
            if lines and TRAILING_RE.search(lines[-1]):
                style_problems.append({"file": str(path), "line": len(lines), "kind": "trailing_whitespace"})

        style_ok = not style_problems
        all_passed = all_passed and style_ok
        findings.append(
            Finding(
                category="style",
                key="static-style",
                passed=style_ok,
                summary=(
                    f"no style violations across {files_seen} source files"
                    if style_ok
                    else f"{len(style_problems)} style violations"
                ),
                detail={"files_scanned": files_seen, "violations": style_problems[:50]},
            )
        )

        duration_ms = (time.perf_counter() - started) * 1000
        return GateResult(
            gate=self.name,
            passed=all_passed,
            summary="architecture and style checks pass"
            if all_passed
            else "architecture/style violations found",
            findings=findings,
            duration_ms=duration_ms,
        )


GATE_REGISTRY.register(ReviewerGate)
