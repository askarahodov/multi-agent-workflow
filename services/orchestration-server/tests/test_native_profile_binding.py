"""Real SQLite/ASGI integration: native profiles cannot grant arbitrary provider rights."""
from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from conftest import seed_workflow

from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.models import Task, WorkflowRun
from orchestration_server.native_http_worker import NativeHttpWorker, RemoteWorkerError
from orchestration_server.native_profile_binding import (
    ProfileBindingError, TrustedProfileBinding, binding_from_env, task_matches_binding,
)

REFS = {
    "agent_definition_id": "11111111-1111-4111-8111-111111111111",
    "model_profile_id": "22222222-2222-4222-8222-222222222222",
    "tool_policy_id": "33333333-3333-4333-8333-333333333333",
}
BINDING = TrustedProfileBinding(*REFS.values())


@asynccontextmanager
async def worker(harness, agent_id, *, binding=None, leased=False, runner):
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=leased, attempt_lease_ttl_seconds=5,
    ))
    async with app.router.lifespan_context(app):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="worker-test-key",
            agent_id=agent_id, transport=httpx.ASGITransport(app=app),
            runner=None if leased else runner,
            leased_runner=runner if leased else None,
            require_lease=leased, profile_binding=binding,
        ) as client:
            yield client


def test_three_explicit_ids_required_and_redacted():
    env = {
        "MAW_NATIVE_PROFILE_AGENT_ID": REFS["agent_definition_id"],
        "MAW_NATIVE_PROFILE_MODEL_ID": REFS["model_profile_id"],
        "MAW_NATIVE_PROFILE_POLICY_ID": REFS["tool_policy_id"],
    }
    assert binding_from_env({}) is None
    assert binding_from_env(env) == BINDING
    assert "11111111" not in repr(BINDING)
    for key in env:
        with pytest.raises(ProfileBindingError, match="all three"):
            binding_from_env({k: v for k, v in env.items() if k != key})
    with pytest.raises(ProfileBindingError, match="valid UUIDs"):
        binding_from_env({**env, "MAW_NATIVE_PROFILE_POLICY_ID": "invalid"})


def test_published_refs_require_trusted_exact_match_and_never_grant_access():
    task = {"input_data": {"workflow_node_id": "a", "workflow_agent_reference": dict(REFS)}}
    assert task_matches_binding(task, BINDING, published=True)
    assert not task_matches_binding(task, replace(BINDING, tool_policy_id="44444444-4444-4444-8444-444444444444"), published=True)
    with pytest.raises(ProfileBindingError, match="operator-bound"):
        task_matches_binding(task, None, published=True)
    assert task_matches_binding({"input_data": None}, None)
    assert not task_matches_binding({"input_data": None}, BINDING)
    with pytest.raises(ProfileBindingError, match="lacks"):
        task_matches_binding({"input_data": {}}, BINDING, published=True)


@pytest.mark.parametrize("metadata", [
    {"workflow_agent_reference": {"model_profile_id": REFS["model_profile_id"]}},
    {"workflow_agent_reference": {**REFS, "extra": "untrusted"}},
    {"workflow_agent_reference": {**REFS, "tool_policy_id": []}},
    {"workflow_node_id": "n", "workflow_agent_reference": "arbitrary"},
    ["not", "a", "mapping"],
])
def test_invalid_published_metadata_rejected(metadata):
    with pytest.raises(ProfileBindingError):
        task_matches_binding({"input_data": metadata}, BINDING, published=True)


async def seed_profile_task(harness):
    _project, _contract, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    task_id = tasks[0].id
    async with harness.sf() as session:
        task = await session.get(Task, task_id)
        task.input_data = {
            "workflow_node_id": "agent-1", "workflow_agent_reference": dict(REFS),
        }
        run_record = await session.get(WorkflowRun, run.id)
        run_record.input_data = {"_workflow_version_id": "published-version-test"}
        await session.commit()
    return agent.id, task_id


async def test_real_sqlite_lease_executes_only_exact_profile(harness):
    agent_id, task_id = await seed_profile_task(harness)
    calls = []

    async def run(task, attempt, lease):
        calls.append(task["id"])
        return '{"summary":"verified by fixed profile"}'

    async with worker(harness, agent_id, binding=BINDING, leased=True, runner=run) as client:
        result = await client.run_once()
        assert result is not None and result.verified and result.task_id == task_id
    assert calls == [task_id]
    assert (await harness.queries.get_task(task_id)).status == "completed"


async def test_unbound_or_foreign_profile_never_claims_or_calls_model(harness):
    agent_id, task_id = await seed_profile_task(harness)
    calls = []

    async def forbidden(*args):
        calls.append(True)
        raise AssertionError("Mismatched published task must not invoke provider")

    async with worker(harness, agent_id, runner=forbidden) as client:
        with pytest.raises(RemoteWorkerError, match="trusted profile binding"):
            await client.run_once()
    assert (await harness.queries.get_task(task_id)).attempt_count == 0
    other = replace(BINDING, model_profile_id="55555555-5555-4555-8555-555555555555")
    async with worker(harness, agent_id, binding=other, runner=forbidden) as client:
        assert await client.run_once() is None
    assert (await harness.queries.get_task(task_id)).attempt_count == 0
    assert calls == []


async def test_claimed_profile_drift_is_quarantined_without_provider_io(harness):
    agent_id, task_id = await seed_profile_task(harness)
    calls = []

    async def forbidden(*args):
        calls.append(True)
        raise AssertionError("Changed metadata must never invoke model")

    async with worker(harness, agent_id, binding=BINDING, leased=True, runner=forbidden) as client:
        original = client._request

        async def mutate_after_claim(method, path, **kwargs):
            result = await original(method, path, **kwargs)
            if method == "POST" and path.endswith("/claim"):
                async with harness.sf() as session:
                    task = await session.get(Task, task_id)
                    task.input_data = {
                        "workflow_node_id": "agent-1",
                        "workflow_agent_reference": {
                            **REFS, "tool_policy_id": "66666666-6666-4666-8666-666666666666",
                        },
                    }
                    await session.commit()
            return result

        client._request = mutate_after_claim
        with pytest.raises(RemoteWorkerError, match="reconciliation"):
            await client.run_once()
    assert calls == []
    current = await harness.queries.get_task(task_id)
    assert current.attempt_count == 1 and current.status == "in_progress"
