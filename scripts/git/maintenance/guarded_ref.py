"""Guarded local ref deletion; no force, no name-only deletion.

Use only in an agreed maintenance window: Git ref transactions do not lock
non-cooperating checkout/worktree operations or the remote server.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class RefGuardError(RuntimeError):
    pass


def _git(repo: Path, *args: str, data: str | None = None) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], input=data,
                          capture_output=True, text=True)
    if proc.returncode:
        raise RefGuardError(f"Git refused {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def direct_tip(repo: Path, ref: str) -> str:
    """Read an exact, non-symbolic ref; reject ambiguity and errors."""
    _git(repo, "check-ref-format", ref)
    sym = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--quiet", ref],
                         capture_output=True, text=True)
    if sym.returncode != 1:
        raise RefGuardError(f"Symbolic or unreadable ref: {ref}")
    oid = _git(repo, "show-ref", "--verify", "--hash", ref).strip()
    if not OID.fullmatch(oid):
        raise RefGuardError(f"Invalid tip: {ref}")
    return oid


def delete_merged_ref(repo: Path, branch: str, expected: str, target: str,
                      target_tip: str) -> None:
    """Atomically delete exactly expected, if still merged in exact target.

    Retain branch configuration rather than removing it without a ref lease.
    Never run concurrently with checkout/worktree creation on this host.
    """
    ref = "refs/heads/" + branch
    if (not OID.fullmatch(expected) or not OID.fullmatch(target_tip)
            or len(expected) != len(target_tip) or ref == target
            or not target.startswith(("refs/heads/", "refs/remotes/"))):
        raise RefGuardError("Invalid deletion identity")
    if direct_tip(repo, ref) != expected or direct_tip(repo, target) != target_tip:
        raise RefGuardError("Branch or target changed before deletion")
    _git(repo, "merge-base", "--is-ancestor", expected, target_tip)
    fields = _git(repo, "worktree", "list", "--porcelain", "-z").split("\0")
    if (f"branch {ref}" in fields or "detached" in fields
            or any(f.startswith(("prunable", "locked")) for f in fields)):
        raise RefGuardError("Branch in use or ambiguous worktree state; retain")
    # Both identities are checked under Git's own ref locks.
    commands = (f"start\noption no-deref\nverify {target} {target_tip}\n"
                f"option no-deref\ndelete {ref} {expected}\nprepare\ncommit\n")
    _git(repo, "update-ref", "--stdin", data=commands)
