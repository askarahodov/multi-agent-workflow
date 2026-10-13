"""Integration tests for scripts/git/maintenance/cleanup-branches.py.

Each test builds a real (bare remote + working clone) pair in a temp dir so
the git subprocess logic is exercised against genuine refs and worktrees,
without mocking git.

Run:  python -m pytest tests -q   (from scripts/git/maintenance)
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

# The CLI script is `cleanup-branches.py` (hyphenated, not importable by name),
# so load it from its real path to test the actual source.
_SCRIPT = Path(__file__).resolve().parent.parent / "cleanup-branches.py"
assert _SCRIPT.is_file(), f"cleanup script not found: {_SCRIPT}"  # noqa: S101 (test)
_spec = importlib.util.spec_from_file_location("cleanup_branches", _SCRIPT)
assert _spec is not None and _spec.loader is not None  # noqa: S101 (test)
cb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cb)


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def git_verbose(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {args} rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"  # noqa: S101 (test)
        )
    return proc.stdout


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create bare remote + working clone, seeded with main and two commits."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(tmp_path, "init", "--bare", str(remote))

    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init")
    git(seed, "config", "user.email", "t@t")
    git(seed, "config", "user.name", "T")
    git(seed, "checkout", "-b", "main")
    (seed / "f.txt").write_text("v1\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "c1")
    (seed / "f.txt").write_text("v2\n")
    git(seed, "commit", "-am", "c2")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    # Point the bare remote HEAD at `main` so clones land on the real branch
    # instead of the (nonexistent) default `master`.
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")

    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(remote), str(clone))
    git(clone, "config", "user.email", "t@t")
    git(clone, "config", "user.name", "T")
    git(clone, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    return remote, clone


def test_gone_upstream_branch_detected(tmp_path: Path) -> None:
    """A local branch whose remote counterpart was deleted is a deletion target."""
    _, clone = make_repo(tmp_path)

    # Create a feature branch, push it, then delete it on the remote (simulates
    # a squash-merged PR whose remote branch is removed).
    git(clone, "checkout", "-b", "wt/t_feat")
    (clone / "f.txt").write_text("v3\n")
    git_verbose(clone, "commit", "-am", "feat")
    git(clone, "push", "-u", "origin", "wt/t_feat")
    git(clone, "push", "origin", "--delete", "wt/t_feat")

    # Upstream now resolved against an origin remote-tracking ref that exists.
    # Prune/fetch to remove the stale tracking ref and surface "gone".
    cb._git(clone, ["fetch", "--prune"])
    git(clone, "checkout", "main")  # leave the branch so it can be cleaned up

    merged, gone = cb.classify(clone, "origin", ["main"])
    assert "wt/t_feat" in gone
    assert "wt/t_feat" not in merged


def test_merged_merge_commit_branch_detected(tmp_path: Path) -> None:
    """A branch whose tip is reachable from main is caught by --merged."""
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "feat/plain")
    (clone / "new.txt").write_text("x\n")
    git_verbose(clone, "add", "new.txt")
    git_verbose(clone, "commit", "-m", "feat plain")
    # Merge commit path: branch merged into main locally as a real merge.
    git(clone, "checkout", "main")
    git(clone, "merge", "--no-ff", "feat/plain", "-m", "merge feat/plain")
    git(clone, "push", "origin", "main")

    merged, gone = cb.classify(clone, "origin", ["main"])
    assert "feat/plain" in merged
    assert "feat/plain" not in gone


def test_protected_branches_never_deleted(tmp_path: Path) -> None:
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "wt/t_a")
    (clone / "f.txt").write_text("v3\n")
    git(clone, "commit", "-am", "a")
    git(clone, "push", "-u", "origin", "wt/t_a")
    git(clone, "push", "origin", "--delete", "wt/t_a")
    cb._git(clone, ["fetch", "--prune"])

    # main is current branch and is itself protected.
    git(clone, "checkout", "main")
    merged, gone = cb.classify(clone, "origin", ["main"], protect=["wt/t_a"])
    assert "wt/t_a" not in gone
    assert "main" not in gone and "main" not in merged


def test_current_branch_not_deleted(tmp_path: Path) -> None:
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "wt/t_live")
    (clone / "f.txt").write_text("x\n")
    git(clone, "commit", "-am", "live")
    git(clone, "push", "-u", "origin", "wt/t_live")
    git(clone, "push", "origin", "--delete", "wt/t_live")
    cb._git(clone, ["fetch", "--prune"])

    # Still checked out on wt/t_live => must not be deleted even though upstream gone.
    merged, gone = cb.classify(clone, "origin", ["main"])
    assert "wt/t_live" not in gone


def test_branch_without_upstream_is_left_alone(tmp_path: Path) -> None:
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "local-only")
    (clone / "f.txt").write_text("y\n")
    git(clone, "commit", "-am", "local only")

    merged, gone = cb.classify(clone, "origin", ["main"])
    assert "local-only" not in gone
    assert "local-only" not in merged


def test_dry_run_deletes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "wt/t_dry")
    (clone / "f.txt").write_text("x\n")
    git(clone, "commit", "-am", "dry")
    git(clone, "push", "-u", "origin", "wt/t_dry")
    git(clone, "push", "origin", "--delete", "wt/t_dry")
    cb._git(clone, ["fetch", "--prune"])

    monkeypatch.chdir(clone)
    rc = cb.main(["--repo", str(clone), "--dry-run", "--no-fetch"])
    assert rc == 0

    branches = git(clone, "branch", "--format=%(refname:short)").splitlines()
    assert "wt/t_dry" in branches  # untouched


def test_yes_deletes_gone_upstream_branch(tmp_path: Path) -> None:
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "wt/t_rm")
    (clone / "f.txt").write_text("x\n")
    git(clone, "commit", "-am", "rm")
    git(clone, "push", "-u", "origin", "wt/t_rm")
    git(clone, "push", "origin", "--delete", "wt/t_rm")
    cb._git(clone, ["fetch", "--prune"])
    git(clone, "checkout", "main")

    rc = cb.main(["--repo", str(clone), "--yes", "--no-fetch"])
    assert rc == 0
    branches = git(clone, "branch", "--format=%(refname:short)").splitlines()
    assert "wt/t_rm" not in branches


@pytest.mark.skipif(
    bool(os.environ.get("CI")) and not sys.stdin.isatty(),
    reason="needs a TTY for confirmation prompt",
)
def test_confirmation_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote, clone = make_repo(tmp_path)
    _ = remote

    git(clone, "checkout", "-b", "wt/t_q")
    (clone / "f.txt").write_text("x\n")
    git(clone, "commit", "-am", "q")
    git(clone, "push", "-u", "origin", "wt/t_q")
    git(clone, "push", "origin", "--delete", "wt/t_q")
    cb._git(clone, ["fetch", "--prune"])
    git(clone, "checkout", "main")

    monkeypatch.chdir(clone)
    rc = cb.main(["--repo", str(clone), "--no-fetch", "-y"])
    assert rc == 0
    branches = git(clone, "branch", "--format=%(refname:short)").splitlines()
    assert "wt/t_q" not in branches