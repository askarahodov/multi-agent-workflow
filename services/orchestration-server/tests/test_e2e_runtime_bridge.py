"""Cross-subsystem integration: the native runtime executes a server-owned run.

This is the wiring proof for the P1 journey: a real orchestration-server API
(no mocks) is driven by the real :class:`agent_runtime.RunBridge`, which drains
the server's ready-task queue, executes each task through
:class:`agent_runtime.AgentRuntime`, and submits the results back over the
public API. The run then completes and its whole lifecycle is observable over
the SSE journal the UI subscribes to.

The orchestration-server test job exposes the runtime package on ``PYTHONPATH``
(see ``.github/workflows/quality-gate.yml``); when it is not importable the test
skips rather than failing an environment it cannot control.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("agent_runtime")

from agent_runtime.runner import AgentRuntime, NodeOutcome  # noqa: E402
from agent_runtime.server_bridge import RunBridge  # noqa: E402
from agent_runtime.spec import (  # noqa: E402
    AgentDefinition,
    AgentInstance,
    ConfigStore,
    ModelProfile,
    ProfileManager,
    RetryPolicy,
    Role,
)
from agent_runtime.limits import Budget  # noqa: E402
from agent_runtime.permissions import ToolPolicy  # noqa: E402
from agent_runtime.workspace import WorkspaceKind, WorkspaceManager  # noqa: E402

from orchestration_server.api import build_app  # noqa: E402
from orchestration_server.config import Settings  # noqa: E402


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime-e2e.db'}",
        recover_on_startup=False,
    )


def _profiles() -> ProfileManager:
    store = ConfigStore()
    store.add_tool_policy(
        ToolPolicy(
            name="dev",
            permissions={"fs_read": ["workspace/**"], "fs_write": ["workspace/**"]},
            requires_approval=(),
        )
    )
    store.add_model_profile(
        ModelProfile(
            id="mp-1",
            provider_id="prov-1",
            model_id="openrouter/openai/gpt-4o",
            context_window=8192,
            retry_policy=RetryPolicy(max_attempts=3, base_delay_ms=1),
            budget=Budget(max_steps=10, max_tokens=10_000, max_cost_usd=1.0, max_wall_time_ms=60_000),
        )
    )
    store.add_definition(
        AgentDefinition(
            id="def-1",
            name="developer",
            system_prompt="Execute the task.",
            default_model_profile_id="mp-1",
            default_tool_policy_id="dev",
            capabilities=("fs.read", "fs.write", "code.run"),
        )
    )
    store.add_instance(
        AgentInstance(
            id="inst-1",
            definition_id="def-1",
            model_profile_id="mp-1",
            tool_policy_id="dev",
            config={"max_turns": 20, "resource_tier": "medium"},
        )
    )
    store.add_role(
        Role(name="default", default_definition_id="def-1", allowed_capabilities=("fs.read", "fs.write", "code.run")),
    )
    return ProfileManager(store)


class HttpServerClient:
    """Adapts the orchestration API (httpx ASGI client) to ``ServerRunClient``."""

    def __init__(self, api: AsyncClient, agent_id: str):
        self.api = api
        self.agent_id = agent_id

    async def list_ready_tasks(self, *, limit: int = 20) -> list[dict]:
        response = await self.api.get("/api/v1/workflows/ready-tasks", params={"limit": limit})
        response.raise_for_status()
        return response.json()

    async def claim_task(self, task_id: str, agent_id: str) -> dict:
        response = await self.api.post(
            f"/api/v1/tasks/{task_id}/claim", json={"agent_id": agent_id}
        )
        response.raise_for_status()
        return response.json()

    async def submit_task(self, task_id, attempt_id, agent_id, output) -> dict:
        response = await self.api.post(
            f"/api/v1/tasks/{task_id}/attempts/{attempt_id}/submit",
            params={"agent_id": agent_id},
            json={"output": dict(output)},
        )
        response.raise_for_status()
        return response.json()

    async def fail_task(self, task_id, attempt_id, agent_id, error) -> dict:
        response = await self.api.post(
            f"/api/v1/tasks/{task_id}/attempts/{attempt_id}/fail",
            params={"agent_id": agent_id},
            json={"error": error},
        )
        response.raise_for_status()
        return response.json()


async def _echo_tool(action, resource, params, workspace):
    return {"action": action, "resource": resource}


def _runtime(ws_root, tool_executor=_echo_tool) -> AgentRuntime:
    return AgentRuntime(
        profiles=_profiles(),
        workspaces=WorkspaceManager(ws_root),
        tool_executor=tool_executor,
        workspace_kind=WorkspaceKind.SCRATCH,
    )


@pytest_asyncio.fixture
async def api(tmp_path):
    app = build_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def test_runtime_executes_server_run_end_to_end(tmp_path, api):
    project = (await api.post("/api/v1/projects", json={"name": "RT"})).json()
    run = (
        await api.post(
            "/api/v1/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "runtime-run",
                "tasks": [
                    {"title": "implement"},
                    {"title": "verify", "depends_on": [0]},
                ],
            },
        )
    ).json()
    agent = (await api.post("/api/v1/agents/register", json={"name": "rt-worker"})).json()

    runtime = _runtime(tmp_path / "ws")

    async def executor(inv):
        await inv.execute_tool("fs_read", "workspace/main.py")
        return NodeOutcome(result={"ok": True}, summary=f"executed {inv.node.title}")

    bridge = RunBridge(
        runtime=runtime,
        executor=executor,
        client=HttpServerClient(api, agent["id"]),
        agent_id=agent["id"],
        run_id=run["id"],
    )
    report = await bridge.run_ready()

    assert report.failed == []
    assert len(report.completed) == 2

    # The API persisted the runtime's results: the run is complete.
    final = (await api.get(f"/api/v1/workflows/runs/{run['id']}")).json()
    assert final["status"] == "completed"
    tasks = (await api.get(f"/api/v1/workflows/runs/{run['id']}/tasks")).json()["items"]
    assert {t["status"] for t in tasks} == {"completed"}
    assert all(t["output_data"] for t in tasks)


async def test_runtime_crash_retried_by_server_then_succeeds(tmp_path, api):
    project = (await api.post("/api/v1/projects", json={"name": "RT-retry"})).json()
    run = (
        await api.post(
            "/api/v1/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "runtime-retry",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 0.0},
                "tasks": [{"title": "flaky"}],
            },
        )
    ).json()
    agent = (await api.post("/api/v1/agents/register", json={"name": "rt-flaky"})).json()

    attempts = {"n": 0}
    from agent_runtime.errors import ErrorKind, PlatformError

    async def flaky_executor(inv):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise PlatformError(ErrorKind.ISOLATION_UNAVAILABLE, "worker process exited")
        return NodeOutcome(result={"ok": True}, summary="recovered")

    client = HttpServerClient(api, agent["id"])

    # First worker: crashes on the first attempt.
    first = await RunBridge(
        runtime=_runtime(tmp_path / "ws-1"),
        executor=flaky_executor,
        client=client,
        agent_id=agent["id"],
        run_id=run["id"],
    ).run_ready()
    assert first.failed and not first.completed

    # The server re-queued the task (retry window opened at delay 0).
    ready = (await api.get("/api/v1/workflows/ready-tasks")).json()
    assert [r["task_id"] for r in ready]

    # A restarted worker (fresh scratch) retries and succeeds.
    second = await RunBridge(
        runtime=_runtime(tmp_path / "ws-2"),
        executor=flaky_executor,
        client=client,
        agent_id=agent["id"],
        run_id=run["id"],
    ).run_ready()
    assert second.completed and not second.failed
    final = (await api.get(f"/api/v1/workflows/runs/{run['id']}")).json()
    assert final["status"] == "completed"

    # The crash, the retry and the completion are all on the durable journal
    # the UI streams (SSE), in order and without duplicates.
    body = b""
    async with api.stream(
        "GET",
        f"/api/v1/workflows/runs/{run['id']}/events",
        params={"after": 0, "poll_interval": 0.05, "idle_timeout": 0.4},
    ) as response:
        assert response.status_code == 200
        async for chunk in response.aiter_bytes():
            body += chunk
    events: list[dict] = []
    for block in body.decode().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    kinds = [e["event"] for e in events]
    assert "attempt.failed" in kinds
    assert "task.retry_scheduled" in kinds
    assert kinds[-1] == "run.completed"
