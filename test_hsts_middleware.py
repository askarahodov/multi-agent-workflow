"""HSTS + HTTP->HTTPS enforcement tests for all four services (SEC-002).

Each service integrates the shared ``add_security_middleware`` so that when TLS
is enabled:

* responses carry a ``Strict-Transport-Security`` header, and
* plain-HTTP requests are redirected to HTTPS (301).

Verified against the real app builders (agent-management via ``build_app``,
orchestration-server + quality-gates via ``build_app``, runtime-hardening via
``create_app``).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

HTTP_HEADER = "strict-transport-security"


@pytest.fixture(autouse=True)
def _tls_env_clean():
    keys = [
        "ORCH_TLS_CERT_FILE",
        "ORCH_TLS_KEY_FILE",
        "ORCH_TLS_CA_FILE",
        "AGENT_MGMT_TLS_CERT_FILE",
        "AGENT_MGMT_TLS_KEY_FILE",
        "AGENT_MGMT_TLS_CA_FILE",
        "AGENT_RUNTIME_TLS_CERT_FILE",
        "AGENT_RUNTIME_TLS_KEY_FILE",
        "AGENT_RUNTIME_TLS_CA_FILE",
        "QG_TLS_CERT_FILE",
        "QG_TLS_KEY_FILE",
        "QG_TLS_CA_FILE",
    ]
    for k in keys:
        os.environ.pop(k, None)
    yield
    for k in keys:
        os.environ.pop(k, None)


# --------------------------------------------------------------------------- #
# Shared middleware unit behaviour
# --------------------------------------------------------------------------- #
def test_add_security_middleware_hsts_header_when_tls_enabled():
    from fastapi.testclient import TestClient

    from shared.security_middleware import add_security_middleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    add_security_middleware(app, tls_enabled=True, tls_redirect=False)
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert HTTP_HEADER in resp.headers


def test_add_security_middleware_no_hsts_when_tls_disabled():
    from fastapi.testclient import TestClient

    from shared.security_middleware import add_security_middleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    add_security_middleware(app, tls_enabled=False)
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert HTTP_HEADER not in resp.headers


def test_add_security_middleware_redirects_http_to_https_when_tls_enabled():
    from starlette.testclient import TestClient

    from shared.security_middleware import add_security_middleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    add_security_middleware(app, tls_enabled=True, tls_redirect=True)
    # Do not follow the 301; assert the redirect itself is emitted to https.
    client = TestClient(app, base_url="http://testserver", follow_redirects=False)
    resp = client.get("/health")
    assert resp.status_code in (301, 307)
    assert resp.headers["location"].startswith("https://")


def test_add_security_middleware_hsts_on_redirect_when_tls_enabled():
    from starlette.testclient import TestClient

    from shared.security_middleware import add_security_middleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    add_security_middleware(app, tls_enabled=True, tls_redirect=True)
    client = TestClient(app, base_url="http://testserver", follow_redirects=False)
    resp = client.get("/health")
    assert resp.status_code in (301, 307)
    assert resp.headers["location"].startswith("https://")
    # The HTTP->HTTPS redirect is the critical path for HSTS: the header must
    # be present on the 301 itself, not only on the followed HTTPS response.
    assert HTTP_HEADER in resp.headers


# --------------------------------------------------------------------------- #
# Service integrations
# --------------------------------------------------------------------------- #
def test_agent_management_hsts_header_when_tls_enabled():
    from fastapi.testclient import TestClient

    os.environ["AGENT_MGMT_TLS_CERT_FILE"] = "/tmp/cert.pem"
    os.environ["AGENT_MGMT_TLS_KEY_FILE"] = "/tmp/key.pem"

    from agent_management.api import build_app

    app = build_app(lambda: None)
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert HTTP_HEADER in resp.headers


def test_agent_management_no_hsts_when_tls_disabled():
    from fastapi.testclient import TestClient

    from agent_management.api import build_app

    app = build_app(lambda: None)
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert HTTP_HEADER not in resp.headers


def test_orchestration_hsts_header_when_tls_enabled():
    from fastapi.testclient import TestClient

    os.environ["ORCH_TLS_CERT_FILE"] = "/tmp/cert.pem"
    os.environ["ORCH_TLS_KEY_FILE"] = "/tmp/key.pem"

    from orchestration_server.api import build_app
    from orchestration_server.config import Settings

    app = build_app(Settings())
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health")
    assert resp.status_code in (200, 404)  # route may be unprefixed
    assert HTTP_HEADER in resp.headers


def test_quality_gates_hsts_header_when_tls_enabled():
    from fastapi.testclient import TestClient

    os.environ["QG_TLS_CERT_FILE"] = "/tmp/cert.pem"
    os.environ["QG_TLS_KEY_FILE"] = "/tmp/key.pem"

    from quality_gates import api as qg_api
    from quality_gates.config import Settings

    app = qg_api.build_app(Settings())
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert HTTP_HEADER in resp.headers


def test_runtime_hsts_header_when_tls_enabled():
    from fastapi.testclient import TestClient

    os.environ["AGENT_RUNTIME_TLS_CERT_FILE"] = "/tmp/cert.pem"
    os.environ["AGENT_RUNTIME_TLS_KEY_FILE"] = "/tmp/key.pem"

    # Lightweight stub so we exercise create_app's middleware wiring without
    # touching a real cgroup/container backend.
    from runtime.config import RuntimeSettings

    fake = SimpleNamespace(
        settings=SimpleNamespace(tls_enabled=True),
        control_plane_health=SimpleNamespace(
            liveness=lambda: True,
            readiness=lambda: True,
            startup=lambda: True,
        ),
        metrics=SimpleNamespace(render=lambda: "ok"),
    )

    from runtime.api import create_app

    app = create_app(fake)
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/healthz/live")
    assert resp.status_code == 200
    assert HTTP_HEADER in resp.headers
    _ = RuntimeSettings  # keep import for parity with the legacy script