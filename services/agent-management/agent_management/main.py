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

from .api import build_app
from .config import get_settings
from .db import build_engine, build_session_factory, create_all
from .services import AgentManagementService

settings = get_settings()
_engine = build_engine(settings.database_url)
_sf = build_session_factory(_engine)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await create_all(_engine)
    yield
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