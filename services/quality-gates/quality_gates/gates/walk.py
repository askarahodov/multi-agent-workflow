"""Shared workspace traversal for gates.

Single source of truth for which directory subtrees a gate scan must never
descend into, and for how files are enumerated. Every gate that walks a
workspace (Reviewer, Security, Release-Prep) uses :func:`iter_files` here.

Two properties matter:

* **Pruning, not filtering.** :func:`iter_files` uses :func:`os.walk` and
  mutates ``dirnames`` *in place* (``dirnames[:] = ...``) so that skipped
  subtrees are never descended into. A virtualenv anywhere in the scanned tree
  therefore cannot be read at all -- it cannot slow the scan nor poison its
  results (previously ``rglob`` + a ``parts`` filter read every file first).
* **One skip-set.** All gates share :data:`SKIP_DIRS` (plus any ``*.egg-info``
  directory), so the policy cannot diverge per gate the way it previously did
  (``vendor`` existed only in Security, ``venv``/``.verify`` nowhere).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

# Directories pruned during traversal. Includes VCS metadata, virtualenvs
# (both spellings), the pipeline's own verification scratch dirs, build/cache
# output and vendored third-party code. Any ``*.egg-info`` directory is also
# pruned (kept as a suffix rule so a package-named dir like
# ``quality_gates.egg-info`` is matched regardless of the package name).
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        ".verify",
        ".qg-verify",
        "__pycache__",
        ".tox",
        "dist",
        "build",
        "vendor",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)


def _is_skipped_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.endswith(".egg-info")


def iter_files(root: Path, exts: set[str] | None = None) -> Iterator[Path]:
    """Yield files under ``root``, pruning skipped and VCS-ignored subtrees.

    Uses :func:`os.walk` with in-place ``dirnames[:]`` mutation so skipped
    directories are never descended into. When ``exts`` is given, only files
    whose suffix is in the set are yielded (other files are skipped, but their
    directories are still walked).
    """
    exts = set(exts) if exts else None
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune in place: skipped directories are never entered.
        dirnames[:] = sorted(d for d in dirnames if not _is_skipped_dir(d))
        for name in filenames:
            path = Path(dirpath) / name
            if exts is not None and path.suffix not in exts:
                continue
            yield path
