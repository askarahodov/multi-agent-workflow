"""Read-only database schema compatibility diagnostic for agent-management.

SQLAlchemy create_all() does not ALTER existing tables. Compare deployed columns
with ORM metadata before attributing an HTTP 500 to API keys/provider networking.
No row data, credentials, URL, or database contents are printed.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import inspect

from .config import get_settings
from .db import build_engine
from .models import Base


def _schema_difference(connection) -> list[tuple[str, tuple[str, ...]]]:
    inspector = inspect(connection)
    present = set(inspector.get_table_names())
    issues: list[tuple[str, tuple[str, ...]]] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        if table.name not in present:
            issues.append((table.name, ("<table missing>",)))
            continue
        columns = {col["name"] for col in inspector.get_columns(table.name)}
        missing = tuple(sorted(col.name for col in table.columns if col.name not in columns))
        if missing:
            issues.append((table.name, missing))
    return issues


async def inspect_schema(engine) -> list[tuple[str, tuple[str, ...]]]:
    """Only reads database schema metadata; never creates tables or alters data."""
    async with engine.connect() as connection:
        return await connection.run_sync(_schema_difference)


async def check_configuration() -> int:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        issues = await inspect_schema(engine)
    finally:
        await engine.dispose()
    if not issues:
        print("PASS: agent-management database schema has all ORM tables and columns")
        return 0
    for table, missing in issues:
        print(f"SCHEMA DRIFT: {table}: missing {', '.join(missing)}")
    print("NO-GO: back up the existing database and review migrations before any write.")
    return 1


def main() -> int:
    try:
        return asyncio.run(check_configuration())
    except Exception:
        # Connection errors can embed usernames/passwords in driver messages.
        print("FAIL: database schema cannot be inspected (check backend logs securely)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
