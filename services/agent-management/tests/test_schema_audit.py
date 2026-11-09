"""Read-only schema drift detection for fresh and legacy SQLite stores."""
from __future__ import annotations

import sqlite3

import pytest

from agent_management.db import build_engine, create_all
from agent_management.schema_audit import inspect_schema


@pytest.mark.asyncio
async def test_fresh_database_has_no_drift(tmp_path):
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    try:
        await create_all(engine)
        assert await inspect_schema(engine) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_old_provider_table_is_detected_without_modification(tmp_path):
    path = tmp_path / "legacy.db"
    # Simulate a pre-upgrade installation with a provider table that lacks
    # current columns. The audit must never silently mutate real user data.
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE providers (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    connection.execute("INSERT INTO providers (id, name) VALUES (?, ?)", ("fixture-id", "fixture-name"))
    connection.commit()
    connection.close()

    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    try:
        issues = dict(await inspect_schema(engine))
        assert "providers" in issues
        assert "auth_config" in issues["providers"]
        assert "version" in issues["providers"]
        assert "model_profiles" in issues
    finally:
        await engine.dispose()

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT id, name FROM providers").fetchall() == [
            ("fixture-id", "fixture-name")
        ]
        columns = {item[1] for item in connection.execute("PRAGMA table_info(providers)")}
        assert columns == {"id", "name"}
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_create_all_does_not_repair_existing_columns(tmp_path):
    path = tmp_path / "unmigrated.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE providers (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    connection.commit()
    connection.close()

    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    try:
        await create_all(engine)
        issues = dict(await inspect_schema(engine))
        assert "providers" in issues
        assert "auth_config" in issues["providers"]
        assert "version" in issues["providers"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_service_lifespan_refuses_legacy_database(tmp_path, monkeypatch):
    """Do not expose healthy status while the settings endpoints would SQL 500."""
    import importlib

    main = importlib.import_module("agent_management.main")
    path = tmp_path / "old-startup.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE providers (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    connection.commit()
    connection.close()
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(main, "_engine", engine)
    with pytest.raises(RuntimeError, match="database schema is incompatible"):
        async with main._lifespan(main.app):
            pytest.fail("the incompatible schema must prevent app startup")
    # No implicit ALTER/DROP: the repair must be explicit and backed up.
    connection = sqlite3.connect(path)
    try:
        assert {c[1] for c in connection.execute("PRAGMA table_info(providers)")} == {
            "id", "name"
        }
    finally:
        connection.close()
