"""Offline tests for durable opt-in attempt capability lifecycle.

No paid LLM, remote worker, or real network calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
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


async def test_lease_issue_samples_time_after_sqlite_writer_contention(harness):
    """A claim cannot return a five-second token stale after a blocked write.

    Exercise actual concurrent SQLite transactions rather than patching
    internal methods: issue() must acquire the DB write fence *before* now().
    """
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    clock = [datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)]
    service = AttemptLeaseService(
        harness.sf, ttl_seconds=5, clock=lambda: clock[0],
    )
    # An actual SQLite BEGIN IMMEDIATE blocks the aiosqlite issuing writer.
    # The test moves the clock while the issue task waits for that lock.
    db_path = harness.url.split("///", 1)[1]
    blocker = sqlite3.connect(db_path, timeout=5, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute(
        "UPDATE task_attempts SET status = status WHERE id = ?",
        (attempt.id,),
    )
    issuing = asyncio.create_task(service.issue(attempt.id, agent.id))
    try:
        await asyncio.sleep(0.2)
        assert not issuing.done(), "Writer lock did not block lease issuance"
        clock[0] += timedelta(seconds=20)
    finally:
        blocker.rollback()
        blocker.close()
    grant = await asyncio.wait_for(issuing, timeout=10)
    assert grant.expires_at == clock[0] + timedelta(seconds=5)
    assert await service.validate(attempt.id, agent.id, grant.token)
    async with harness.sf() as session:
        persisted = await session.get(AttemptLease, attempt.id)
        issued = persisted.issued_at
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        assert issued == clock[0]
        assert persisted.expires_at == grant.expires_at.replace(tzinfo=None) or (
            persisted.expires_at == grant.expires_at
        )
