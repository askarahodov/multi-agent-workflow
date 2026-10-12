#!/usr/bin/env python3
"""CI entrypoint: run the unified SDLC pipeline for the platform.

Usage:
    python -m tools.ci.main [--repo-root PATH] [--gates-url URL] [--goal TEXT]
                            [--max-fix-loops N]

Runs the full SDLC flow: every backend module's test suite, then the SDLC
phase DAG with contract verification and (when --gates-url is given) the
quality-gates integration. Exits 0 only when everything passes.

This is the CI script referenced by task item (a) — a unified pipeline that
runs the full SDLC flow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .pipeline import CIPipeline, QualityGateApiClient


def _default_repo_root() -> Path:
    # Repository root is the nearest ancestor containing a backend module
    # directory (works for both the main checkout and a nested git worktree).
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "orchestration-server").is_dir():
            return ancestor
    return here.parents[2]


async def _main(args: argparse.Namespace) -> int:
    gate_client = QualityGateApiClient(args.gates_url) if args.gates_url else None
    pipeline = CIPipeline(
        Path(args.repo_root),
        gate_client=gate_client,
        run_id=args.run_id,
    )
    report = await pipeline.run(goal=args.goal, max_fix_loops=args.max_fix_loops)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0 if report.overall_ok else 1


def main() -> int:
    default_root = _default_repo_root()
    parser = argparse.ArgumentParser(description="Unified CI / SDLC pipeline.")
    parser.add_argument("--repo-root", default=str(default_root), help="Repository root (default: repo root).")
    parser.add_argument("--gates-url", default=None, help="Quality-gates service base URL, e.g. http://localhost:8003")
    parser.add_argument("--goal", default="run all backend suites and the SDLC flow", help="SDLC goal text.")
    parser.add_argument("--max-fix-loops", type=int, default=3, help="Max fix loop iterations before escalation.")
    parser.add_argument("--run-id", default=None, help="Stable run id (default: generated).")
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())