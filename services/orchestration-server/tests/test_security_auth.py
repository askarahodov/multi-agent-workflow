"""Role-based authorization tests for orchestration-server (SEC-001).

The main suite runs with AUTH_ENABLED=false, so auth is exercised separately
here (mirroring agent-management/tests/test_security_auth.py): we enable the
module-level auth configuration directly and assert that unauthenticated /
underprivileged requests are rejected while properly-keyed requests pass.

Proves the acceptance contract: no credentials -> 401, read-only key on a
write/admin endpoint -> 403, admin key -> passes (not 401/403).
"""

from __future__ import annotations

import os

os.environ.setdefault("AUTH_ENABLED", "false")

import shared.auth_middleware as auth_mod


def _enable_auth(monkeypatch, *, admin=(), write=(), read=()):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", set(admin))
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", set(write))
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", set(read))


def _client(tmp_path):
    from fastapi.testclient import TestClient

    from orchestration_server.api import build_app
    from orchestration_server.config import Settings

    app = build_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    )
    # Entering the TestClient context runs the app lifespan (engine + schema).
    return TestClient(app)


def test_unauthenticated_rejected(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.get("/api/v1/workflows/runs")
        assert resp.status_code == 401
        assert resp.json().get("type") == "urn:auth:error:unauthorized"


def test_invalid_key_is_rejected(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.get("/api/v1/workflows/runs", headers={"X-API-Key": "bogus"})
        assert resp.status_code == 401


def test_read_key_reads_list_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.get("/api/v1/workflows/runs", headers={"X-API-Key": "rea"})
        assert resp.status_code == 200


def test_read_key_denied_on_write_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post(
            "/api/v1/workflows/runs",
            json={"project_id": "p1", "name": "r1", "tasks": []},
            headers={"X-API-Key": "rea"},
        )
        assert resp.status_code == 403


def test_write_key_allowed_on_write_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post(
            "/api/v1/workflows/runs",
            json={"project_id": "p1", "name": "r1", "tasks": []},
            headers={"X-API-Key": "wri"},
        )
        # Auth passed; handler may 4xx on business validation, never 401/403.
        assert resp.status_code not in (401, 403)


def test_read_key_denied_on_admin_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        assert (
            c.post("/api/v1/admin/recover", headers={"X-API-Key": "rea"}).status_code
            == 403
        )
        assert (
            c.post("/api/v1/admin/recover", headers={"X-API-Key": "wri"}).status_code
            == 403
        )


def test_admin_key_allowed_on_admin_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post("/api/v1/admin/recover", headers={"X-API-Key": "adm"})
        assert resp.status_code not in (401, 403)


def test_read_key_denied_on_submit(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post(
            "/api/v1/tasks/t1/attempts/a1/submit",
            json={"output": "x"},
            headers={"X-API-Key": "rea"},
        )
        assert resp.status_code == 403


def test_health_is_exempt_from_auth(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        assert c.get("/health").status_code == 200


def test_no_configured_keys_rejects_everything(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=[], write=[], read=[])
    with _client(tmp_path) as c:
        assert c.get("/api/v1/workflows/runs").status_code == 401
        assert (
            c.get("/api/v1/workflows/runs", headers={"X-API-Key": "any"}).status_code
            == 401
        )
