"""Real SQLite/ASGI integration: native profiles cannot grant arbitrary provider rights."""
from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
import json
from shared import auth_middleware
from orchestration_server.native_claim_policy import credential_digest
from conftest import seed_workflow

from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.models import Task, WorkflowRun
from orchestration_server.native_http_worker import NativeHttpWorker, RemoteWorkerError
from orchestration_server.native_profile_binding import (
    ProfileBindingError, TrustedProfileBinding, TrustedProfileRevision, binding_from_env, task_matches_binding,
)

REFS = {
    "agent_definition_id": "11111111-1111-4111-8111-111111111111",
    "model_profile_id": "22222222-2222-4222-8222-222222222222",
    "tool_policy_id": "33333333-3333-4333-8333-333333333333",
}
BINDING = TrustedProfileBinding(*REFS.values())


@asynccontextmanager
async def worker(harness, agent_id, *, binding=None, revision=None, leased=False, runner, policy_file=None, api_key='worker-test-key'):
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=leased, attempt_lease_ttl_seconds=5,
        native_claim_policy_file=policy_file,
    ))
    async with app.router.lifespan_context(app):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key=api_key,
            agent_id=agent_id, transport=httpx.ASGITransport(app=app),
            runner=None if leased else runner,
            leased_runner=runner if leased else None,
            require_lease=leased, profile_binding=binding, profile_revision=revision,
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
        with pytest.raises(RemoteWorkerError, match="leased, operator-bound"):
            await client.run_once()
    assert (await harness.queries.get_task(task_id)).attempt_count == 0
    other = replace(BINDING, model_profile_id="55555555-5555-4555-8555-555555555555")
    async with worker(harness, agent_id, binding=other, leased=True, runner=forbidden) as client:
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


async def test_published_graph_refuses_classic_worker_even_when_profile_matches(harness):
    agent_id, task_id = await seed_profile_task(harness)
    calls = []

    async def forbidden(*args):
        calls.append(True)
        raise AssertionError("Unleased published execution must never reach provider")

    async with worker(harness, agent_id, binding=BINDING, leased=False, runner=forbidden) as client:
        with pytest.raises(RemoteWorkerError, match="leased, operator-bound"):
            await client.run_once()
    assert calls == []
    assert (await harness.queries.get_task(task_id)).attempt_count == 0


async def test_published_graph_refuses_unbound_lease_before_any_claim(harness):
    agent_id, task_id = await seed_profile_task(harness)
    calls = []

    async def forbidden(*args):
        calls.append(True)
        raise AssertionError("Unbound leased execution must never reach provider")

    async with worker(harness, agent_id, binding=None, leased=True, runner=forbidden) as client:
        with pytest.raises(RemoteWorkerError, match="leased, operator-bound"):
            await client.run_once()
    assert calls == []
    assert (await harness.queries.get_task(task_id)).attempt_count == 0


PIN = {
    "agent_role": "developer", "agent_definition_version": 2,
    "model_profile_version": 3, "tool_policy_version": 4,
    "provider_id": "44444444-4444-4444-8444-444444444444", "provider_version": 5,
}
REVISION = TrustedProfileRevision.from_mapping(PIN)


@pytest.mark.parametrize("field,value", [
    ("agent_role", "reviewer"), ("agent_definition_version", 8),
    ("model_profile_version", 8), ("tool_policy_version", 8),
    ("provider_id", "55555555-5555-4555-8555-555555555555"), ("provider_version", 8),
])
def test_every_pinned_field_must_match_trusted_snapshot(field, value):
    task = {"input_data": {"workflow_agent_reference": {**REFS, "profile_revision": PIN}}}
    assert task_matches_binding(task, BINDING, published=True, revision=REVISION)
    assert not task_matches_binding(task, BINDING, published=True)
    assert not task_matches_binding(task, BINDING, published=True,
                                    revision=replace(REVISION, **{field: value}))


