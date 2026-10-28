"""Seven native stages + automatic independent QA across control-server restart.

External model stream is scripted; HTTP, SQLite, Git, leases, QG subprocesses,
HMAC signing and worker-to-QA separation are real.
"""
from __future__ import annotations

import shutil
import sys

import httpx
import pytest

from agent_management.trusted_git_worktree import TrustedGitWorktreeStore
from orchestration_server.api import build_app as control_app
from orchestration_server.config import Settings as ControlSettings
from orchestration_server.native_http_worker import NativeHttpWorker
from quality_gates.api import build_app as qa_app
from quality_gates.config import Settings as QaSettings
from quality_gates.db import build_engine, build_session_factory, create_all
from quality_gates.native_qa_controller import NativeQaController, QaControllerConfig, QaControllerError, require_scoped_gate_result
from shared import auth_middleware

from test_git_worktree_commit import store, git
from test_native_contract_pipeline import runtime
from test_remote_git_artifact_flow import make_gateway, worker_runner
from test_seven_stage_native_sdlc import STAGES, model_for_stages

WORKER = "native-test-worker-key"
ORCH_ADMIN = "orchestration-qa-controller-admin-key"
QA_ADMIN = "independent-qg-controller-admin-key"
SIGNING_KEY = "qa-signed-receipt-shared-by-trusted-services-only-00001"


def client_for(app, key):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://service.example", headers={"X-API-Key": key},
    )


@pytest.mark.asyncio
async def test_native_worker_and_controller_complete_seven_qa_gated_stages(
    runtime, tmp_path, monkeypatch,
):
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {WORKER})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", {ORCH_ADMIN, QA_ADMIN})
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())

    # Close prerequisite created by the shared native-worker fixture.
    original = await runtime["orch"].claim_task(runtime["task"].id, runtime["agent"].id)
    await runtime["orch"].submit(
        runtime["task"].id, original.id, runtime["agent"].id,
        {"summary": "existing fixture completed"},
    )
    producer_store, repo = store(tmp_path)
    (repo / "pyproject.toml").write_text(
        "[project]\nname='qa-auto-e2e'\nversion='0.1.0'\n"
    )
    git(repo, "add", "--", "pyproject.toml")
    git(repo, "-c", "user.name=QA Tester", "-c",
        "user.email=qa@localhost", "commit", "-qm", "QA fixture")
    source_head = git(repo, "rev-parse", "HEAD")
    qa_home = tmp_path / "private-qa-home"
    qa_home.mkdir(mode=0o700)
    qa_git = TrustedGitWorktreeStore(
        repository=repo, worktree_home=qa_home,
        git_executable=shutil.which("git"),
    )
    gateway = make_gateway(runtime, tmp_path, producer_store)
    db = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'autonomous-qa.sqlite3'}")
    await create_all(db)
    sf = build_session_factory(db)
    qa_service = qa_app(QaSettings(
        evidence_root=tmp_path / "auto-qa-evidence",
        artifact_root=tmp_path / "auto-qa-artifacts",
        qa_attestation_key=SIGNING_KEY,
    ), sf=sf)
    model = model_for_stages()
    qa_config = QaControllerConfig(
        orch_url="https://orchestration.example", orch_admin_key=ORCH_ADMIN,
        qg_url="https://quality.example", qg_admin_key=QA_ADMIN,
        test_command=(
            sys.executable, "-B", "-c",
            "from pathlib import Path; assert len(list(Path('out').glob('*.txt'))) == 1",
        ),
    )

    def control():
        return control_app(ControlSettings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
            recover_on_startup=False, attempt_lease_enabled=True,
            attempt_lease_ttl_seconds=30, qa_attestation_key=SIGNING_KEY,
        ))

    async def phase(server, begin, end, run_id, tasks):
        async with NativeHttpWorker(
            server_url="https://orchestration.example",
            api_key=WORKER, agent_id=runtime["agent"].id,
            leased_runner=worker_runner(runtime, gateway, model),
            require_lease=True, lease_renew_interval_seconds=0.05,
            transport=httpx.ASGITransport(app=server),
        ) as worker:
            async with NativeQaController(
                qa_config, git_store=qa_git,
                orchestration_transport=httpx.ASGITransport(app=server),
                qa_transport=httpx.ASGITransport(app=qa_service),
            ) as qa:
                for stage in STAGES[begin:end]:
                    result = await worker.run_once()
                    assert result and result.verified
                    assert result.task_id == tasks[stage]["id"]
                    # Contract-gated predecessor completed, QA still pending.
                    async with client_for(server, WORKER) as read:
                        state = await read.get(f"/api/v1/workflows/runs/{run_id}")
                        assert state.json()["status"] == "running"
                        blocked = await read.post(
                            f"/api/v1/tasks/{result.task_id}/qa-attestation",
                            json={},
                        )
                        assert blocked.status_code == 403
                    assert await worker.run_once() is None
                    # Controller triggers three genuine QG runs, signs receipt,
                    # and registers it under separate ADMIN credentials.
                    assert await qa.run_once() == result.task_id
                    assert await qa.run_once() is None  # durable no replay
                    async with client_for(server, WORKER) as read:
                        checked = await read.get(
                            f"/api/v1/tasks/{result.task_id}/qa-attestation"
                        )
                        assert checked.status_code == 200
                        evidence = checked.json()
                        assert evidence["status"] == "verified"
                        assert evidence["attempt_id"] == result.attempt_id
                        assert set(evidence["gate_run_ids"]) == {
                            "tester", "reviewer", "security",
                        }

    specs = [
        {"title": stage, "contract_id": runtime["task"].contract_id,
         "depends_on": [i - 1] if i else []}
        for i, stage in enumerate(STAGES)
    ]
    try:
        first = control()
        async with first.router.lifespan_context(first):
            async with client_for(first, ORCH_ADMIN) as admin:
                launch = await admin.post("/api/v1/workflows/runs", json={
                    "project_id": runtime["run"].project_id,
                    "name": "Seven stages with autonomous signed QA",
                    "tasks": specs, "retry_policy": {"max_attempts": 1},
                })
                assert launch.status_code == 201, launch.text
                run_id = launch.json()["id"]
                page = await admin.get(f"/api/v1/workflows/runs/{run_id}/tasks")
                tasks = {item["title"]: item for item in page.json()["items"]}
            await phase(first, 0, 3, run_id, tasks)

        restarted = control()
        async with restarted.router.lifespan_context(restarted):
            await phase(restarted, 3, 7, run_id, tasks)
            async with client_for(restarted, WORKER) as read:
                state = await read.get(f"/api/v1/workflows/runs/{run_id}")
                assert state.status_code == 200
                assert state.json()["status"] == "completed"
                assert state.json()["output_data"] == {"tasks_completed": 7}
            assert git(repo, "rev-parse", "HEAD") == source_head
            assert len(model.history) == 14
            assert not list(qa_home.iterdir())
    finally:
        await db.dispose()


