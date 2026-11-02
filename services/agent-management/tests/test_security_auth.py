"""Regression tests for API-key authentication added during EPIC-INT E8.

The main test suites run with AUTH_ENABLED=false so auth is exercised
separately here: we enable the module-level auth configuration directly and
assert that unauthenticated/underprivileged requests are rejected while
properly-keyed requests pass through.

Security finding E7-CRITICAL: no auth middleware on any FastAPI app. This
module proves the middleware enforces an allow-list of API keys and roles.
"""

from __future__ import annotations

import os

os.environ.setdefault("AUTH_ENABLED", "false")

import shared.auth_middleware as auth_mod
from agent_management.api import build_app

BASE = "/api/v1"


class _StubService:
    """Minimal service supporting the endpoints we exercise under auth."""

    def __init__(self):
        self.providers = _StubRepo()


class _StubRepo:
    async def list_providers(self, limit=50, offset=0, after=None):
        return [], 0, None

    async def create_provider(self, data: dict):
        """Return a synthetic Provider-like object for auth gate tests."""
        import uuid
        from datetime import datetime, timezone
        return type("_Provider", (), {
            "id": str(uuid.uuid4()),
            "name": data.get("name", "test"),
            "type": data.get("type", "mock"),
            "base_url": data.get("base_url"),
            "auth_config": data.get("auth_config") or {},
            "rate_limits": data.get("rate_limits"),
            "is_active": data.get("is_active", True),
            "version": 1,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })()

    async def delete_provider(self, provider_id: str):
        """No-op for auth gate tests."""
        return None


def _enable_auth(monkeypatch, *, admin=(), write=(), read=()):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", set(admin))
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", set(write))
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", set(read))


def _client():
    from fastapi.testclient import TestClient

    return TestClient(build_app(lambda: _StubService()))


def test_unauthenticated_request_is_rejected(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().get(f"{BASE}/providers")
    assert resp.status_code == 401
    assert resp.json().get("type") == "urn:auth:error:unauthorized"


def test_invalid_key_is_rejected(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().get(f"{BASE}/providers", headers={"X-API-Key": "bogus"})
    assert resp.status_code == 401


def test_read_key_reads_list_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().get(f"{BASE}/providers", headers={"X-API-Key": "rea"})
    assert resp.status_code == 200


def test_read_key_denied_on_write_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        f"{BASE}/providers", json={"name": "x", "type": "mock"},
        headers={"X-API-Key": "rea"},
    )
    assert resp.status_code == 403


def test_write_key_allowed_on_write_endpoint(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    resp = _client().post(
        f"{BASE}/providers", json={"name": "x", "type": "mock"},
        headers={"X-API-Key": "wri"},
    )
    # Stub repo has no create_provider -> would attempt and raise; use 422/403/401
    # as pass-criteria for the auth gate. We expect NOT 401/403 (auth passes).
    assert resp.status_code not in (401, 403)


def test_admin_required_for_delete_not_writable_by_write_key(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    c = _client()
    resp = c.delete(f"{BASE}/providers/p-1", headers={"X-API-Key": "wri"})
    assert resp.status_code == 403
    resp = c.delete(f"{BASE}/providers/p-1", headers={"X-API-Key": "adm"})
    assert resp.status_code not in (401, 403)


def test_health_is_exempt_from_auth(monkeypatch):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    assert _client().get("/health").status_code == 200


def test_no_configured_keys_rejects_everything(monkeypatch):
    _enable_auth(monkeypatch, admin=[], write=[], read=[])
    c = _client()
    assert c.get(f"{BASE}/providers").status_code == 401
    assert c.get(f"{BASE}/providers", headers={"X-API-Key": "any"}).status_code == 401