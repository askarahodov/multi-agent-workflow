"""P0 #11: native 7-stage SDLC across API, model tools, Git and a real restart.

This is a deterministic OFFLINE integration test, not live OpenRouter, human
review or server-side Git attestation. Every stage executes real Git and SQLite.
"""
from __future__ import annotations

import os

import httpx
import pytest

from agent_management.trusted_fs_client import TrustedLeasedGatewayRunner
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.native_http_worker import NativeHttpWorker
from shared import auth_middleware

from test_git_worktree_commit import store, git
from test_native_contract_pipeline import runtime, ScriptedStream, tool, usage, done
from test_remote_git_artifact_flow import make_gateway, worker_runner


STAGES = (
    "research", "architecture", "implementation", "tests",
    "review", "security", "release-prep",
)
KEY = "native-test-worker-key"


@pytest.fixture(autouse=True)
def native_auth(monkeypatch):
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {KEY})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", set())
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())


def model_for_stages():
    events = []
    for stage in STAGES:
        events.extend((
            [tool("write_file", f"write-{stage}",
                  path=f"out/{stage}.txt", content=f"native {stage} artifact"),
             usage(), done("tool_calls")],
            [{"type": "text_delta",
              "text": '{"summary":"%s done"}' % stage},
             usage(), done("stop")],
        ))
    return ScriptedStream(*events)


def control_app(tmp_path):
    return build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
        attempt_lease_ttl_seconds=30,
    ))


def api_client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://control.example",
        headers={"X-API-Key": KEY},
    )


def make_worker(runtime, control, gateway, provider):
    return NativeHttpWorker(
        server_url="https://control.example", api_key=KEY,
        agent_id=runtime["agent"].id,
        leased_runner=worker_runner(runtime, gateway, provider),
        require_lease=True, lease_renew_interval_seconds=0.05,
        transport=httpx.ASGITransport(app=control),
    )


