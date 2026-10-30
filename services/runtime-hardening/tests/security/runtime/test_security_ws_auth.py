"""WebSocket authentication tests for runtime-hardening (SEC-001-WS).

AuthMiddleware is a BaseHTTPMiddleware, which Starlette never runs for
WebSocket handshakes — so ``/agents/{agent_id}/events`` authenticates
explicitly (API key via ``?api_key=`` query parameter, checked *before*
``accept()``) and enforces a read-equivalent role (mirrors
``GET /agents/{id}`` which is gated by ``Depends(require_read)``).

Proves the acceptance contract:
  * no API key -> handshake rejected with close code 1008, no data streamed
  * invalid key -> rejected with close code 1008
  * read/write/admin key -> connects and streams ``{"type":"state",...}``
  * existing ping->pong and AgentNotFound->error + close(1008) flows intact
"""

from __future__ import annotations

import os

os.environ.setdefault("AUTH_ENABLED", "false")

import pytest
import shared.auth_middleware as auth_mod
from starlette.websockets import WebSocketDisconnect

SPEC: dict = {
    "id": "agent-ws-auth",
    "name": "ws-auth",
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


def _create_agent(client) -> None:
    assert (
        client.post("/agents", json=SPEC, headers={"X-API-Key": "wri"}).status_code
        == 201
    )


def test_ws_no_key_rejected(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    client = _client(settings, quota_config)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/agents/agent-ws-auth/events"),
    ):
        pass  # pragma: no cover - handshake must be rejected before accept
    assert exc.value.code == 1008


def test_ws_invalid_key_rejected(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    client = _client(settings, quota_config)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/agents/agent-ws-auth/events?api_key=bogus"),
    ):
        pass  # pragma: no cover - handshake must be rejected before accept
    assert exc.value.code == 1008


def test_ws_read_key_connects_and_streams_state(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    client = _client(settings, quota_config)
    _create_agent(client)
    with client.websocket_connect("/agents/agent-ws-auth/events?api_key=rea") as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        assert first["agentId"] == "agent-ws-auth"


def test_ws_read_key_ping_pong(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    client = _client(settings, quota_config)
    _create_agent(client)
    with client.websocket_connect("/agents/agent-ws-auth/events?api_key=rea") as ws:
        assert ws.receive_json()["type"] == "state"
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"


def test_ws_unknown_agent_error_flow(monkeypatch, settings, quota_config):
    """Authenticated client on a non-existent agent still gets error + close(1008)."""
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    client = _client(settings, quota_config)
    with client.websocket_connect("/agents/ghost/events?api_key=rea") as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_ws_admin_key_allowed(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    client = _client(settings, quota_config)
    _create_agent(client)
    with client.websocket_connect("/agents/agent-ws-auth/events?api_key=adm") as ws:
        assert ws.receive_json()["type"] == "state"


def test_ws_no_configured_keys_rejects_everything(monkeypatch, settings, quota_config):
    _enable_auth(monkeypatch, admin=[], write=[], read=[])
    client = _client(settings, quota_config)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/agents/agent-ws-auth/events?api_key=any"),
    ):
        pass  # pragma: no cover - no key configured -> rejected
    assert exc.value.code == 1008
