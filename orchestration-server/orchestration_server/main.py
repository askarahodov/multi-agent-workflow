"""Uvicorn entrypoint for the orchestration server."""

from __future__ import annotations

import logging

import uvicorn

from shared.auth_middleware import api_key_filter

from .api import build_app
from .config import get_settings

# Apply API key redaction filter to the uvicorn access/error loggers so that
# query-string `api_key` and `Authorization` values are never written to logs in
# plain text (CWE-532). Applied at import time so it also covers
# `uvicorn orchestration_server.main:app`, where `__main__` does not run.
for _logger_name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_logger_name).addFilter(api_key_filter)

app = build_app(get_settings())


if __name__ == "__main__":
    uvicorn.run(
        "orchestration_server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        **get_settings().ssl_config,
    )