@pytest.mark.asyncio
async def test_api_launched_seven_stage_native_sdlc_survives_restart_with_git(
    runtime, tmp_path,
):
    """Real HTTP control and gateway; scripted provider only. No Hermes."""
    # The reusable cross-service fixture has a one-task run. Complete it
    # before creating our run so dispatcher discovery cannot pick it first.
    previous = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    await runtime["orch"].submit(
        runtime["task"].id, previous.id, runtime["agent"].id,
        {"summary": "fixture prerequisite complete"},
    )

    storage, repository = store(tmp_path)
    baseline = git(repository, "rev-parse", "HEAD")
    gateway = make_gateway(runtime, tmp_path, storage)
    scripted = model_for_stages()
    specs = [
        {
            "title": stage, "contract_id": runtime["task"].contract_id,
            "description": "Build the approved project with native tools",
            "depends_on": [idx - 1] if idx else [],
        }
        for idx, stage in enumerate(STAGES)
    ]
    control = control_app(tmp_path)
    async with control.router.lifespan_context(control):
        async with api_client(control) as client:
            # A leased SDLC stage without a contract must never start.
            denied = await client.post("/api/v1/workflows/runs", json={
                "project_id": runtime["run"].project_id,
                "name": "unverified",
                "tasks": [{"title": "unverified"}],
            })
            assert denied.status_code == 422

            started = await client.post("/api/v1/workflows/runs", json={
                "project_id": runtime["run"].project_id,
                "name": "Native SDLC seven stages",
                "tasks": specs, "retry_policy": {"max_attempts": 1},
            })
            assert started.status_code == 201, started.text
            run_id = started.json()["id"]
            tasks_response = await client.get(
                f"/api/v1/workflows/runs/{run_id}/tasks",
            )
            assert tasks_response.status_code == 200
            tasks = {x["title"]: x for x in tasks_response.json()["items"]}
            assert set(tasks) == set(STAGES)

            # Later stages cannot be claimed while the prerequisites are
            # still pending, even if a caller knows their task IDs.
            premature = await client.post(
                f"/api/v1/tasks/{tasks['release-prep']['id']}/claim",
                json={"agent_id": runtime["agent"].id},
            )
            assert premature.status_code == 409

        async with make_worker(runtime, control, gateway, scripted) as worker:
            first = await worker.run_batch(max_attempts=3)
        assert not first.stopped_on_failure
        assert len(first.attempts) == 3
        assert all(a.verified for a in first.attempts)
        assert [x.task_id for x in first.attempts] == [
            tasks[stage]["id"] for stage in STAGES[:3]
        ]
        assert (await runtime["queries"].get_run(run_id)).status == "running"
        assert (await runtime["queries"].get_task(
            tasks["tests"]["id"],
        )).status == "pending"

    # Simulate orchestration-server shutdown/startup with a new app, engine
    # and SQL connection. Gateway and durable Git/ledger survive the restart.
    restarted = control_app(tmp_path)
    async with restarted.router.lifespan_context(restarted):
        async with api_client(restarted) as client:
            persisted = await client.get(f"/api/v1/workflows/runs/{run_id}")
            assert persisted.status_code == 200
            assert persisted.json()["status"] == "running"

        async with make_worker(runtime, restarted, gateway, scripted) as worker:
            second = await worker.run_batch(max_attempts=4)
            assert not second.stopped_on_failure
            assert len(second.attempts) == 4
            assert all(a.verified for a in second.attempts)
            assert await worker.run_once() is None
        assert [x.task_id for x in second.attempts] == [
            tasks[stage]["id"] for stage in STAGES[3:]
        ]

        async with api_client(restarted) as client:
            finished = await client.get(f"/api/v1/workflows/runs/{run_id}")
            assert finished.status_code == 200
            assert finished.json()["status"] == "completed"
            assert finished.json()["output_data"] == {"tasks_completed": 7}
            for stage in STAGES:
                task = tasks[stage]
                detail = await client.get(f"/api/v1/tasks/{task['id']}")
                assert detail.status_code == 200
                actual = detail.json()
                assert actual["status"] == "completed"
                assert actual["attempt_count"] == 1
                assert actual["output_data"] == {"summary": f"{stage} done"}
                index = STAGES.index(stage)
                if index:
                    upstream = actual["input_data"]["_maw_upstream"]
                    assert upstream[-1]["task_id"] == tasks[STAGES[index - 1]]["id"]
                    assert upstream[-1]["summary"] == f"{STAGES[index - 1]} done"

                evidence_response = await client.get(
                    f"/api/v1/tasks/{task['id']}/git-evidence",
                )
                assert evidence_response.status_code == 200
                evidence = evidence_response.json()
                assert len(evidence) == 1
                entry = evidence[0]
                assert entry["provenance"] == "worker_reported"
                assert entry["changed_paths"] == [f"out/{stage}.txt"]
                ref = f"refs/maw/attempts/{task['id']}-{entry['attempt_id']}"
                assert entry["commit_sha"] == git(repository, "rev-parse", ref)
                assert storage.verify_artifact(
                    task["id"], entry["attempt_id"],
                    expected_sha=entry["commit_sha"],
                    expected_paths=(f"out/{stage}.txt",),
                ).commit_sha == entry["commit_sha"]
                assert git(storage._path(task["id"], entry["attempt_id"]),
                           "show", f"HEAD:out/{stage}.txt") == (
                               f"native {stage} artifact"
                           )

    assert git(repository, "rev-parse", "HEAD") == baseline
    assert len(scripted.history) == len(STAGES) * 2
    # Bounded model messages contain verified handoff summaries, never a
    # trusted lease or Git command. A model cannot self-mark a stage complete.
    for idx, stage in enumerate(STAGES):
        message = scripted.history[2 * idx]["messages"][-1]["content"]
        if idx:
            assert f"{STAGES[idx - 1]} done" in message
        assert all(
            t["function"]["name"] != "git_commit"
            for t in scripted.history[2 * idx]["tools"]
        )
    for idx, stage in enumerate(STAGES):
        attempt_id = (first.attempts + second.attempts)[idx].attempt_id
        scope = f"run-{run_id}/attempt-{attempt_id}"
        assert runtime["ledger"].state(scope, f"write-{stage}") == "SUCCEEDED"
        assert runtime["ledger"].state(scope, "git-commit-v1") == "SUCCEEDED"
