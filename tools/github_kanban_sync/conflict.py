"""Conflict detection & ownership reservation (Issue #192 §4).

Reports, never resolves. Three classes of hazard, all surfaced to the
orchestrator **before** a task is handed out and **before** a merge:

* ``path_overlap``   — a path changed on ``main`` is also touched on an active
  branch (``critical`` = the exact same path, ``warn`` = the same sensitive
  directory, e.g. a #182 relocation touching a reserved tree).
* ``reservation``    — a path inside a scope exclusively reserved by another
  Issue/task (e.g. the #182 migration reservation).
* ``stale_main``     — the snapshot the caller is about to act on is older than
  the live ``origin/main``.

The module is pure: it takes already-gathered facts (``main_changed`` paths,
claims, reservations, SHAs) and returns a JSON-able report. The read-only git
gathering lives in :func:`gather_claims`, which uses ``git`` observation only —
no rebase/reset/merge/checkout/delete, ever.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

# Sensitive trees (SPEC §1.4 / REPOSITORY-STRUCTURE.md §1). A change inside one of
# these fires a ``warn`` against any active branch touching the same tree.
SENSITIVE_DIRS = (
    "frontend/",
    ".github/workflows/",
    "orchestration-server/",
    "agent-management/",
    "quality-gates/",
    "runtime-hardening/",
    "shared/",
)
SENSITIVE_FILES = (
    "docker-compose.yml",
    "AGENT_GITFLOW_RULES.md",
    "gitflow-policy.schema.json",
    "Makefile",
    "README.md",
)


def norm(path: str) -> str:
    return path.strip().lstrip("./").replace("\\", "/")


def _in_dir(path: str, directory: str) -> bool:
    directory = norm(directory).rstrip("/")
    return path == directory or path.startswith(directory + "/")


def is_sensitive(path: str) -> bool:
    norm_path = norm(path)
    if norm_path in SENSITIVE_FILES:
        return True
    if norm_path.startswith("compose.") and norm_path.endswith(".yml"):
        return True
    return any(_in_dir(norm_path, d) for d in SENSITIVE_DIRS)


def _severity(path: str, main_changed: set[str]) -> str:
    return "critical" if norm(path) in main_changed else "warn"


def _reservation_owner(path: str, reservations: Sequence[dict[str, Any]]) -> Optional[dict[str, Any]]:
    norm_path = norm(path)
    best: Optional[dict[str, Any]] = None
    for res in reservations:
        scope = norm(res.get("scope", ""))
        if not scope:
            continue
        if _in_dir(norm_path, scope) or (scope.endswith("/") and norm_path.startswith(scope)):
            if best is None or len(scope) > len(norm(best.get("scope", ""))):
                best = res
    return best


def detect(
    *,
    main_changed: Iterable[str],
    claims: Sequence[dict[str, Any]],
    reservations: Sequence[dict[str, Any]] = (),
    snapshot_origin_main: Optional[str] = None,
    live_origin_main: Optional[str] = None,
    self_task_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return a conflict report. ``self_task_id`` is excluded from overlap checks."""
    changed = {norm(p) for p in main_changed}
    conflicts: list[dict[str, Any]] = []

    for claim in claims:
        task_id = claim.get("task_id")
        if not task_id or task_id == self_task_id:
            continue
        claim_paths = {norm(p) for p in (claim.get("changed_paths") or [])}
        exact = sorted(changed & claim_paths)
        if exact:
            conflicts.append({
                "type": "path_overlap", "task_id": task_id, "branch": claim.get("branch"),
                "owner": claim.get("owner"), "severity": "critical", "files": exact,
                "reason": "path changed on main is also modified on the branch",
            })
            continue
        # same-sensitive-dir warn (only when there is no exact overlap)
        warn_files = sorted(
            p for p in changed
            if is_sensitive(p) and any(
                is_sensitive(cp) and _same_sensitive_dir(p, cp) for cp in claim_paths
            )
        )
        if warn_files:
            conflicts.append({
                "type": "path_overlap", "task_id": task_id, "branch": claim.get("branch"),
                "owner": claim.get("owner"), "severity": "warn", "files": warn_files,
                "reason": "change inside a sensitive directory also touched on the branch",
            })

    for path in sorted(changed):
        res = _reservation_owner(path, reservations)
        if res is None:
            continue
        if self_task_id and res.get("task_id") == self_task_id:
            continue
        conflicts.append({
            "type": "reservation", "task_id": res.get("task_id"),
            "owner": res.get("task_id"), "severity": "critical", "files": [path],
            "scope": res.get("scope"), "issue_number": res.get("issue_number"),
            "reason": f"path is inside a scope reserved for Issue #{res.get('issue_number')}",
        })

    stale = bool(
        snapshot_origin_main and live_origin_main and snapshot_origin_main != live_origin_main
    )
    if stale:
        conflicts.append({
            "type": "stale_main", "task_id": None, "owner": None, "severity": "critical",
            "files": [], "snapshot_origin_main": snapshot_origin_main,
            "live_origin_main": live_origin_main,
            "reason": "the snapshot used to decide is older than live origin/main",
        })

    decision = "block" if any(c["severity"] == "critical" for c in conflicts) else "allow"
    return {
        "main_changed": sorted(changed),
        "conflicts": conflicts,
        "critical": [c for c in conflicts if c["severity"] == "critical"],
        "stale_main": stale,
        "decision": decision,
    }


def _same_sensitive_dir(a: str, b: str) -> bool:
    for d in SENSITIVE_DIRS:
        if _in_dir(a, d) and _in_dir(b, d):
            return True
    return a in SENSITIVE_FILES and a == b


def unmerged_branches(
    branches: Sequence[str],
    origin_main: str,
    is_ancestor: Callable[[str, str], bool],
) -> list[str]:
    """Return branches whose tip is not an ancestor of ``origin_main``."""
    return [b for b in branches if not is_ancestor(b, origin_main)]


# ---------------------------------------------------------------------------
# Read-only git gathering
# ---------------------------------------------------------------------------
def _git(repo: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def gather_claims(repo: str | Path, origin_main: str) -> list[dict[str, Any]]:
    """Enumerate active ``wt/t_*`` worktrees and the files each one touches.

    Read-only: ``worktree list`` / ``diff`` / ``status`` only.
    """
    claims: list[dict[str, Any]] = []
    wt = _git(repo, "worktree", "list", "--porcelain")
    if wt.returncode != 0:
        return claims
    current_path = None
    for line in wt.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and current_path:
            branch = line[len("branch "):].strip().replace("refs/heads/", "")
            if branch.startswith("wt/t_"):
                task_id = branch.split("/")[-1]
                base = _git(repo, "merge-base", origin_main, branch).stdout.strip()
                files: set[str] = set()
                if base:
                    diff = _git(repo, "diff", "--name-only", f"{base}..{branch}")
                    files |= {norm(p) for p in diff.stdout.splitlines() if p.strip()}
                status = _git(repo, "-C", current_path, "status", "--porcelain")
                files |= {norm(p[3:]) for p in status.stdout.splitlines() if p.strip()}
                claims.append({
                    "task_id": task_id, "branch": branch, "worktree": current_path,
                    "changed_paths": sorted(files), "base_sha": base or None,
                })
            current_path = None
    return claims


def changed_on_main(repo: str | Path, old_sha: Optional[str], new_sha: str) -> list[str]:
    if not old_sha or old_sha == new_sha:
        return []
    diff = _git(repo, "diff", "--name-only", f"{old_sha}..{new_sha}")
    return [norm(p) for p in diff.stdout.splitlines() if p.strip()]
