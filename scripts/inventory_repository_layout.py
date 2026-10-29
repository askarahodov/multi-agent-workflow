"""Read-only inventory for concurrent-agent-safe repo layout migrations.

No branch operations, writes, subprocesses or filesystem mutation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SERVICE_AREAS = (
    "orchestration-server", "agent-management",
    "runtime-hardening", "quality-gates", "frontend", "shared",
)
FOUNDATION = ("README.md", "Makefile", "docker-compose.yml", ".github/workflows")


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
        "move_prohibited_without_agent_coordination": list(SERVICE_AREAS),
        "note": "Read-only inventory; no active branch ownership can be inferred",
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
