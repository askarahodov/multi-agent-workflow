"""SQLAlchemy engine/session helpers for the quality-gates subsystem."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

metadata: MetaData = Base.metadata


def build_engine(url: str) -> AsyncEngine:
    """Create an async engine for ``url`` (default SQLite or PostgreSQL)."""
    kwargs: dict = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


@asynccontextmanager
async def session_scope(sf: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sf() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