def test_controller_denies_insecure_transport_and_key_reuse():
    with pytest.raises(ValueError, match="HTTPS"):
        QaControllerConfig(
            orch_url="http://localhost:8000", orch_admin_key="orch-admin-key",
            qg_url="https://qa.example", qg_admin_key="qg-admin-key",
            test_command=("pytest", "-q"),
        )
    with pytest.raises(ValueError, match="separate"):
        QaControllerConfig(
            orch_url="https://orch.example", orch_admin_key="same-admin-key",
            qg_url="https://qa.example", qg_admin_key="same-admin-key",
            test_command=("pytest", "-q"),
        )



def test_controller_rejects_untrusted_tls_ca(tmp_path):
    with pytest.raises(ValueError, match="absolute regular"):
        QaControllerConfig(
            orch_url="https://orchestration.example",
            orch_admin_key=ORCH_ADMIN, qg_url="https://quality.example",
            qg_admin_key=QA_ADMIN, test_command=("python", "-V"),
            orch_ca_file="ca.pem",
        )
    fake = tmp_path / "missing-ca.pem"
    with pytest.raises(ValueError, match="absolute regular"):
        QaControllerConfig(
            orch_url="https://orchestration.example",
            orch_admin_key=ORCH_ADMIN, qg_url="https://quality.example",
            qg_admin_key=QA_ADMIN, test_command=("python", "-V"),
            qg_ca_file=str(fake),
        )


@pytest.mark.parametrize("field", ["task_id", "gate", "attempt_id", "commit_sha"])
def test_scoped_gate_response_requires_exact_identity(field):
    task, attempt, sha, gate = ("task-1", "attempt-1", "a" * 40, "tester")
    result = {"status": "passed", "task_id": task, "gate": gate,
              "attempt_id": attempt, "commit_sha": sha}
    require_scoped_gate_result(result, task_id=task, attempt_id=attempt,
                               commit_sha=sha, gate=gate)
    result[field] = "other"
    with pytest.raises(QaControllerError, match="scope mismatch"):
        require_scoped_gate_result(result, task_id=task, attempt_id=attempt,
                                   commit_sha=sha, gate=gate)


def test_scoped_gate_response_rejects_missing_fields_and_failure():
    valid = dict(status="passed", task_id="task", gate="tester",
                 attempt_id="attempt", commit_sha="a" * 40)
    for missing in valid:
        altered = dict(valid)
        altered.pop(missing)
        with pytest.raises(QaControllerError):
            require_scoped_gate_result(altered, task_id="task", attempt_id="attempt",
                                       commit_sha="a" * 40, gate="tester")
