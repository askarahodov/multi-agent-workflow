"""End-to-end user journey over the real API + runtime event transports.

These tests exercise the *whole* user flow the web UI drives, against the real
FastAPI app (no mocks), and assert on the observable results of each stage:

    create project -> define tasks -> launch run -> delegate (claim by agent)
    -> execute (submit) -> see results (qa-attestation, git-evidence)
    -> watch the run over the live WebSocket event stream

Two scenarios are covered, per the P1 acceptance criteria:

* **happy path** — a dependency-ordered run completes from claim to
  ``run.completed``, with every transition observable over the WebSocket;
* **error recovery** — an agent crash (``attempt.failed``) is retried to
  success, and a client that loses its socket reconnects and resumes from its
  cursor without duplicating or missing events.
"""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from orchestration_server.api import build_app
from orchestration_server.config import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'journey.db'}",
        recover_on_startup=False,
    )


def _sse_events(client: TestClient, run_id: str, **params) -> list[dict]:
    """Read a finite SSE window and return the parsed ``data:`` payloads."""
    with client.stream(
        "GET", f"/api/v1/workflows/runs/{run_id}/events", params=params
    ) as response:
        assert response.status_code == 200, response.status_code
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b""
        for chunk in response.iter_bytes():
            body += chunk
    events: list[dict] = []
    for block in body.decode().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


def _register_agent(client: TestClient, name: str = "worker-1") -> dict:
    response = client.post("/api/v1/agents/register", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _claim_and_submit(client: TestClient, task_id: str, agent_id: str, output: dict) -> dict:
    claim = client.post(f"/api/v1/tasks/{task_id}/claim", json={"agent_id": agent_id})
    assert claim.status_code == 201, claim.text
    attempt = claim.json()
    submit = client.post(
        f"/api/v1/tasks/{task_id}/attempts/{attempt['id']}/submit",
        params={"agent_id": agent_id},
        json={"output": output},
    )
    assert submit.status_code == 200, submit.text
    return submit.json()


def test_happy_path_full_journey_and_websocket(tmp_path):
    app = build_app(_settings(tmp_path))
    with TestClient(app) as client:
        # 1. create project
        project = client.post(
            "/api/v1/projects", json={"name": "Journey", "description": "e2e"}
        ).json()

        # 2. define tasks (t2 depends on t1)
        run = client.post(
            "/api/v1/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "run-1",
                "tasks": [
                    {"title": "implement", "node_id": "impl"},
                    {"title": "test", "node_id": "test", "depends_on": [0]},
                ],
            },
        ).json()
        assert run["status"] in {"pending", "running"}

        # 3. delegate: only the first task is claimable (server-owned ordering)
        ready = client.get("/api/v1/workflows/ready-tasks").json()
        ready_ids = [r["task_id"] for r in ready]
        tasks = client.get(f"/api/v1/workflows/runs/{run['id']}/tasks").json()["items"]
        by_node = {t["node_id"]: t for t in tasks}
        assert ready_ids == [by_node["impl"]["id"]], ready

        agent = _register_agent(client)

        # 4. execute task 1, then task 2 becomes ready (server-owned ordering)
        _claim_and_submit(client, by_node["impl"]["id"], agent["id"], {"summary": "impl"})
        second_ready = client.get("/api/v1/workflows/ready-tasks").json()
        assert [r["task_id"] for r in second_ready] == [by_node["test"]["id"]]
        _claim_and_submit(client, by_node["test"]["id"], agent["id"], {"summary": "test"})

        # 5. watch the run over the live WebSocket: every transition is
        #    replayed in order and the terminal event is `run.completed`.
        seen: list[str] = []
        with client.websocket_connect(
            f"/api/v1/workflows/runs/{run['id']}/ws?after=0&poll_interval=0.05"
        ) as ws:
            for _ in range(30):
                frame = ws.receive_json()
                if frame["type"] == "ping":
                    continue
                seen.append(frame["event"])
                if frame["event"] in {"run.completed", "run.failed"}:
                    break
        assert seen[0] == "run.launched", seen
        assert "task.claimed" in seen
        assert "task.completed" in seen
        assert seen[-1] == "run.completed", seen

        # 6. results: the run is terminal and every task completed
        final = client.get(f"/api/v1/workflows/runs/{run['id']}").json()
        assert final["status"] == "completed"
        final_tasks = client.get(f"/api/v1/workflows/runs/{run['id']}/tasks").json()["items"]
        assert {t["status"] for t in final_tasks} == {"completed"}

        # 7. independent QA surface is reachable per task (test/review/security)
        qa = client.get(f"/api/v1/tasks/{by_node['impl']['id']}/qa-attestation").json()
        assert qa["status"] in {"disabled", "pending", "verified"}
        evidence = client.get(f"/api/v1/tasks/{by_node['impl']['id']}/git-evidence").json()
        assert isinstance(evidence, list)

        # 8. the durable SSE journal replays the whole ordered run, no duplicates
        replay = _sse_events(client, run["id"], after=0, poll_interval=0.05, idle_timeout=0.4)
        kinds = [e["event"] for e in replay]
        assert kinds[0] == "run.launched"
        assert kinds[-1] == "run.completed"
        ids = [e["id"] for e in replay]
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))


