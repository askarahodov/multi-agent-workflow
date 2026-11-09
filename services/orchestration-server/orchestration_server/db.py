"""Async database engine, session factory and init helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


def build_engine(database_url: str):
    """Build an async engine.

    For SQLite we raise the busy timeout so concurrent writers wait for the
    lock instead of failing immediately with "database is locked"; PostgreSQL
    (asyncpg) is used unchanged.
    """
    kwargs: dict = {"future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    return create_async_engine(database_url, **kwargs)


def build_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Model metadata.create_all does not add indexes to existing tables. Keep a
# fixed, additive, idempotent DDL migration for upgraded SQLite/PostgreSQL DBs.
QUARANTINE_EVENT_INDEX = "ix_saga_events_aggregate_event"
_QUARANTINE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_saga_events_aggregate_event "
    "ON saga_events (aggregate_type, aggregate_id, event_type)"
)


async def create_all(engine) -> None:
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # IF NOT EXISTS does NOT serialize concurrent PostgreSQL index
            # creation. All application/CLI upgrades take the same lock
            # before metadata checkfirst and additive DDL; transaction exit
            # releases it even on failure. Stable two-part key is DB-scoped.
            await conn.execute(text("SELECT pg_advisory_xact_lock(786422, 20261109)"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_QUARANTINE_INDEX_DDL))


async def drop_all(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def session_scope(session_factory):
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise