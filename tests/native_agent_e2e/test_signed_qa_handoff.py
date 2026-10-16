"""Seven real HTTP+Git SDLC stages gated by a second service's signed QA receipt.

The provider is scripted; native worker, Git worktrees, QA subprocesses,
authenticated services, persistent databases and signed handoffs are real.
"""
from __future__ import annotations

import os
import sys

import httpx
import pytest
from sqlalchemy import select

from agent_management.trusted_fs_client import TrustedLeasedGatewayRunner
from orchestration_server.api import build_app as build_control_app
from orchestration_server.config import Settings as ControlSettings
from orchestration_server.models import TaskQaAttestation
from orchestration_server.native_http_worker import NativeHttpWorker
from quality_gates.api import build_app as build_qa_app
from quality_gates.config import Settings as QaSettings
from quality_gates.db import build_engine, build_session_factory, create_all
from shared import auth_middleware

from test_git_worktree_commit import store, git
from test_native_contract_pipeline import runtime
from test_remote_git_artifact_flow import make_gateway, worker_runner
from test_seven_stage_native_sdlc import STAGES, model_for_stages

QA_ADMIN = "trusted-independent-qa-admin"
WORKER_KEY = "native-test-worker-key"
SIGNING_KEY = "operator-qa-receipt-key-not-available-to-worker-00000001"


@pytest.fixture(autouse=True)
def strict_auth(monkeypatch):
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {WORKER_KEY})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", {QA_ADMIN})
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())


def client_for(app, key):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://service.example",
        headers={"X-API-Key": key},
    )