def test_error_recovery_agent_crash_retry_and_socket_resume(tmp_path):
    app = build_app(_settings(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Recovery"}).json()
        run = client.post(
            "/api/v1/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "run-crash",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 0.0},
                "tasks": [{"title": "flaky"}],
            },
        ).json()
        agent = _register_agent(client, "worker-crash")
        task = client.get(f"/api/v1/workflows/runs/{run['id']}/tasks").json()["items"][0]

        # First attempt: the agent crashes -> attempt.failed + retry scheduled.
        claim = client.post(
            f"/api/v1/tasks/{task['id']}/claim", json={"agent_id": agent["id"]}
        ).json()
        failure = client.post(
            f"/api/v1/tasks/{task['id']}/attempts/{claim['id']}/fail",
            params={"agent_id": agent["id"]},
            json={"error": "segfault: worker process exited"},
        )
        assert failure.status_code == 200, failure.text
        assert failure.json()["status"] == "failed"

        # A client that was streaming from the start sees the crash + retry.
        observed = _sse_events(
            client, run["id"], after=0, poll_interval=0.05, idle_timeout=0.4
        )
        kinds = [e["event"] for e in observed]
        assert "attempt.failed" in kinds, kinds
        assert "task.retry_scheduled" in kinds, kinds
        cursor = observed[-1]["id"]

        # The task is retryable: it is claimable again.
        ready = client.get("/api/v1/workflows/ready-tasks").json()
        assert [r["task_id"] for r in ready] == [task["id"]]

        # Second attempt succeeds -> the run completes.
        _claim_and_submit(client, task["id"], agent["id"], {"summary": "recovered"})
        final = client.get(f"/api/v1/workflows/runs/{run['id']}").json()
        assert final["status"] == "completed"

        # Network blip: resuming from the cursor delivers only *new* events.
        resumed = _sse_events(
            client, run["id"], after=cursor, poll_interval=0.05, idle_timeout=0.4
        )
        resumed_ids = [e["id"] for e in resumed]
        assert resumed_ids == [i for i in resumed_ids if i > cursor]
        assert [e["event"] for e in resumed][-1] == "run.completed"

        # Reconnecting from 0 never duplicates an id.
        full = _sse_events(client, run["id"], after=0, poll_interval=0.05, idle_timeout=0.4)
        full_ids = [e["id"] for e in full]
        assert len(full_ids) == len(set(full_ids))


def test_websocket_unknown_run_fails_closed(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    app = build_app(_settings(tmp_path))
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/api/v1/workflows/runs/missing/ws"):
                raise AssertionError("unknown run must not open a stream")
        except WebSocketDisconnect:
            pass
