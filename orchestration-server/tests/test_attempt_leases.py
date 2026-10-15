"""Offline tests for durable opt-in attempt capability lifecycle.

No paid LLM, remote worker, or real network calls.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.attempt_leases import AttemptLeaseService
from orchestration_server.config import Settings
from orchestration_server.errors import ConflictError
from orchestration_server.models import AttemptLease


async def test_issue_once_stores_only_digest_and_renews_before_expiry(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    clock = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    svc = AttemptLeaseService(harness.sf, ttl_seconds=30, clock=lambda: clock[0])
    grant = await svc.issue(attempt.id, agent.id)

    assert len(grant.token) >= 40
    assert grant.generation == attempt.attempt_number == 1
    assert await svc.validate(attempt.id, agent.id, grant.token)
    assert not await svc.validate(attempt.id, agent.id, "invalid-not-the-secret-token")
    assert not await svc.validate(attempt.id, "wrong-agent", grant.token)

    async with harness.sf() as session:
        persisted = await session.get(AttemptLease, attempt.id)
        assert persisted.token_sha256 == hashlib.sha256(grant.token.encode()).hexdigest()
        assert grant.token != persisted.token_sha256
        assert persisted.generation == 1

    with pytest.raises(ConflictError, match="already issued"):
        await svc.issue(attempt.id, agent.id)
    clock[0] += timedelta(seconds=20)
    renewed = await svc.renew(
        attempt.id, agent.id, grant.token, task_id=tasks[0].id,
    )
    assert renewed.token == grant.token
    assert renewed.expires_at == clock[0] + timedelta(seconds=30)
    assert await svc.validate(attempt.id, agent.id, grant.token)
    with pytest.raises(ConflictError, match="this task"):
        await svc.renew(attempt.id, agent.id, grant.token, task_id="wrong-task")


async def test_expired_lease_is_never_revived(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    clock = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    svc = AttemptLeaseService(harness.sf, ttl_seconds=5, clock=lambda: clock[0])
    grant = await svc.issue(attempt.id, agent.id)
    clock[0] += timedelta(seconds=5)
    assert not await svc.validate(attempt.id, agent.id, grant.token)
    with pytest.raises(ConflictError, match="expired"):
        await svc.renew(attempt.id, agent.id, grant.token)
    with pytest.raises(ConflictError, match="already issued"):
        await svc.issue(attempt.id, agent.id)


async def test_revoked_or_terminal_lease_cannot_authorize_new_work(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    svc = AttemptLeaseService(harness.sf)
    grant = await svc.issue(attempt.id, agent.id)

    assert await svc.revoke(attempt.id)
    assert not await svc.revoke(attempt.id)
    assert not await svc.validate(attempt.id, agent.id, grant.token)
    with pytest.raises(ConflictError, match="expired"):
        await svc.renew(attempt.id, agent.id, grant.token)
    await harness.orch.submit(
        tasks[0].id, attempt.id, agent.id, {"summary": "accepted"},
    )
    assert not await svc.validate(attempt.id, agent.id, grant.token)


async def test_server_lease_api_issues_once_without_leaking_into_attempt_queries(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True, attempt_lease_ttl_seconds=60,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claimed = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )
            assert claimed.status_code == 201
            assert claimed.headers["cache-control"] == "no-store"
            body = claimed.json()
            secret = body["lease_token"]
            assert isinstance(secret, str) and len(secret) >= 40
            assert body["lease_generation"] == 1
            assert body["lease_expires_at"]

            listed = await client.get(f"/api/v1/tasks/{tasks[0].id}/attempts")
            assert listed.status_code == 200
            assert "lease_token" not in str(listed.json())
            assert secret not in str(listed.json())
            renewed = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{body['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": secret},
            )
            assert renewed.status_code == 200
            assert renewed.headers["cache-control"] == "no-store"
            assert renewed.json()["generation"] == 1
            assert "token" not in renewed.text.lower()

            incorrect = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{body['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": "x" * 48},
            )
            assert incorrect.status_code == 409
            assert secret not in incorrect.text
            wrong_task = await client.post(
                f"/api/v1/tasks/not-the-task/attempts/{body['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": secret},
            )
            assert wrong_task.status_code == 409

            revoked = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{body['id']}/lease/revoke",
            )
            assert revoked.status_code == 200
            assert revoked.json() == {"revoked": True}
            assert (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{body['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": secret},
            )).status_code == 409


async def test_lease_api_disabled_by_default_preserves_existing_claim_contract(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            res = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )
            assert res.status_code == 201
            assert res.json()["lease_token"] is None
            assert (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{res.json()['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": "x" * 48},
            )).status_code == 409


@pytest.mark.parametrize("ttl", [-1, 0, 1, 301, True, "60"])
def test_lease_ttl_fail_closed(harness, ttl):
    with pytest.raises(ValueError, match="TTL"):
        AttemptLeaseService(harness.sf, ttl_seconds=ttl)


async def test_server_rejects_terminal_mutations_without_correct_lease(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claim = (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )).json()
            task_id, attempt_id = tasks[0].id, claim["id"]
            submit_url = f"/api/v1/tasks/{task_id}/attempts/{attempt_id}/submit"
            fail_url = f"/api/v1/tasks/{task_id}/attempts/{attempt_id}/fail"
            params = {"agent_id": agent.id}
            for headers in ({}, {"X-Attempt-Lease": "x" * 43}):
                submit = await client.post(
                    submit_url, params=params, headers=headers,
                    json={"output": {"summary": "untrusted"}},
                )
                assert submit.status_code == 409
                fail = await client.post(
                    fail_url, params=params, headers=headers,
                    json={"error": "not authorized"},
                )
                assert fail.status_code == 409
                assert "lease_token" not in submit.text

            assert (await harness.queries.get_task(task_id)).status == "in_progress"
            assert (await harness.queries.list_attempts(task_id))[0].status == "running"
            success = await client.post(
                submit_url, params=params,
                headers={"X-Attempt-Lease": claim["lease_token"]},
                json={"output": {"summary": "trusted"}},
            )
            assert success.status_code == 200
            assert success.json()["status"] == "completed"
            assert (await client.post(
                submit_url, params=params,
                headers={"X-Attempt-Lease": claim["lease_token"]},
                json={"output": {"summary": "duplicate"}},
            )).status_code == 422  # existing terminal-state transition contract
            async with harness.sf() as session:
                lease = await session.get(AttemptLease, attempt_id)
                assert lease.state == "revoked"


async def test_server_rejects_revoked_lease_before_submit_or_fail(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claim = (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )).json()
            await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/lease/revoke",
            )
            for action, payload in (
                ("submit", {"output": {"summary": "late"}}),
                ("fail", {"error": "late"}),
            ):
                result = await client.post(
                    f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/{action}",
                    params={"agent_id": agent.id},
                    headers={"X-Attempt-Lease": claim["lease_token"]},
                    json=payload,
                )
                assert result.status_code == 409
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"


async def test_authenticated_failure_consumes_lease_atomically(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claim = (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )).json()
            reply = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/fail",
                params={"agent_id": agent.id},
                headers={"X-Attempt-Lease": claim["lease_token"]},
                json={"error": "trusted failure"},
            )
            assert reply.status_code == 200
            assert reply.json()["status"] == "failed"
            renewed = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": claim["lease_token"]},
            )
            assert renewed.status_code == 409
    async with harness.sf() as session:
        lease = await session.get(AttemptLease, claim["id"])
        assert lease.state == "revoked"


async def test_lease_terminal_gate_is_disabled_in_legacy_mode(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claim = (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )).json()
            out = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/submit",
                params={"agent_id": agent.id},
                json={"output": {"summary": "legacy"}},
            )
            assert out.status_code == 200
            assert out.json()["status"] == "completed"


async def test_recovery_revokes_lease_and_rejects_late_terminal_write(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claimed = (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )).json()
            from orchestration_server.engine import OrchestrationEngine
            recovered = await OrchestrationEngine(
                harness.sf, require_lease=True,
            ).recover()
            assert recovered["recovered_attempts"] == 1
            assert recovered["recovered_tasks"] == 1

            async with harness.sf() as session:
                lease = await session.get(AttemptLease, claimed["id"])
                assert lease.state == "revoked"

            for action, data in (
                ("submit", {"output": {"summary": "late"}}),
                ("fail", {"error": "late"}),
            ):
                rejected = await client.post(
                    f"/api/v1/tasks/{tasks[0].id}/attempts/{claimed['id']}/{action}",
                    params={"agent_id": agent.id},
                    headers={"X-Attempt-Lease": claimed["lease_token"]},
                    json=data,
                )
                assert rejected.status_code in (409, 422)
            retry_renew = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claimed['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": claimed["lease_token"]},
            )
            assert retry_renew.status_code == 409

    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"


async def test_lease_renewal_cannot_revive_after_terminal_submission(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            claim = (await client.post(
                f"/api/v1/tasks/{tasks[0].id}/claim",
                json={"agent_id": agent.id},
            )).json()
            submitted = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/submit",
                params={"agent_id": agent.id},
                headers={"X-Attempt-Lease": claim["lease_token"]},
                json={"output": {"summary": "final"}},
            )
            assert submitted.status_code == 200
            renewed = await client.post(
                f"/api/v1/tasks/{tasks[0].id}/attempts/{claim['id']}/lease/renew",
                json={"agent_id": agent.id, "lease_token": claim["lease_token"]},
            )
            assert renewed.status_code == 409
            async with harness.sf() as session:
                lease = await session.get(AttemptLease, claim["id"])
                assert lease.state == "revoked"
