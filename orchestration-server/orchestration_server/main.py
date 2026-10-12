"""Uvicorn entrypoint for the orchestration server."""

from __future__ import annotations

import uvicorn

from .api import build_app
from .config import get_settings


app = build_app(get_settings())


if __name__ == "__main__":
    uvicorn.run(
        "orchestration_server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        **get_settings().ssl_config,
    )