"""End-to-end opt-in ticket issuance and stream authentication."""
from queue import Empty, Queue
from threading import Thread

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orchestration_server.api import build_app
from orchestration_server.config import Settings
from shared import auth_middleware as auth
from shared.auth_middleware import require_read


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
    @app.get("/untrusted/workflows/runs/{run_id}/events")
    async def unrelated_run_events(run_id: str, _auth=Depends(require_read)):
        return {"untrusted": run_id}

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

        # Duplicate credentials and empty trailing legacy keys must never
        # bypass the no-long-lived-key-in-URL contract.
        ambiguous_sse = create("sse").json()["ticket"]
        assert client.get(
            f"{prefix}/events?stream_ticket={ambiguous_sse}&api_key="
        ).status_code == 401
        assert client.get(
            f"{prefix}/events?api_key=reader&api_key=&stream_ticket={ambiguous_sse}"
        ).status_code == 401
        assert client.get(
            f"{prefix}/events?stream_ticket={ambiguous_sse}&stream_ticket=unused"
        ).status_code == 401
        allowed = client.get(
            f"{prefix}/events", params={"stream_ticket": ambiguous_sse, "max_events": 1}
        )
        assert allowed.status_code == 200
        assert client.get(
            f"{prefix}/events", params={"stream_ticket": ambiguous_sse}
        ).status_code == 403

        # A route that merely resembles SSE must not inherit provisional READ.
        assert client.get(
            "/untrusted/workflows/runs/not-a-real-run/events",
            params={"stream_ticket": "unrelated"},
        ).status_code == 401

        first = create("sse")
        assert first.status_code == 200, first.text
        assert first.headers["cache-control"] == "no-store"
        ticket = first.json()["ticket"]
        params = {"stream_ticket": ticket, "max_events": 1}
        stream = client.get(f"{prefix}/events", params=params)
        assert stream.status_code == 200
        assert "run.launched" in stream.text
        assert client.get(f"{prefix}/events", params=params).status_code == 403

        alias_ticket = create("sse").json()["ticket"]
        assert client.get(
            f"/workflows/runs/{run['id']}/events",
            params={"stream_ticket": alias_ticket, "max_events": 1},
        ).status_code == 200

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

        duplicate_ws = create("websocket").json()["ticket"]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"{prefix}/ws?stream_ticket={duplicate_ws}&stream_ticket=unused"
            ):
                pass
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"{prefix}/ws?stream_ticket={duplicate_ws}&api_key="
            ):
                pass
        with client.websocket_connect(
            f"{prefix}/ws?stream_ticket={duplicate_ws}&max_events=1"
        ) as ws:
            assert ws.receive_json()["type"] == "run_event"

        sse_only = create("sse").json()["ticket"]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"{prefix}/ws?stream_ticket={sse_only}"):
                pass

def test_open_ticket_websocket_closes_after_key_revocation(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "ADMIN_API_KEYS", {"admin"})
    monkeypatch.setattr(auth, "READ_API_KEYS", {"reader"})
    monkeypatch.setattr(auth, "WRITE_API_KEYS", set())
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'revocation.db'}",
        recover_on_startup=False,
        stream_tickets_enabled=True,
        stream_ticket_database=str(tmp_path / "tickets.db"),
    ))
    with TestClient(app) as client:
        admin = {"X-API-Key": "admin"}
        project = client.post("/projects", json={"name": "revocation"}, headers=admin).json()
        run = client.post("/workflows/runs", headers=admin, json={
            "project_id": project["id"], "name": "revocation",
            "tasks": [{"title": "one"}],
        }).json()
        prefix = f"/api/v1/workflows/runs/{run['id']}"
        token = client.post(
            f"{prefix}/stream-tickets", headers={"Authorization": "Bearer reader"},
            json={"transport": "websocket"},
        ).json()["ticket"]
        with client.websocket_connect(
            f"{prefix}/ws?stream_ticket={token}&poll_interval=0.05"
        ) as ws:
            assert ws.receive_json()["type"] == "run_event"
            monkeypatch.setattr(auth, "READ_API_KEYS", set())
            # Receive is a synchronous blocking call. Run it in a daemon
            # reader and bound the wait so a broken revocation path fails
            # promptly instead of hanging the whole CI suite.
            results: Queue[int | BaseException] = Queue()

            def consume_until_close():
                try:
                    while True:
                        ws.receive_json()
                except WebSocketDisconnect as exc:
                    results.put(exc.code)
                except BaseException as exc:
                    results.put(exc)

            reader = Thread(target=consume_until_close, daemon=True)
            reader.start()
            try:
                try:
                    result = results.get(timeout=8)
                except Empty:
                    ws.close(code=1000)
                    pytest.fail("revoked WebSocket did not close within 8 seconds")
                if isinstance(result, BaseException):
                    raise result
                assert result == 1008
            finally:
                if reader.is_alive():
                    ws.close(code=1000)
                reader.join(timeout=2)


def test_development_mode_rejects_ambiguous_sse_ticket_urls(tmp_path, monkeypatch):
    """Even with AUTH_ENABLED=false, ticket-mode SSE must reject URL key mixing."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dev-events.db'}",
        recover_on_startup=False,
        stream_tickets_enabled=True,
        stream_ticket_database=str(tmp_path / "dev-tickets.db"),
    ))
    with TestClient(app) as client:
        project = client.post("/projects", json={"name": "dev ticket"}).json()
        run = client.post("/workflows/runs", json={
            "project_id": project["id"], "name": "dev",
            "tasks": [{"title": "one"}],
        }).json()
        prefix = f"/api/v1/workflows/runs/{run['id']}"
        for bad_suffix in (
            "&api_key=",
            "&api-key=legacy",
            "&stream_ticket=unused",
            "&stream_ticket=",
        ):
            ticket = client.post(
                f"{prefix}/stream-tickets", json={"transport": "sse"}
            ).json()["ticket"]
            response = client.get(
                f"{prefix}/events?stream_ticket={ticket}{bad_suffix}&max_events=1"
            )
            assert response.status_code == 401, (bad_suffix, response.text)
            # An invalid query must not consume the valid token.
            assert client.get(
                f"{prefix}/events",
                params={"stream_ticket": ticket, "max_events": 1},
            ).status_code == 200
        assert client.get(f"{prefix}/events?stream_ticket=").status_code == 401