@pytest.mark.parametrize("pin", [
    None, {}, {**PIN, "agent_role": "Reviewer"}, {**PIN, "provider_version": True},
    {**PIN, "tool_policy_version": 0}, {**PIN, "model_profile_version": "3"},
    {**PIN, "agent_definition_version": 2147483648}, {**PIN, "extra": "forged"},
])
def test_malformed_revision_is_not_legacy_compatibility(pin):
    task = {"input_data": {"workflow_agent_reference": {**REFS, "profile_revision": pin}}}
    with pytest.raises(ProfileBindingError):
        task_matches_binding(task, BINDING, published=True, revision=REVISION)


async def _pin_task(harness, task_id):
    async with harness.sf() as session:
        task = await session.get(Task, task_id)
        task.input_data = {"workflow_node_id": "agent-1",
                           "workflow_agent_reference": {**REFS, "profile_revision": PIN}}
        task.node_id = "agent-1"
        run = await session.get(WorkflowRun, task.workflow_run_id)
        run.input_data = {"_workflow_version_id": "77777777-7777-4777-8777-777777777777"}
        await session.commit()


SCOPED_KEY = "test-dedicated-scoped-worker-key-0123456789"
OTHER_KEY = "test-other-write-credential-0123456789"
ADMIN_KEY = "test-independent-admin-key-0123456789"


async def _assignment_document(harness, agent_id, task_id):
    task = await harness.queries.get_task(task_id)
    run = await harness.queries.get_run(task.workflow_run_id)
    return {"schema_version": 1, "workers": [{
        "agent_id": agent_id, "key_sha256": credential_digest(SCOPED_KEY),
        "profile": {**REFS, "profile_revision": PIN.copy()},
        "scopes": [{"project_id": run.project_id, "workspace_id": run.workspace_id,
                    "workflow_version_id": run.input_data["_workflow_version_id"],
                    "node_id": task.node_id}],
    }]}


def _write_policy(tmp_path, document):
    path = tmp_path / "assignment.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return str(path)


def _enable_assignment_auth(monkeypatch):
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {SCOPED_KEY, OTHER_KEY})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", {ADMIN_KEY})
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())


async def test_pinned_sqlite_task_skips_legacy_and_stale_workers_then_runs_exact_match(harness, monkeypatch, tmp_path):
    agent_id, task_id = await seed_profile_task(harness)
    await _pin_task(harness, task_id)
    _enable_assignment_auth(monkeypatch)
    path = _write_policy(tmp_path, await _assignment_document(harness, agent_id, task_id))
    calls = []

    async def run(task, attempt, lease):
        calls.append(task["id"])
        return '{"summary":"verified exact revision"}'

    for revision in (None, replace(REVISION, agent_definition_version=9)):
        async with worker(harness, agent_id, binding=BINDING, revision=revision,
                          leased=True, runner=run, policy_file=path, api_key=SCOPED_KEY) as client:
            assert await client.run_once() is None
        assert (await harness.queries.get_task(task_id)).attempt_count == 0
    assert calls == []
    async with worker(harness, agent_id, binding=BINDING, revision=REVISION,
                      leased=True, runner=run, policy_file=path, api_key=SCOPED_KEY) as client:
        result = await client.run_once()
        assert result is not None and result.verified and result.task_id == task_id
    assert calls == [task_id]


@pytest.mark.parametrize("downgrade", [True, False])
async def test_revision_drift_after_claim_prevents_provider_io(harness, downgrade, monkeypatch, tmp_path):
    agent_id, task_id = await seed_profile_task(harness)
    await _pin_task(harness, task_id)
    _enable_assignment_auth(monkeypatch)
    path = _write_policy(tmp_path, await _assignment_document(harness, agent_id, task_id))
    calls = []

    async def forbidden(*args):
        calls.append(True)
        raise AssertionError("Changed revision must not reach provider")

    async with worker(harness, agent_id, binding=BINDING, revision=REVISION,
                      leased=True, runner=forbidden, policy_file=path, api_key=SCOPED_KEY) as client:
        original = client._request

        async def mutate_after_claim(method, path, **kwargs):
            result = await original(method, path, **kwargs)
            if method == "POST" and path.endswith("/claim"):
                async with harness.sf() as session:
                    task = await session.get(Task, task_id)
                    refs = dict(REFS)
                    if not downgrade:
                        refs["profile_revision"] = {**PIN, "tool_policy_version": 9}
                    task.input_data = {"workflow_node_id": "agent-1",
                                       "workflow_agent_reference": refs}
                    await session.commit()
            return result

        client._request = mutate_after_claim
        with pytest.raises(RemoteWorkerError, match="reconciliation"):
            await client.run_once()
    assert calls == []
    current = await harness.queries.get_task(task_id)
    assert current.attempt_count == 1 and current.status == "in_progress"


