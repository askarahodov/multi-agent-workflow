"""Idempotent, additive schema migration for the orchestration store.

The platform evolves its persistence **additively**: new SQLAlchemy models may
appear (``workflow_definitions``, ``workflow_versions``, ``task_dependencies``,
...) but existing tables/columns are never dropped or rewritten in place. The
supported upgrade path for a database created by an older build is therefore:

    python -m orchestration_server.migrations --database-url <url> [--apply]

:func:`plan_migration` reports the delta between the live database and the
model metadata without touching it; :func:`ensure_schema` creates only the
missing tables (reusing :meth:`sqlalchemy.MetaData.create_all`, which is a
no-op for objects that already exist) and returns a report. No existing rows
are modified, so the operation is safe to re-run.

This complements the startup ``create_all`` used by the server lifespan: the CLI
gives operators a dry-run/backup-friendly way to upgrade a production SQLite
(or PostgreSQL) database before deploying a new build.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Iterable

from sqlalchemy import inspect

from .db import (
    QUARANTINE_EVENT_INDEX, acquire_schema_lock, build_engine,
    create_schema_objects,
)
from .models import Base


def required_tables() -> set[str]:
    """Every table declared by the current model metadata."""
    return set(Base.metadata.tables.keys())


def plan_migration(existing: Iterable[str]) -> dict:
    """Pure diff of the live schema against the model metadata."""
    present = set(existing)
    required = required_tables()
    return {
        "required": sorted(required),
        "present": sorted(required & present),
        "missing": sorted(required - present),
    }


async def existing_tables(engine) -> set[str]:
    """Names of tables that physically exist in the database."""
    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
    return set(names)


async def existing_quarantine_index(engine) -> bool:
    """Inspect the physical index (not merely the SQLAlchemy metadata)."""
    async with engine.connect() as conn:
        found = await conn.run_sync(
            lambda sync_conn: {
                item["name"] for item in inspect(sync_conn).get_indexes("saga_events")
            } if inspect(sync_conn).has_table("saga_events") else set()
        )
    return QUARANTINE_EVENT_INDEX in found


async def ensure_schema(engine) -> dict:
    """Check, create and report DDL in one serialized transaction.

    Reading the initial index state before taking the PostgreSQL advisory
    lock falsely reports duplicate index creation under concurrent upgrades.
    """
    async with engine.begin() as conn:
        await acquire_schema_lock(conn)

        def inspect_state(sync_conn):
            inspector = inspect(sync_conn)
            tables = set(inspector.get_table_names())
            has_index = (
                QUARANTINE_EVENT_INDEX in
                {item["name"] for item in inspector.get_indexes("saga_events")}
                if "saga_events" in tables else False
            )
            return tables, has_index

        before, index_before = await conn.run_sync(inspect_state)
        await create_schema_objects(conn)
        after, index_after = await conn.run_sync(inspect_state)
        return {
            "created": sorted(after - before),
            "created_indexes": [QUARANTINE_EVENT_INDEX]
            if index_after and not index_before else [],
            "present": sorted(before),
            "required": sorted(required_tables()),
        }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orchestration schema migration")
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy async URL, e.g. sqlite+aiosqlite:///./orchestration.db",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create missing tables (default: dry-run, print the plan only).",
    )
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    engine = build_engine(args.database_url)
    try:
        if not args.apply:
            report = plan_migration(await existing_tables(engine))
            report["missing_indexes"] = (
                [] if await existing_quarantine_index(engine)
                else [QUARANTINE_EVENT_INDEX]
            )
            print(json.dumps({"mode": "dry-run", **report}, indent=2))
            return 0
        report = await ensure_schema(engine)
        print(json.dumps({"mode": "apply", **report}, indent=2))
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
