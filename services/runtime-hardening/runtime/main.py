"""Uvicorn entrypoint for the hardened runtime control plane.

Exposes the FastAPI app built by :func:`runtime.api.create_app` with the
default service wiring, matching the entrypoint pattern used by the other
platform services (``uvicorn runtime.main:app``).
"""

from __future__ import annotations

import uvicorn

from shared.auth_middleware import install_access_log_redaction

from .api import create_app

install_access_log_redaction()

app = create_app()


if __name__ == "__main__":
    uvicorn.run("runtime.main:app", host="0.0.0.0", port=8002, reload=False)
