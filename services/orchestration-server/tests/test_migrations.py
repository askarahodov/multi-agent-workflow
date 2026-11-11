"""Additive, idempotent schema migration for the orchestration store."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from orchestration_server.db import QUARANTINE_EVENT_INDEX, build_engine, create_all
from orchestration_server.migrations import (
    ensure_schema,
    existing_quarantine_index,
    existing_tables,
    main,
    plan_migration,
    required_tables,
)


async def test_plan_migration_detects_missing_tables(tmp_path):
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'plan.db'}")
    try:
        await create_all(engine)
        all_tables = await existing_tables(engine)

        current = plan_migration(all_tables)
        assert current["missing"] == []
        assert set(current["required"]) == all_tables
        assert {"workflow_definitions", "workflow_versions"} <= set(current["required"])

        # Simulate an older database created before the design-time domain.
        stale = plan_migration(all_tables - {"workflow_definitions", "workflow_versions"})
        assert stale["missing"] == ["workflow_definitions", "workflow_versions"]
    finally:
        await engine.dispose()


async def test_ensure_schema_adds_only_missing_and_preserves_data(tmp_path):
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'apply.db'}")
    try:
        await create_all(engine)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projects (id, name, version, created_at, updated_at) "
                    "VALUES ('p1', 'proj', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            # Drop a table to mimic a database from an earlier build.
            await conn.execute(text("DROP TABLE workflow_definitions"))

        report = await ensure_schema(engine)
        assert report["created"] == ["workflow_definitions"]
        assert "workflow_definitions" in await existing_tables(engine)

        async with engine.connect() as conn:
            count = (await conn.execute(text("SELECT COUNT(*) FROM projects"))).scalar()
        assert count == 1  # existing rows are never rewritten

        # Re-running is a no-op.
        again = await ensure_schema(engine)
        assert again["created"] == []
    finally:
        await engine.dispose()


def test_migrations_cli_reports_and_applies(tmp_path, capsys):
    url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"

    async def _stale_schema() -> None:
        engine = build_engine(url)
        try:
            await create_all(engine)
            async with engine.begin() as conn:
                await conn.execute(text("DROP TABLE workflow_definitions"))
        finally:
            await engine.dispose()

    asyncio.run(_stale_schema())

    # Dry-run must not touch the database and must name the missing table.
    assert main(["--database-url", url]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["mode"] == "dry-run"
    assert dry["missing"] == ["workflow_definitions"]

    # Apply creates it.
    assert main(["--database-url", url, "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["created"] == ["workflow_definitions"]
    assert required_tables()


async def test_existing_database_receives_missing_recovery_index_without_row_changes(tmp_path):
    """Simulate a real old database: tables exist but the new index is absent."""
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'old-db-index.db'}")
    try:
        await create_all(engine)
        assert await existing_quarantine_index(engine)
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO saga_events "
                "(run_id,aggregate_type,aggregate_id,event_type,created_at) "
                "VALUES ('old-run','task','old-task','task.recovery_quarantined', CURRENT_TIMESTAMP)"))
            await conn.execute(text(f"DROP INDEX {QUARANTINE_EVENT_INDEX}"))
        assert not await existing_quarantine_index(engine)
        updated = await ensure_schema(engine)
        assert updated["created"] == []
        assert updated["created_indexes"] == [QUARANTINE_EVENT_INDEX]
        assert await existing_quarantine_index(engine)
        again = await ensure_schema(engine)
        assert again["created_indexes"] == []
        async with engine.connect() as conn:
            count = (await conn.execute(
                text("SELECT count(*) FROM saga_events WHERE aggregate_id='old-task'")
            )).scalar_one()
            plan = (await conn.execute(text(
                "EXPLAIN QUERY PLAN SELECT id FROM saga_events "
                "WHERE aggregate_type='task' AND aggregate_id='old-task' "
                "AND event_type='task.recovery_quarantined'"
            ))).all()
        assert count == 1
        assert any(QUARANTINE_EVENT_INDEX in row[-1] for row in plan)
    finally:
        await engine.dispose()
