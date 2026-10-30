"""Uvicorn entrypoint for the orchestration server."""

from __future__ import annotations

import uvicorn

from shared.auth_middleware import install_access_log_redaction

from .api import build_app
from .config import get_settings

# uvicorn renders access lines from record.args on its own loggers. Installing
# at import time also covers `uvicorn orchestration_server.main:app`, where
# __main__ does not run.
install_access_log_redaction()

app = build_app(get_settings())


if __name__ == "__main__":
    uvicorn.run(
        "orchestration_server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        **get_settings().ssl_config,
    )
