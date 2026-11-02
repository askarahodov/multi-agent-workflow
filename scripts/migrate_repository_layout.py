#!/usr/bin/env python3
"""Issue #182: prepare an atomic monorepo layout migration in a local checkout.

Dry-run by default. Refuses dirty worktrees and moves only tracked files.
This is a developer tool, not a product runtime dependency.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

DESTINATIONS = {
    "frontend": "apps/frontend",
    "orchestration-server": "services/orchestration-server",
    "agent-management": "services/agent-management",
    "quality-gates": "services/quality-gates",
    "runtime-hardening": "services/runtime-hardening",
    "shared": "packages/shared",
}
COMPOSE_DEV = {"docker-compose.yml", "docker-compose.override.yml.example"}
COMPOSE_SECURE = None  # All compose.*.yml are secure/opt-in; preserve exact names.


def git(root: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def tracked_moves(root: pathlib.Path) -> list[tuple[str, str]]:
    paths = git(root, "ls-files", "-z").split("\0")
    result: list[tuple[str, str]] = []
    for source in paths:
        if not source:
            continue
        prefix = source.split("/", 1)[0]
        if prefix in DESTINATIONS:
            target = DESTINATIONS[prefix] + source[len(prefix):]
        elif source in COMPOSE_DEV:
            target = "deploy/compose/dev/" + source
        elif source.startswith("compose.") and source.endswith(".yml"):
            target = "deploy/compose/secure/" + source
        else:
            continue
        result.append((source, target))
    return result


def verify(root: pathlib.Path, moves: list[tuple[str, str]]) -> None:
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Tracked checkout has modifications; do not migrate concurrently")
    if not moves:
        raise RuntimeError("No files eligible for migration; checkout might already be migrated")
    seen: set[str] = set()
    for source, target in moves:
        if target in seen or (root / target).exists():
            raise RuntimeError(f"Target already exists: {target}")
        if not (root / source).is_file():
            raise RuntimeError(f"Missing tracked source: {source}")
        seen.add(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true", help="Run git mv; default prints the exact move plan")
    options = parser.parse_args()
    root = options.root.resolve()
    if not (root / ".git").exists():
        try:
            git(root, "rev-parse", "--show-toplevel")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("A local git checkout is required") from exc
    moves = tracked_moves(root)
    verify(root, moves)
    for source, target in moves:
        print(f"{source} -> {target}")
        if options.apply:
            (root / target).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(root), "mv", "--", source, target], check=True)
    print(f"{len(moves)} tracked moves " + ("applied" if options.apply else "planned (dry-run)"))
    if options.apply:
        print("NOT COMPLETE: rewrite Compose build contexts, bind paths, Dockerfile COPY, CI,")
        print("packaging, Makefile, scripts, tests, and docs before committing or opening a PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