@asynccontextmanager
async def assignment_api(harness, path=None, *, leased=True):
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False,
                             attempt_lease_enabled=leased, native_claim_policy_file=path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="https://control.example") as client:
            yield client


@pytest.mark.parametrize("field,value", [
    ("project_id", "55555555-5555-4555-8555-555555555555"),
    ("workspace_id", "55555555-5555-4555-8555-555555555555"),
    ("workflow_version_id", "55555555-5555-4555-8555-555555555555"),
    ("node_id", "other-stage"), ("agent_role", "reviewer"),
    ("agent_definition_version", 9), ("model_profile_version", 9),
    ("tool_policy_version", 9), ("provider_version", 9),
    ("provider_id", "55555555-5555-4555-8555-555555555555"),
])
async def test_server_rejects_ineligible_assignment_before_claim(harness, monkeypatch, tmp_path, field, value):
    agent_id, task_id = await seed_profile_task(harness)
    await _pin_task(harness, task_id)
    _enable_assignment_auth(monkeypatch)
    document = await _assignment_document(harness, agent_id, task_id)
    row = document["workers"][0]
    target = row["scopes"][0] if field in row["scopes"][0] else row["profile"]["profile_revision"]
    target[field] = value
    path = _write_policy(tmp_path, document)
    async with assignment_api(harness, path) as client:
        result = await client.post(f"/api/v1/tasks/{task_id}/claim",
                                   headers={"X-API-Key": SCOPED_KEY}, json={"agent_id": agent_id})
        assert result.status_code == 409, result.text
        assert "lease_token" not in result.text
    current = await harness.queries.get_task(task_id)
    assert current.attempt_count == 0 and current.status == "pending"


async def test_pinned_claim_denied_without_assignment_even_in_development(harness, monkeypatch):
    agent_id, task_id = await seed_profile_task(harness)
    await _pin_task(harness, task_id)
    for enabled in (False, True):
        _enable_assignment_auth(monkeypatch)
        monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", enabled)
        async with assignment_api(harness) as client:
            result = await client.post(f"/api/v1/tasks/{task_id}/claim",
                                       headers={"X-API-Key": OTHER_KEY}, json={"agent_id": agent_id})
            assert result.status_code == 409, result.text
    assert (await harness.queries.get_task(task_id)).attempt_count == 0


