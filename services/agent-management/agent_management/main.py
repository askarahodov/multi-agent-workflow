"""Uvicorn entrypoint for the agent-management subsystem.

Run directly (``python -m agent_management.main``) or via uvicorn
(``uvicorn agent_management.main:app``). The app is wired to the default SQLite
database so it boots with zero external infrastructure; production setups use
PostgreSQL + Alembic migrations instead of the convenience one-time schema create.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from shared.auth_middleware import install_access_log_redaction

from .api import build_app
from .config import get_settings
from .db import build_engine, build_session_factory, create_all
from .schema_audit import inspect_schema
from .services import AgentManagementService

# uvicorn renders access lines from record.args on its own loggers; without this
# the query-string API key would be written to the access log in plain text.
install_access_log_redaction()

settings = get_settings()
_engine = build_engine(settings.database_url)
_sf = build_session_factory(_engine)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        await create_all(_engine)
        # create_all never adds columns to old tables. Refuse to claim healthy
        # while every provider/agent API call would fail with SQL 500.
        issues = await inspect_schema(_engine)
        if issues:
            names = "; ".join(
                f"{table}: {', '.join(columns)}" for table, columns in issues
            )
            raise RuntimeError(
                "agent-management database schema is incompatible; "
                f"missing tables/columns: {names}. "
                "Back up the database and review migrations. No automatic repair attempted."
            )
        yield
    finally:
        await _engine.dispose()


app = build_app(lambda: AgentManagementService(_sf))
app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    uvicorn.run(
        "agent_management.main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        **settings.ssl_config,
    )