"""Role-based authorization tests for quality-gates (SEC-001).

The main suite runs with AUTH_ENABLED=false, so auth is exercised separately
here (mirroring agent-management/tests/test_security_auth.py): we enable the
module-level auth configuration directly and assert that unauthenticated /
underprivileged requests are rejected while properly-keyed requests pass.

Proves the acceptance contract: no credentials -> 401, read-only key on a
write endpoint -> 403, admin key -> passes (not 401/403).
"""

from __future__ import annotations

import os

os.environ.setdefault("AUTH_ENABLED", "false")

import shared.auth_middleware as auth_mod
from quality_gates.api import build_app


def _enable_auth(monkeypatch, *, admin=(), write=(), read=()):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", set(admin))
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", set(write))
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", set(read))


def _client():
    from fastapi.testclient import TestClient

    return TestClient(build_app())


def test_unauthenticated_read_rejected(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().get("/api/v1/gates")
    assert resp.status_code == 401
    assert resp.json().get("type") == "urn:auth:error:unauthorized"


def test_invalid_key_is_rejected(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().get("/api/v1/gates", headers={"X-API-Key": "bogus"})
    assert resp.status_code == 401


def test_read_key_reads_list_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().get("/api/v1/gates", headers={"X-API-Key": "rea"})
    assert resp.status_code == 200


def test_read_key_denied_on_write_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        "/api/v1/runs",
        json={"task_id": "t1", "workspace": "/tmp/ws", "gate": "reviewer"},
        headers={"X-API-Key": "rea"},
    )
    # Auth is enforced before the handler runs: read key must not reach the
    # write endpoint, regardless of pipeline state.
    assert resp.status_code == 403


def test_read_key_denied_on_transition(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        "/api/v1/tasks/t1/transition",
        json={"to": "review"},
        headers={"X-API-Key": "rea"},
    )
    assert resp.status_code == 403


def test_read_key_denied_on_release_approve(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        "/api/v1/releases/rel-1/approve",
        json={"approver": "human-qe"},
        headers={"X-API-Key": "rea"},
    )
    assert resp.status_code == 403


def test_write_key_allowed_on_write_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        "/api/v1/runs",
        json={"task_id": "t1", "workspace": "/tmp/ws", "gate": "reviewer"},
        headers={"X-API-Key": "wri"},
    )
    # Auth passed (not 401/403); the handler may 500 because no pipeline is
    # bound in this auth-focused test, which is expected.
    assert resp.status_code not in (401, 403)


def test_admin_key_allowed_on_write_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        "/api/v1/runs",
        json={"task_id": "t1", "workspace": "/tmp/ws", "gate": "reviewer"},
        headers={"X-API-Key": "adm"},
    )
    assert resp.status_code not in (401, 403)


def test_health_is_exempt_from_auth(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    assert _client().get("/health").status_code == 200


def test_no_configured_keys_rejects_everything(monkeypatch):
    _enable_auth(monkeypatch, admin=[], write=[], read=[])
    c = _client()
    assert c.get("/api/v1/gates").status_code == 401
    assert c.get("/api/v1/gates", headers={"X-API-Key": "any"}).status_code == 401