async def test_assignment_key_is_not_delegation_or_approval_authority(harness, monkeypatch, tmp_path):
    agent_id, task_id = await seed_profile_task(harness)
    await _pin_task(harness, task_id)
    _enable_assignment_auth(monkeypatch)
    path = _write_policy(tmp_path, await _assignment_document(harness, agent_id, task_id))
    other = await harness.orch.register_agent("other-worker")
    task = await harness.queries.get_task(task_id)
    async with assignment_api(harness, path) as client:
        headers = {"X-API-Key": SCOPED_KEY}
        for key in (OTHER_KEY, ADMIN_KEY):
            denied = await client.post(f"/api/v1/tasks/{task_id}/claim",
                                       headers={"X-API-Key": key}, json={"agent_id": agent_id})
            assert denied.status_code == 409
        denied = await client.post(f"/api/v1/tasks/{task_id}/claim",
                                   headers=headers, json={"agent_id": other.id})
        assert denied.status_code == 409
        for prefix in ("", "/api/v1"):
            for route in ("/agents/register", "/projects", "/workflows/runs",
                          f"/tasks/{task_id}/block",
                          f"/workflows/runs/{task.workflow_run_id}/release-approval"):
                denied = await client.post(prefix + route, headers=headers, json={})
                assert denied.status_code == 403, (route, denied.text)
        # General WRITE cannot bypass assignment by the legacy block route.
        denied = await client.post(f"/api/v1/tasks/{task_id}/block",
                                   headers={"X-API-Key": OTHER_KEY}, params={"agent_id": agent_id},
                                   json={"reason": "bypass"})
        assert denied.status_code == 409
        claim = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=headers,
                                  json={"agent_id": agent_id})
        assert claim.status_code == 201, claim.text
        lease = claim.json()
        attempt = f"/api/v1/tasks/{task_id}/attempts/{lease['id']}"
        for key in (OTHER_KEY, ADMIN_KEY):
            wrong = {"X-API-Key": key, "X-Attempt-Lease": lease["lease_token"]}
            renewed = await client.post(attempt + "/lease/renew", headers=wrong,
                                        json={"agent_id": agent_id, "lease_token": lease["lease_token"]})
            assert renewed.status_code == 409
            submitted = await client.post(attempt + "/submit", headers=wrong,
                                          params={"agent_id": agent_id}, json={"output": {"summary": "forged"}})
            assert submitted.status_code == 409
            failed = await client.post(attempt + "/fail", headers=wrong,
                                       params={"agent_id": agent_id}, json={"error": "forged"})
            assert failed.status_code == 409
        correct = await client.post(attempt + "/submit",
                                    headers={**headers, "X-Attempt-Lease": lease["lease_token"]},
                                    params={"agent_id": agent_id}, json={"output": {"summary": "approved result"}})
        assert correct.status_code == 200, correct.text
    assert (await harness.queries.get_task(task_id)).status == "completed"


@pytest.mark.parametrize("mutation", ["admin", "duplicate_key", "duplicate_worker", "duplicate_scope",
                                     "invalid_version", "extra_field", "missing_write", "auth_off", "leases_off",
                                     "public_file", "duplicate_json_key", "reserved_key"])
async def test_assignment_policy_rejects_unsafe_configuration(harness, monkeypatch, tmp_path, mutation):
    agent_id, task_id = await seed_profile_task(harness)
    await _pin_task(harness, task_id)
    _enable_assignment_auth(monkeypatch)
    doc = await _assignment_document(harness, agent_id, task_id)
    from copy import deepcopy
    row = doc["workers"][0]
    if mutation == "admin":
        row["key_sha256"] = credential_digest(ADMIN_KEY)
    elif mutation == "duplicate_key":
        doc["workers"].append({**deepcopy(row), "agent_id": "55555555-5555-4555-8555-555555555555"})
    elif mutation == "duplicate_worker":
        doc["workers"].append({**deepcopy(row), "key_sha256": credential_digest(OTHER_KEY)})
    elif mutation == "duplicate_scope":
        row["scopes"].append(deepcopy(row["scopes"][0]))
    elif mutation == "invalid_version":
        doc["schema_version"] = True
    elif mutation == "extra_field":
        row["delegate"] = True
    elif mutation == "missing_write":
        monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {OTHER_KEY})
    elif mutation == "auth_off":
        monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", False)
    path = _write_policy(tmp_path, doc)
    from pathlib import Path
    if mutation == "public_file":
        Path(path).chmod(0o644)
    elif mutation == "duplicate_json_key":
        Path(path).write_text('{"schema_version":1,"schema_version":1,"workers":[]}')
    with pytest.raises(ValueError):
        build_app(Settings(database_url=harness.url, recover_on_startup=False,
                           attempt_lease_enabled=mutation != "leases_off",
                           native_claim_policy_file=path,
                           qa_attestation_key=SCOPED_KEY if mutation == "reserved_key" else None))
