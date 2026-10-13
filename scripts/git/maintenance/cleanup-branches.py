#!/usr/bin/env python3
"""Safely clean up stale local branches.

Identifies local branches that are safe to delete because the work they
contain is no longer needed locally:

  * ``upstream gone``  -- the branch has a configured upstream that no longer
    exists on the remote (e.g. the remote branch was deleted after its PR was
    squash-merged).  This is the primary signal for the agent workflow defined
    in ``gitflow-strategy.md``, because squash merges mean the local branch's
    commits are **not** ancestors of ``main`` and would never be caught by a
    plain ``git branch --merged`` scan.
  * ``merged``  -- the branch tip is reachable from a target branch (main /
    develop).  Catches merge-commit based branches.

By default the script only *reports* what it would delete.  It never deletes
without explicit confirmation unless ``--yes`` is passed, and it always skips
protected branches (current branch, HEAD, the target branches themselves, and
anything listed with ``--protect``).

Usage
-----
    cleanup-branches.py [--repo DIR] [--dry-run] [--yes] [--prune-remotes]
                        [--target main develop] [--protect release/v1.2.0]

Exit codes
----------
    0   success (including dry-run)
    1   nothing to delete is a success; 1 = git/operational error
    2   deletion was cancelled at the confirmation prompt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

# Protected by default regardless of discovery.
DEFAULT_PROTECTED = ("main", "master", "develop", "HEAD")


class GitError(RuntimeError):
    """Raised when a git invocation fails."""


def _git(repo: Path, args: Sequence[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail}") from exc
    return proc.stdout


def _git_ok(repo: Path, args: Sequence[str]) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def current_branch(repo: Path) -> str | None:
    """Return the symbolic short name of HEAD, or None when detached."""
    try:
        out = _git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
        return out.strip() or None
    except GitError:
        return None


def local_upstreams(repo: Path) -> dict[str, str | None]:
    """Map local branch name -> configured upstream short ref (or None).

    Uses ``for-each-ref`` so it works with linked worktrees and does not
    depend on ``git branch`` porcelain output formatting.
    """
    rows = _git(
        repo,
        ["for-each-ref", "--format=%(refname:short)%09%(upstream:short)", "refs/heads/"],
    )
    upstreams: dict[str, str | None] = {}
    for line in rows.splitlines():
        if not line:
            continue
        name, _, upstream = line.partition("\t")
        upstreams[name] = upstream or None
    return upstreams


def merged_branches(repo: Path, target: str) -> set[str]:
    """Return local branches whose tip is reachable from ``target``."""
    out = _git(
        repo,
        ["branch", "--merged", target, "--format=%(refname:short)"],
    )
    return {name.strip() for name in out.splitlines() if name.strip()}


def upstream_missing(repo: Path, upstream: str) -> bool:
    """True when the remote-tracking ref ``upstream`` does not exist locally."""
    return not _git_ok(repo, ["rev-parse", "--verify", "--quiet", f"refs/remotes/{upstream}"])


def discover_targets(repo: Path, remote: str) -> list[str]:
    """Return local branch names to treat as merge targets (existing only).

    Prefers configured targets, then the remote HEAD default branch, then the
    conventional ``main`` / ``develop`` names -- filtered to those that exist
    locally or as remote-tracking refs.
    """
    candidates: list[str] = []
    # Remote HEAD default branch first.
    try:
        remote_head = _git(repo, ["symbolic-ref", f"refs/remotes/{remote}/HEAD"]).strip()
        # refs/remotes/origin/main -> origin/main
        if remote_head.startswith(f"refs/remotes/{remote}/"):
            candidates.append(remote_head[len(f"refs/remotes/{remote}/"):])
    except GitError:
        pass
    candidates.extend(["main", "develop"])

    targets: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        # Exists as local or remote-tracking ref?
        if _git_ok(repo, ["rev-parse", "--verify", "--quiet", f"refs/heads/{name}"]) or _git_ok(
            repo, ["rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{name}"]
        ):
            targets.append(name)
    return targets


def classify(
    repo: Path,
    remote: str,
    targets: Sequence[str],
    protect: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """Return (merged_branches_to_delete, gone_upstream_branches_to_delete).

    Excludes the current branch, protected names, and everything not safe to
    delete.  ``protect`` may contain exact names; default protection always
    applies.
    """
    up = local_upstreams(repo)
    current = current_branch(repo)

    protected: set[str] = set(DEFAULT_PROTECTED)
    protected.update(name for name in protect if name)
    protected.update(targets)
    if current:
        protected.add(current)

    # Scan against local targets where present, else remote-tracking ref name.
    scan_targets: list[str] = []
    for t in targets:
        if t in up:
            scan_targets.append(t)
        else:
            scan_targets.append(f"{remote}/{t}")

    merged: set[str] = set()
    for t in scan_targets:
        merged |= merged_branches(repo, t)

    merged_to_delete = sorted(n for n in merged if n not in protected)
    gone: list[str] = []
    for name, upstream in up.items():
        if name in protected:
            continue
        if not upstream:
            continue
        if upstream_missing(repo, upstream):
            gone.append(name)
    gone_to_delete = sorted(set(gone) - set(merged_to_delete))

    return merged_to_delete, gone_to_delete


def delete_branch(repo: Path, name: str, force: bool) -> None:
    flag = "-D" if force else "-d"
    _git(repo, ["branch", flag, name])


def confirm(message: str, default: bool = False) -> bool:
    prompt = f"{message} [y/N] " if not default else f"{message} [Y/n] "
    answer = input(prompt).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cleanup-branches.py",
        description="Safely delete stale local branches (upstream gone or merged into main/develop).",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="git repository root (default: cwd)")
    parser.add_argument("-r", "--remote", default="origin", help="remote name (default: origin)")
    parser.add_argument(
        "-t",
        "--target",
        action="append",
        default=None,
        help="target branch(es) for merged detection (repeatable; default: main + develop)",
    )
    parser.add_argument(
        "-p",
        "--protect",
        action="append",
        default=None,
        help="additional branch name(s) to never delete (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted without changing anything (default)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="delete without prompting (use in cron/CI)",
    )
    parser.add_argument(
        "--prune-remotes",
        action="store_true",
        help="prune remote-tracking refs (git fetch --prune + remote prune)",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip the initial fetch (use --prune-remotes to still prune local refs)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    if not (repo / ".git").exists() and not _git_ok(repo, ["rev-parse", "--git-dir"]):
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 1

    remote = args.remote
    targets = list(args.target) if args.target else discover_targets(repo, remote)

    # Fetch freshly so upstream-gone detection is accurate.  Squash-merged
    # agent branches rely on the remote branch being deleted, so we must see
    # the current remote state.
    if not args.no_fetch:
        fetch = ["fetch", remote]
        if args.prune_remotes:
            fetch.append("--prune")
        try:
            _git(repo, fetch)
        except GitError as exc:
            # A transient network failure should not block a local dry-run.
            print(f"warning: fetch failed: {exc}", file=sys.stderr)
    elif args.prune_remotes:
        _git(repo, ["remote", "prune", remote])
        # Still prune remote-tracking refs even without a fresh fetch.
        _git(repo, ["fetch", remote, "--prune", "--dry-run"])

    merged, gone = classify(repo, remote, targets, list(args.protect or ()))

    if not merged and not gone:
        print("Nothing to clean up: no local branches are merged or have a missing upstream.")
        return 0

    print("Branches identified as safe to remove:")
    for name in merged:
        print(f"  [merged]        {name}")
    for name in gone:
        print(f"  [upstream gone] {name}")

    if args.dry_run or not args.yes:
        action = "would delete" if args.dry_run else "will delete"
        n = len(merged) + len(gone)
        if args.dry_run:
            print(f"\nDry-run: {action} {n} local branch(es). Nothing changed.")
            return 0

        if not sys.stdin.isatty():
            print(
                "\nerror: not a TTY and --yes not given; refusing to delete "
                "without confirmation. Pass --yes for headless/cron runs.",
                file=sys.stderr,
            )
            return 2

        if not confirm(f"Delete {n} local branch(es)?"):
            print("Cancelled.")
            return 2

    # Deletions.  Merged branches are removed with safe `-d`; upstream-gone
    # branches use force `-D` because their commits are typically not
    # reachable from HEAD after a squash merge.
    deleted: list[str] = []
    for name in merged:
        try:
            delete_branch(repo, name, force=False)
        except GitError as exc:
            print(f"warning: could not delete {name}: {exc}", file=sys.stderr)
            continue
        deleted.append(name)
    for name in gone:
        try:
            delete_branch(repo, name, force=True)
        except GitError as exc:
            print(f"warning: could not delete {name}: {exc}", file=sys.stderr)
            continue
        deleted.append(name)

    if args.prune_remotes:
        _git(repo, ["remote", "prune", remote])

    print(f"Deleted {len(deleted)} local branch(es):")
    for name in deleted:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())