@pytest.mark.asyncio
async def test_seven_stage_native_sdlc_requires_real_operator_qa_evidence(
    runtime, tmp_path, monkeypatch,
):
    """Only independent QA can authorize each stage, even after API restart."""
    # Close the one-task setup fixture so the native dispatcher selects this
    # new seven-stage run instead.
    prereq = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    await runtime["orch"].submit(
        runtime["task"].id, prereq.id, runtime["agent"].id,
        {"summary": "fixture completed"},
    )

    storage, repository = store(tmp_path)
    # QA reviewer inspects a real committed source manifest, not an untracked
    # file that would be rejected by the Git worktree commit policy.
    (repository / "pyproject.toml").write_text(
        "[project]\nname='native-qa-e2e'\nversion='0.1.0'\n"
    )
    git(repository, "add", "--", "pyproject.toml")
    git(repository, "-c", "user.name=Native Test", "-c",
        "user.email=native@localhost", "commit", "-qm", "QA manifest")
    source_head = git(repository, "rev-parse", "HEAD")
    gateway = make_gateway(runtime, tmp_path, storage)
    qa_engine = build_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'independent-qa.sqlite3'}",
    )
    await create_all(qa_engine)
    qa_sf = build_session_factory(qa_engine)
    qa = build_qa_app(QaSettings(
        evidence_root=tmp_path / "qa-evidence",
        artifact_root=tmp_path / "qa-artifacts",
        qa_attestation_key=SIGNING_KEY,
    ), sf=qa_sf)
    provider = model_for_stages()
    stages = [
        {"title": name, "contract_id": runtime["task"].contract_id,
         "depends_on": [index - 1] if index else []}
        for index, name in enumerate(STAGES)
    ]

    def control():
        return build_control_app(ControlSettings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
            recover_on_startup=False, attempt_lease_enabled=True,
            attempt_lease_ttl_seconds=30, qa_attestation_key=SIGNING_KEY,
        ))

    async def authorize_qa(control_app, qa_client, task, outcome):
        assert outcome.status == "completed" and outcome.verified
        async with client_for(control_app, WORKER_KEY) as view:
            response = await view.get(
                f"/api/v1/tasks/{task['id']}/git-evidence",
            )
            assert response.status_code == 200
            evidence = response.json()
            assert len(evidence) == 1
            sha = evidence[0]["commit_sha"]
            attempt_id = evidence[0]["attempt_id"]
            assert attempt_id == outcome.attempt_id

            # Worker cannot issue or register an independent QA certificate.
            denied = await view.post(
                f"/api/v1/tasks/{task['id']}/qa-attestation", json={},
            )
            assert denied.status_code == 403
            before = await view.get(
                f"/api/v1/tasks/{task['id']}/qa-attestation",
            )
            assert before.status_code == 200
            assert before.json()["status"] == "pending"

        worktree = storage._path(task["id"], attempt_id)
        assert storage.verify_artifact(
            task["id"], attempt_id, expected_sha=sha,
            expected_paths=(f"out/{task['title']}.txt",),
        ).commit_sha == sha
        # Real independent subprocess validates the exact stage's Git output.
        script = (
            "from pathlib import Path; "
            f"assert Path('out/{task['title']}.txt').read_text() "
            f"== 'native {task['title']} artifact'"
        )
        for gate in ("tester", "reviewer", "security"):
            payload = {
                "task_id": task["id"], "workspace": str(worktree),
                "gate": gate,
                "attempt_id": attempt_id, "commit_sha": sha,
            }
            if gate == "tester":
                payload["context"] = {
                    "commands": {"unit": [sys.executable, "-c", script]},
                }
            recorded = await qa_client.post("/api/v1/runs", json=payload)
            assert recorded.status_code == 200, recorded.text
            assert recorded.json()["status"] == "passed", recorded.text

        issued = await qa_client.post(
            f"/api/v1/tasks/{task['id']}/qa-attestation",
            json={"attempt_id": attempt_id, "commit_sha": sha},
        )
        assert issued.status_code == 200, issued.text
        async with client_for(control_app, QA_ADMIN) as admin:
            admitted = await admin.post(
                f"/api/v1/tasks/{task['id']}/qa-attestation",
                json=issued.json(),
            )
            assert admitted.status_code == 200, admitted.text
            assert admitted.json()["status"] == "verified"
            readback = await admin.get(
                f"/api/v1/tasks/{task['id']}/qa-attestation",
            )
            assert readback.status_code == 200
            assert readback.json()["status"] == "verified"
            assert readback.json()["commit_sha"] == sha
            assert "signature" not in readback.json()

    async def run_half(control_app, begin, end, run_id, tasks):
        async with client_for(qa, QA_ADMIN) as qa_admin:
            async with NativeHttpWorker(
                server_url="https://control.example", api_key=WORKER_KEY,
                agent_id=runtime["agent"].id,
                leased_runner=worker_runner(runtime, gateway, provider),
                require_lease=True, lease_renew_interval_seconds=0.05,
                transport=httpx.ASGITransport(app=control_app),
            ) as worker:
                for stage in STAGES[begin:end]:
                    completed = await worker.run_once()
                    assert completed is not None
                    assert completed.task_id == tasks[stage]["id"]
                    # A JSON contract passes but independent QA has not run.
                    async with client_for(control_app, WORKER_KEY) as view:
                        state = await view.get(f"/api/v1/workflows/runs/{run_id}")
                        assert state.json()["status"] == "running"
                    assert await worker.run_once() is None
                    await authorize_qa(control_app, qa_admin, tasks[stage], completed)

    try:
        first = control()
        async with first.router.lifespan_context(first):
            async with client_for(first, QA_ADMIN) as admin:
                started = await admin.post("/api/v1/workflows/runs", json={
                    "project_id": runtime["run"].project_id,
                    "name": "QA gated native SDLC",
                    "tasks": stages, "retry_policy": {"max_attempts": 1},
                })
                assert started.status_code == 201, started.text
                run_id = started.json()["id"]
                listed = await admin.get(
                    f"/api/v1/workflows/runs/{run_id}/tasks",
                )
                tasks = {t["title"]: t for t in listed.json()["items"]}
            await run_half(first, 0, 3, run_id, tasks)

        # New orchestration app and DB connection, preserved QA/Git state.
        restarted = control()
        async with restarted.router.lifespan_context(restarted):
            await run_half(restarted, 3, 7, run_id, tasks)
            async with client_for(restarted, WORKER_KEY) as view:
                result = await view.get(f"/api/v1/workflows/runs/{run_id}")
                assert result.status_code == 200
                assert result.json()["status"] == "completed"
                assert result.json()["output_data"] == {"tasks_completed": 7}
                for task in tasks.values():
                    detail = await view.get(f"/api/v1/tasks/{task['id']}")
                    assert detail.json()["status"] == "completed"
                    assert detail.json()["attempt_count"] == 1

            async with runtime["factory"]() as session:
                receipts = (await session.scalars(
                    select(TaskQaAttestation)
                    .where(TaskQaAttestation.task_id.in_(
                        [t["id"] for t in tasks.values()]
                    ))
                )).all()
            assert len(receipts) == 7
            assert all(set(a.gate_run_ids) ==
                       {"tester", "reviewer", "security"} for a in receipts)
            assert git(repository, "rev-parse", "HEAD") == source_head
            assert len(provider.history) == 14
    finally:
        await qa_engine.dispose()
