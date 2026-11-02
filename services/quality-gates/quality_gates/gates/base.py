"""Gate abstraction and shared result types.

A *gate* is a deterministic evaluation of a workspace against a set of rules. It
produces ``Findings`` (evidence) and an overall pass/fail verdict. Concrete gates
(Tester, Reviewer, Security, ReleasePrepHook) implement :class:`Gate` and are
registered in :data:`GATE_REGISTRY`.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Shared workspace traversal
#
# Single source of truth for which subtrees a gate should never read. Every
# gate that walks a workspace (Reviewer, Security, ReleasePrep) uses
# :func:`iter_files`, so the skip policy cannot drift between them. Names are
# matched at any depth; VCS-ignored paths from a workspace-root ``.gitignore``
# are honoured best-effort in addition.
# ---------------------------------------------------------------------------

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        "dist",
        "build",
        "vendor",
        "site-packages",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".coverage",
        ".verify",
        ".qg-verify",
        ".idea",
        ".vscode",
    }
)


def _load_gitignore_patterns(root: Path) -> list[str]:
    """Read ``<root>/.gitignore`` into a simple pattern list (negation unsupported)."""
    gi = root / ".gitignore"
    if not gi.is_file():
        return []
    patterns: list[str] = []
    for raw in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line.rstrip("/"))
    return patterns


def _matches_gitignore(rel_posix: str, patterns: list[str]) -> bool:
    parts = rel_posix.split("/")
    for pat in patterns:
        if "/" not in pat:
            # bare pattern matches any path segment of that name
            if any(fnmatch.fnmatch(p, pat) for p in parts):
                return True
        elif len(pat.split("/")) == 1:
            continue
        else:
            if rel_posix == pat or rel_posix.startswith(pat + "/"):
                return True
            if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(rel_posix, pat + "/*"):
                return True
    return False


def iter_files(root: Path):
    """Yield regular files under ``root``, pruning ignored subtrees during walk.

    Unlike ``rglob("*")`` followed by a ``path.parts`` filter, this prunes
    skip-listed and VCS-ignored directories *in place* via ``os.walk``'s
    ``dirnames`` mutation, so a large ``venv``/``.verify``/``site-packages``
    subtree is never read at all -- both a correctness fix (a venv in the tree
    can no longer poison a gate's findings) and a performance fix.
    """
    root = Path(root)
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    patterns = _load_gitignore_patterns(root)

    def _excluded(path: Path) -> bool:
        rel = str(path.relative_to(root)).replace(os.sep, "/")
        return any(p in SKIP_DIR_NAMES for p in rel.split("/")) or _matches_gitignore(rel, patterns)

    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not _excluded(dp / d)]
        for name in sorted(filenames):
            fp = dp / name
            if not _excluded(fp):
                yield fp


@dataclass
class Finding:
    """A single piece of evidence produced by a gate."""

    category: str  # unit / integration / lint / style / arch / dep / secret / release
    key: str
    passed: bool
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_evidence(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "key": self.key,
            "passed": self.passed,
            "summary": self.summary,
            "detail": self.detail,
        }


@dataclass
class GateResult:
    """Outcome of running one gate."""

    gate: str
    passed: bool
    summary: str
    findings: list[Finding] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def categories(self) -> list[str]:
        return sorted({f.category for f in self.findings})


class Gate(Protocol):
    """Protocol every gate executor implements."""

    name: str
    description: str

    def execute(self, workspace: str, context: dict[str, Any] | None = None) -> GateResult:
        """Run the gate against ``workspace`` and return a verdict + findings."""
        ...


class Registry:
    """Name -> Gate class mapping plus pipeline ordering."""

    def __init__(self) -> None:
        self._gates: dict[str, type[Gate]] = {}

    def register(self, gate: type[Gate]) -> type[Gate]:
        self._gates[gate.name] = gate
        return gate

    def get(self, name: str) -> type[Gate]:
        if name not in self._gates:
            raise KeyError(f"unknown gate: {name}")
        return self._gates[name]

    def names(self) -> list[str]:
        return list(self._gates.keys())


GATE_REGISTRY: Registry = Registry()
