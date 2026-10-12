"""Uvicorn entrypoint for the runtime-hardening control plane (SEC-002)."""

from __future__ import annotations

import uvicorn

from runtime.api import app_factory
from runtime.config import RuntimeSettings


app = app_factory()


if __name__ == "__main__":
    uvicorn.run(
        "runtime.main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        **RuntimeSettings().ssl_config,
    )