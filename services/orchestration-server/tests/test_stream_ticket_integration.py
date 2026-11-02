"""End-to-end opt-in ticket issuance and stream authentication."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orchestration_server.api import build_app
from orchestration_server.config import Settings
from shared import auth_middleware as auth


def test_ticket_mode_requires_fresh_scoped_ticket_for_sse_and_ws(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "ADMIN_API_KEYS", {"admin"})
    monkeypatch.setattr(auth, "READ_API_KEYS", {"reader"})
    monkeypatch.setattr(auth, "WRITE_API_KEYS", set())
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'events.db'}",
        recover_on_startup=False,
        stream_tickets_enabled=True,
        stream_ticket_database=str(tmp_path / "stream-tickets.db"),
    ))
    with TestClient(app) as client:
        headers = {"X-API-Key": "admin"}
        project = client.post("/projects", json={"name": "ticket test"}, headers=headers).json()
        run = client.post("/workflows/runs", json={
            "project_id": project["id"], "name": "test",
            "tasks": [{"title": "one"}],
        }, headers=headers).json()
        prefix = f"/api/v1/workflows/runs/{run['id']}"
        create = lambda transport: client.post(
            f"{prefix}/stream-tickets", headers={"X-API-Key": "reader"},
            json={"transport": transport},
        )

        assert client.get(f"{prefix}/events", params={"api_key": "reader"}).status_code == 401
        no_auth = client.post(f"{prefix}/stream-tickets", json={"transport": "sse"})
        assert no_auth.status_code == 401

        first = create("sse")
        assert first.status_code == 200, first.text
        assert first.headers["cache-control"] == "no-store"
        ticket = first.json()["ticket"]
        params = {"stream_ticket": ticket, "max_events": 1}
        stream = client.get(f"{prefix}/events", params=params)
        assert stream.status_code == 200
        assert "run.launched" in stream.text
        assert client.get(f"{prefix}/events", params=params).status_code == 403

        ws_ticket = create("websocket").json()["ticket"]
        with client.websocket_connect(
            f"{prefix}/ws?stream_ticket={ws_ticket}&max_events=1"
        ) as ws:
            assert ws.receive_json()["type"] == "run_event"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"{prefix}/ws?stream_ticket={ws_ticket}"):
                pass

        mixed = create("websocket").json()["ticket"]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"{prefix}/ws?stream_ticket={mixed}&api_key=reader"
            ):
                pass

        sse_only = create("sse").json()["ticket"]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"{prefix}/ws?stream_ticket={sse_only}"):
                pass
