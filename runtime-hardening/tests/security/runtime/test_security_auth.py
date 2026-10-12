"""Role-based authorization tests for runtime-hardening (SEC-001).

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

SPEC: dict = {
    "id": "agent-auth",
    "name": "auth",
    "isolationTier": "gvisor-runsc",
    "image": "alpine:latest",
    "resourceClass": "untrusted",
    "workspace": {"baseImage": "alpine", "durable": True},
}


def _enable_auth(monkeypatch, *, admin=(), write=(), read=()):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", set(admin))
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", set(write))
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", set(read))


def _client(settings, quota_config):
    from fastapi.testclient import TestClient

    from runtime.api import RuntimeService, create_app

    svc = RuntimeService(
        settings=settings, quota_config=quota_config, manage_containers=False
    )
    return TestClient(create_app(svc))


def test_unauthenticated_rejected(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).get("/agents")
    assert resp.status_code == 401
    assert resp.json().get("type") == "urn:auth:error:unauthorized"


def test_invalid_key_is_rejected(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).get("/agents", headers={"X-API-Key": "bogus"})
    assert resp.status_code == 401


def test_read_key_reads_list_endpoint(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).get("/agents", headers={"X-API-Key": "rea"})
    assert resp.status_code == 200


def test_read_key_denied_on_create_agent(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).post(
        "/agents", json=SPEC, headers={"X-API-Key": "rea"}
    )
    assert resp.status_code == 403


def test_write_key_allowed_on_create_agent(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).post(
        "/agents", json=SPEC, headers={"X-API-Key": "wri"}
    )
    assert resp.status_code == 201


def test_read_key_denied_on_delete_agent(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).request(
        "DELETE", "/agents/agent-auth", headers={"X-API-Key": "rea"}
    )
    # DELETE requires admin: read key must be rejected before the handler.
    assert resp.status_code == 403


def test_write_key_denied_on_delete_agent(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).request(
        "DELETE", "/agents/agent-auth", headers={"X-API-Key": "wri"}
    )
    assert resp.status_code == 403


def test_admin_key_allowed_on_delete_agent(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).request(
        "DELETE", "/agents/agent-auth", headers={"X-API-Key": "adm"}
    )
    # Auth passed (not 401/403); agent was never created so handler returns 404.
    assert resp.status_code not in (401, 403)


def test_read_key_denied_on_pause_agent(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client(settings, quota_config).post(
        "/agents/agent-auth/pause", headers={"X-API-Key": "rea"}
    )
    assert resp.status_code == 403


def test_healthz_is_exempt_from_auth(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    c = _client(settings, quota_config)
    assert c.get("/healthz/live").status_code == 200
    assert c.get("/metrics").status_code == 200


def test_no_configured_keys_rejects_everything(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=[], write=[], read=[])
    c = _client(settings, quota_config)
    assert c.get("/agents").status_code == 401
    assert c.get("/agents", headers={"X-API-Key": "any"}).status_code == 401
