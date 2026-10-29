"""Real-time run event streaming (SSE + WebSocket) over the saga journal.

The saga journal is the durable record of every run/task/attempt transition;
these tests prove that the two transports expose those transitions to the UI,
that delivery is resumable from an event id, and that unknown runs fail closed.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orchestration_server.api import build_app
from orchestration_server.config import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'events.db'}",
        recover_on_startup=False,
    )


@pytest_asyncio.fixture
async def api(tmp_path):
    app = build_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def _launch(api, tasks):
    project = (await api.post("/projects", json={"name": "p"})).json()
    run = (
        await api.post(
            "/workflows/runs",
            json={"project_id": project["id"], "name": "r", "tasks": tasks},
        )
    ).json()
    return project, run


def _parse_sse(text: str) -> list[dict]:
    """Extract the ``data:`` payloads from an SSE body (ignore ping comments)."""
    events: list[dict] = []
    for block in text.split("\n\n"):
        data = None
        for line in block.splitlines():
            if line.startswith("data: "):
                data = line[len("data: "):]
        if data is not None:
            events.append(json.loads(data))
    return events


async def _read_stream(client, run_id: str, **params) -> str:
    async with client.stream(
        "GET", f"/workflows/runs/{run_id}/events", params=params
    ) as response:
        assert response.status_code == 200, response.status_code
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
    return body.decode()


async def test_sse_streams_launch_events(api):
    _, run = await _launch(api, [{"title": "t1"}])

    text = await _read_stream(api, run["id"], after=0, max_events=2, poll_interval=0.05)
    events = _parse_sse(text)

    assert [e["event"] for e in events] == ["run.launched", "task.created"]
    assert events[0]["id"] < events[1]["id"]
    assert all(e["run_id"] == run["id"] for e in events)
    assert events[1]["aggregate_type"] == "task"


async def test_sse_covers_task_lifecycle_and_resumes_without_duplicates(api):
    _, run = await _launch(api, [{"title": "t1"}])
    agent = (await api.post("/agents/register", json={"name": "a"})).json()
    task = (await api.get(f"/workflows/runs/{run['id']}/tasks")).json()["items"][0]
    attempt = (
        await api.post(f"/tasks/{task['id']}/claim", json={"agent_id": agent["id"]})
    ).json()
    await api.post(
        f"/tasks/{task['id']}/attempts/{attempt['id']}/submit",
        params={"agent_id": agent["id"]},
        json={"output": {"summary": "done"}},
    )

    text = await _read_stream(api, run["id"], after=0, poll_interval=0.05, idle_timeout=0.4)
    events = _parse_sse(text)
    kinds = [e["event"] for e in events]

    # The full lifecycle is observable in order, with no duplicates.
    assert "task.claimed" in kinds
    assert "task.completed" in kinds
    assert "run.completed" in kinds
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))

    # Resuming from the last seen id yields no already-delivered event.
    resumed = _parse_sse(
        await _read_stream(
            api, run["id"], after=ids[-1], poll_interval=0.05, idle_timeout=0.3
        )
    )
    assert resumed == []


async def test_sse_unknown_run_is_problem_details(api):
    response = await api.get("/workflows/runs/does-not-exist/events")
    assert response.status_code == 404
    assert response.json()["status"] == 404
    assert response.json()["type"].startswith("urn:orchestration:error:")


async def test_sse_available_under_versioned_prefix(api):
    _, run = await _launch(api, [{"title": "t"}])
    async with api.stream(
        "GET",
        f"/api/v1/workflows/runs/{run['id']}/events",
        params={"max_events": 1, "poll_interval": 0.05},
    ) as response:
        assert response.status_code == 200
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
    events = _parse_sse(body.decode())
    assert [e["event"] for e in events] == ["run.launched"]


def test_websocket_streams_events(tmp_path):
    app = build_app(_settings(tmp_path))
    with TestClient(app) as client:
        project = client.post("/projects", json={"name": "p"}).json()
        run = client.post(
            "/workflows/runs",
            json={"project_id": project["id"], "name": "r", "tasks": [{"title": "t1"}]},
        ).json()
        with client.websocket_connect(
            f"/workflows/runs/{run['id']}/ws?max_events=2&poll_interval=0.05"
        ) as ws:
            first = ws.receive_json()
            second = ws.receive_json()

    assert first["type"] == "run_event"
    assert first["event"] == "run.launched"
    assert second["event"] == "task.created"
    assert second["id"] > first["id"]
    assert first["run_id"] == run["id"]


class _FakeWebSocket:
    """Minimal stand-in exposing only the handshake attributes we read."""

    def __init__(self, query=None, headers=None):
        self.query_params = query or {}
        self.headers = headers or {}


def test_ws_read_authorization_rules(monkeypatch):
    from orchestration_server import api as api_mod
    from shared import auth_middleware as auth_mod

    # Development mode: everything is allowed so local UIs work unauthenticated.
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", False)
    assert api_mod._ws_read_authorized(_FakeWebSocket()) is True

    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", set())
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", {"write-key"})
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", {"read-key"})

    assert api_mod._ws_read_authorized(_FakeWebSocket()) is False
    assert api_mod._ws_read_authorized(_FakeWebSocket({"api_key": "nope"})) is False
    assert api_mod._ws_read_authorized(_FakeWebSocket({"api_key": "read-key"})) is True
    # A write key also carries read.
    assert api_mod._ws_read_authorized(_FakeWebSocket({"api_key": "write-key"})) is True
    # Non-browser clients may use the standard header instead of the query param.
    assert (
        api_mod._ws_read_authorized(
            _FakeWebSocket(headers={auth_mod.API_KEY_HEADER_NAME: "read-key"})
        )
        is True
    )


def test_websocket_unknown_run_fails_closed(tmp_path):
    app = build_app(_settings(tmp_path))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/workflows/runs/does-not-exist/ws"):
                pass
