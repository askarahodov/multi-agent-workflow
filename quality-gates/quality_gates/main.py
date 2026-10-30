"""Run the quality-gates API server with uvicorn.

Usage::

    python -m quality_gates.main --db sqlite+aiosqlite:///./qg.db
"""

from __future__ import annotations

import argparse

from shared.auth_middleware import install_access_log_redaction

from .api import build_app
from .config import Settings
from .db import build_engine, build_session_factory, create_all
from .pipeline import GatePipeline

install_access_log_redaction()


async def _wire(settings: Settings, db_url: str):
    engine = build_engine(db_url)
    await create_all(engine)
    sf = build_session_factory(engine)
    return build_app(settings=settings, sf=sf)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="sqlite+aiosqlite:///./quality_gates.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8005)
    args = parser.parse_args()

    import asyncio

    import uvicorn

    settings = Settings()

    async def _app():
        return await _wire(settings, args.db)

    app = asyncio.run(_app())
    uvicorn.run(app, host=args.host, port=args.port, **settings.ssl_config)


if __name__ == "__main__":
    main()
