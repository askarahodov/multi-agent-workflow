"""Read-only inventory for concurrent-agent-safe repo layout migrations.

No branch operations, writes, subprocesses or filesystem mutation.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SERVICE_AREAS = (
    "orchestration-server", "agent-management",
    "runtime-hardening", "quality-gates", "frontend", "shared",
)
FOUNDATION = ("README.md", "Makefile", "docker-compose.yml", ".github/workflows")



# Tracked path consumers that must be reviewed before a directory move.
# Keep these patterns conservative: matches are evidence, not automatic rewrites.
CONSUMER_GLOBS = (
    "Dockerfile", "**/Dockerfile", "**/Dockerfile.*", "*.yml",
    "*.yaml", ".github/workflows/*.yml", "Makefile", "**/Makefile",
    "pyproject.toml", "**/pyproject.toml", "package.json",
    "**/package.json", "*.sh", "**/*.sh", "*.py", "**/*.py",
)
IGNORED_PARTS = frozenset((".git", "node_modules", ".venv", "venv", "__pycache__", ".worktrees", "dist", "build"))
MAX_CONSUMER_BYTES = 2_000_000


def path_references(root: Path, areas: tuple[str, ...] = SERVICE_AREAS) -> dict[str, list[str]]:
    """Map current root paths to files containing a literal path reference.

    Scans only local text and never follows symlinks or executes source files.
    Results are advisory: dynamic path construction still needs manual review.
    """
    if not root.is_dir():
        raise ValueError("Repository root does not exist")
    candidates: set[Path] = set()
    for pattern in CONSUMER_GLOBS:
        for candidate in root.glob(pattern):
            if candidate.is_file() and not candidate.is_symlink():
                rel = candidate.relative_to(root)
                if not any(part in IGNORED_PARTS for part in rel.parts):
                    candidates.add(candidate)
    result = {area: [] for area in areas}
    patterns = {area: re.compile(r"(?<![\w-])" + re.escape(area) + r"(?=/|\b)") for area in areas}
    for candidate in sorted(candidates):
        if candidate.stat().st_size > MAX_CONSUMER_BYTES:
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        name = candidate.relative_to(root).as_posix()
        for area, pattern in patterns.items():
            if pattern.search(content):
                result[area].append(name)
    return result

def inventory(root: Path) -> dict:
    if not root.is_dir():
        raise ValueError("Repository root does not exist")
    missing = [name for name in (*SERVICE_AREAS, *FOUNDATION) if not (root / name).exists()]
    if missing:
        raise ValueError("Repository structure incomplete: " + ", ".join(missing))
    overlays = sorted(p.name for p in root.glob("compose.*.yml") if p.is_file())
    reports = sorted(p.name for pattern in ("*-REPORT-*.md", "*-gate-output.json")
                     for p in root.glob(pattern) if p.is_file())
    root_probes = sorted(p.name for p in root.glob("test_*.py") if p.is_file())
    return {
        "service_areas": list(SERVICE_AREAS),
        "compose_overlays": overlays,
        "root_historical_reports": reports,
        "root_probes": root_probes,
        "path_consumers": path_references(root),
        "move_prohibited_without_agent_coordination": list(SERVICE_AREAS),
        "note": "Read-only advisory path references; dynamic paths and active branch ownership require independent review",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only issue #182 migration inventory")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        data = inventory(args.root)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
