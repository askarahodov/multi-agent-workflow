"""Real PostgreSQL concurrent startup / additive index migration regression.

Runs in GitHub Actions against a disposable PostgreSQL service. Skips in
generic SQLite-only jobs; no credentials or production DB are required.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from orchestration_server.db import QUARANTINE_EVENT_INDEX, build_engine, create_all
from orchestration_server.migrations import ensure_schema, existing_quarantine_index


@pytest.mark.asyncio
async def test_two_postgres_upgraders_serialize_missing_index():
    url = os.environ.get("MAW_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set MAW_TEST_POSTGRES_URL for disposable PostgreSQL CI")

    seed = build_engine(url)
    try:
        await create_all(seed)
        async with seed.begin() as conn:
            await conn.execute(text(f"DROP INDEX IF EXISTS {QUARANTINE_EVENT_INDEX}"))
            await conn.execute(text(
                "INSERT INTO saga_events "
                "(run_id,aggregate_type,aggregate_id,event_type,created_at) "
                "VALUES ('pg-run','task','pg-evidence','task.recovery_quarantined',NOW())"
            ))
        assert not await existing_quarantine_index(seed)

        async def upgrade() -> dict:
            engine = build_engine(url)
            try:
                return await ensure_schema(engine)
            finally:
                await engine.dispose()

        # Independent async engines use two physical PostgreSQL connections.
        ready = asyncio.Event()
        async def simultaneous() -> dict:
            await ready.wait()
            return await upgrade()

        first = asyncio.create_task(simultaneous())
        second = asyncio.create_task(simultaneous())
        ready.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=45)
        assert await existing_quarantine_index(seed)
        assert sum(QUARANTINE_EVENT_INDEX in r["created_indexes"] for r in results) <= 1
        assert all(r["created"] == [] for r in results)
        async with seed.connect() as conn:
            count = (await conn.execute(text(
                "SELECT COUNT(*) FROM saga_events WHERE aggregate_id='pg-evidence'"
            ))).scalar_one()
        assert count == 1
    finally:
        await seed.dispose()
