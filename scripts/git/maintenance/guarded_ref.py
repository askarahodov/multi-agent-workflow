"""Guarded local ref deletion; no force, no name-only deletion.

Use only in an agreed maintenance window: Git ref transactions do not lock
non-cooperating checkout/worktree operations or the remote server.
"""
from __future__ import annotations

import re
import os
import stat
from contextlib import contextmanager
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


@contextmanager
def repo_mutation_lock(repo: Path):
    """Serialize cooperating mutators across linked worktrees.

    Never unlink the lock file. External Git writers do not participate:
    stop them and running agents before authorizing maintenance.
    """
    try:
        import fcntl
    except ImportError as exc:
        raise RefGuardError("Repository maintenance requires POSIX flock") from exc
    common = Path(_git(repo, "rev-parse", "--path-format=absolute",
                       "--git-common-dir").strip())
    if not common.is_absolute() or not common.is_dir():
        raise RefGuardError("Cannot resolve common Git directory")
    try:
        fd = os.open(common / "agent-gitflow-mutation.lock",
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except (OSError, AttributeError) as exc:
        raise RefGuardError(f"Cannot open repository lock: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RefGuardError("Repository lock is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RefGuardError("Repository mutation lock unavailable; retry after triage") from exc
        yield
    finally:
        os.close(fd)
