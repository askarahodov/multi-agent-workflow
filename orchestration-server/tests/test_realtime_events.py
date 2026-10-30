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


# ---------------------------------------------------------------------------
# B1 regression: SSE frames must reach a browser's default ``message`` channel
# ---------------------------------------------------------------------------


def _browser_dispatch(text: str) -> list[dict]:
    """Dispatch an SSE body exactly as a browser ``EventSource`` would.

    Per the SSE spec a frame may name an event type with ``event: <type>``;
    such a frame is delivered *only* to listeners registered for that exact
    type and never to the default ``onmessage`` handler. This helper returns
    the events a client listening on the default ``message`` channel receives.
    """
    delivered: list[dict] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith(":"):
                continue  # comment / keep-alive
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_type = value
            elif field == "data":
                data_lines.append(value)
        if not data_lines:
            continue
        if event_type == "message":
            delivered.append(json.loads("\n".join(data_lines)))
    return delivered


async def test_sse_frames_are_dispatched_on_the_default_message_channel(api):
    """B1: a browser listening on ``onmessage`` must receive every event.

    Before the fix ``format_sse`` emitted ``event: <name>``; browsers dispatch
    such a frame only to same-named listeners, so the default ``message``
    channel (what the client uses) received nothing at all.
    """
    _, run = await _launch(api, [{"title": "t1"}])
    text = await _read_stream(api, run["id"], after=0, max_events=2, poll_interval=0.05)

    assert [e["event"] for e in _browser_dispatch(text)] == ["run.launched", "task.created"]
    # No frame may carry a named event type.
    assert not any(line.startswith("event:") for line in text.splitlines())


def test_format_sse_uses_the_default_message_type():
    from orchestration_server.events import format_sse

    frame = format_sse({"id": 7, "event": "task.completed", "run_id": "r"})
    assert frame.startswith("id: 7\n")
    assert "\nevent:" not in frame
    assert _browser_dispatch(frame) == [{"id": 7, "event": "task.completed", "run_id": "r"}]


def test_sse_accepts_api_key_query_param_when_auth_enabled(monkeypatch, tmp_path):
    """B1 auth: a browser ``EventSource`` cannot set headers.

    The SSE route must accept the same ``api_key`` query fallback the
    WebSocket handshake uses, or the fallback 401s under ``AUTH_ENABLED``.
    """
    from fastapi.testclient import TestClient

    from shared import auth_middleware as auth_mod

    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", {"adm"})
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", set())
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", {"rea"})

    app = build_app(_settings(tmp_path))
    admin = {"X-API-Key": "adm"}
    with TestClient(app) as client:
        project = client.post("/projects", json={"name": "p"}, headers=admin).json()
        run = client.post(
            "/workflows/runs",
            json={"project_id": project["id"], "name": "r", "tasks": [{"title": "t"}]},
            headers=admin,
        ).json()
        url = f"/workflows/runs/{run['id']}/events"
        params = {"max_events": 1, "poll_interval": 0.05}

        # No key at all is still rejected.
        assert client.get(url, params=params).status_code == 401
        # Header form (non-browser clients).
        header = client.get(url, params=params, headers={"X-API-Key": "rea"})
        assert header.status_code == 200
        # Browser EventSource form: query param, no headers.
        query = client.get(url, params={**params, "api_key": "rea"})
        assert query.status_code == 200
        assert query.headers["content-type"].startswith("text/event-stream")
        assert _browser_dispatch(query.text)
