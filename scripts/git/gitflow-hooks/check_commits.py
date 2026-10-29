#!/usr/bin/env python3
"""Validate a range of commits against the GitFlow Conventional-Commits policy.

Usage:
    check_commits.py <base-sha> <head-sha> [--repo DIR] [--allow-merge]

Reads the policy from AGENT_GITFLOW_RULES.md's YAML front-matter when available
(falling back to the compiled default) and checks every non-merge commit in
``<base-sha>..<head-sha>`` against it.

Exit codes:
    0   every commit in range is compliant (or the range is empty)
    1   at least one commit violates the policy (offending SHAs printed)
    2   usage / repo error
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_PATTERN = (
    r"^(feat|fix|docs|chore|refactor|perf|test|security|build|ci|revert)"
    r"(\([^)]+\)): [a-z].{1,71}$"
)
_TYPES = "feat|fix|docs|chore|refactor|perf|test|security|build|ci|revert"


def load_pattern(repo: Path) -> str:
    """Return the commit-format regex, preferring the rules doc front-matter."""
    rules = repo / "AGENT_GITFLOW_RULES.md"
    if rules.is_file():
        try:
            text = rules.read_text(encoding="utf-8")
        except OSError:
            return DEFAULT_PATTERN
        m = re.search(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if m:
            fm = m.group(1)
            pm = re.search(r"^\s*pattern:\s*['\"]?(.+?)['\"]?\s*$", fm, re.MULTILINE)
            if pm:
                pat = pm.group(1).strip().strip("'\"")
                # YAML single/double quoted escapes: undouble backslashes.
                pat = pat.replace("\\\\", "\\")
                try:
                    re.compile(pat)
                    return pat
                except re.error:
                    pass
    return DEFAULT_PATTERN


def _git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def commits_in_range(repo: Path, base: str, head: str, allow_merge: bool) -> list[tuple[str, str]]:
    """Return (sha, subject) pairs for the range, newest first, merge filtered."""
    fmt = "%H%x1f%s"
    try:
        out = _git(repo, ["log", "--format=" + fmt, f"{base}..{head}"])
    except RuntimeError:
        # Range may be a single commit or unrelated history; fall back to head.
        out = _git(repo, ["log", "-1", "--format=" + fmt, head])
    result: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x1f")
        if not allow_merge and _is_merge(repo, sha):
            continue
        result.append((sha, subject))
    return result


def _is_merge(repo: Path, sha: str) -> bool:
    out = _git(repo, ["rev-list", "--parents", "-n", "1", sha])
    return len(out.split()) > 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_commits.py", description=__doc__)
    parser.add_argument("base", help="base sha (exclusive)")
    parser.add_argument("head", help="head sha (inclusive)")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--allow-merge", action="store_true", help="do not skip merge commits")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        try:
            _git(repo, ["rev-parse", "--git-dir"])
        except RuntimeError:
            print(f"error: {repo} is not a git repository", file=sys.stderr)
            return 2

    pattern = load_pattern(repo)
    try:
        rx = re.compile(pattern)
    except re.error as exc:  # pragma: no cover - defensive
        print(f"error: invalid commit pattern from policy: {exc}", file=sys.stderr)
        return 2

    try:
        commits = commits_in_range(repo, args.base, args.head, args.allow_merge)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not commits:
        print(f"check_commits: no commits in {args.base}..{args.head} (ok)")
        return 0

    bad: list[tuple[str, str]] = []
    for sha, subject in commits:
        if not rx.match(subject):
            bad.append((sha, subject))

    if bad:
        print("GF-04 violations (Conventional Commits required):", file=sys.stderr)
        for sha, subject in bad:
            print(f"  {sha[:12]}  {subject!r}", file=sys.stderr)
        print(
            f"\nexpected: <type>(<scope>): <summary>  types=({_TYPES})",
            file=sys.stderr,
        )
        return 1

    print(f"check_commits: {len(commits)} commit(s) in range comply with GF-04")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
