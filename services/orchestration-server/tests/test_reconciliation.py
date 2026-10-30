"""Operator attestation over quarantined tasks; no recovery side-effect replay."""
from __future__ import annotations

import asyncio
from hashlib import sha256

import pytest
from sqlalchemy import select

from conftest import seed_workflow
from orchestration_server.errors import ConflictError, StateTransitionError
from orchestration_server.models import SagaEvent
from orchestration_server.native_worker import NativeWorker

REF = "qa-artifacts/recovery-review-123"
DIGEST = sha256(b"offline-review-evidence").hexdigest()


async def _quarantine(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    return agent, run, tasks[0]


def _decision(engine, task_id, decision, *, ref=REF, operator="key-demo"):
    return engine.reconcile_quarantined_task(
        task_id, decision=decision, evidence_ref=ref,
        evidence_sha256=DIGEST, operator_subject=operator,
    )


async def test_unknown_evidence_is_audited_but_still_blocked(harness):
    agent, run, task = await _quarantine(harness)
    record = await _decision(harness.orch, task.id, "UNKNOWN")
    assert record.decision == "UNKNOWN"
    assert record.evidence_sha256 == DIGEST
    assert record.operator_subject == "key-demo"
    assert (await harness.queries.get_task(task.id)).status == "blocked"
    assert (await harness.queries.get_reconciliation(task.id)).decision == "UNKNOWN"

    quarantined = await harness.queries.list_recovery_quarantine()
    assert [t.id for t in quarantined] == [task.id]
    async with harness.sf() as session:
        events = (await session.scalars(select(SagaEvent).where(
            SagaEvent.run_id == run.id,
            SagaEvent.event_type == "task.reconciliation_attested",
        ))).all()
    assert len(events) == 1
    assert events[0].payload["evidence_sha256"] == DIGEST
    assert events[0].payload["operator_subject"] == "key-demo"


async def test_unknown_may_be_upgraded_once_but_never_requeued(harness):
    agent, run, task = await _quarantine(harness)
    await _decision(harness.orch, task.id, "UNKNOWN")
    result = await _decision(
        harness.orch, task.id, "CONFIRMED_SIDE_EFFECT",
        ref="qa-artifacts/verified-side-effect-456",
        operator="key-admin-second",
    )
    assert result.decision == "CONFIRMED_SIDE_EFFECT"
    assert result.operator_subject == "key-admin-second"
    assert (await harness.queries.get_task(task.id)).status == "blocked"

    calls = []

    def forbidden(_task):
        calls.append(1)
        raise AssertionError("Confirmed side effect is never auto-replayed")

    worker = NativeWorker(
        harness.orch, harness.queries,
        agent_id=agent.id, runner_factory=forbidden,
    )
    assert await worker.run_once() is None
    assert calls == []
    with pytest.raises(ConflictError):
        await _decision(harness.orch, task.id, "CONFIRMED_NO_SIDE_EFFECT")

    async with harness.sf() as session:
        events = (await session.scalars(select(SagaEvent).where(
            SagaEvent.run_id == run.id,
            SagaEvent.event_type == "task.reconciliation_attested",
        ))).all()
    assert [e.payload["decision"] for e in events] == [
        "UNKNOWN", "CONFIRMED_SIDE_EFFECT",
    ]


async def test_two_admins_cannot_override_first_confirmed_decision(harness):
    _, _, task = await _quarantine(harness)
    outcomes = await asyncio.gather(
        _decision(harness.orch, task.id, "CONFIRMED_SIDE_EFFECT", operator="key-a"),
        _decision(harness.orch, task.id, "CONFIRMED_NO_SIDE_EFFECT", operator="key-b"),
        return_exceptions=True,
    )
    assert len([x for x in outcomes if not isinstance(x, Exception)]) == 1
    assert len([x for x in outcomes if isinstance(x, ConflictError)]) == 1
    saved = await harness.queries.get_reconciliation(task.id)
    assert saved.decision in ("CONFIRMED_SIDE_EFFECT", "CONFIRMED_NO_SIDE_EFFECT")
    assert (await harness.queries.get_task(task.id)).status == "blocked"


async def test_existing_confirmed_decision_cannot_be_modified(harness):
    _, _, task = await _quarantine(harness)
    await _decision(harness.orch, task.id, "CONFIRMED_NO_SIDE_EFFECT")
    for decision in (
        "CONFIRMED_NO_SIDE_EFFECT", "CONFIRMED_SIDE_EFFECT", "UNKNOWN",
    ):
        with pytest.raises(ConflictError):
            await _decision(harness.orch, task.id, decision)
    assert (await harness.queries.get_reconciliation(task.id)).decision == (
        "CONFIRMED_NO_SIDE_EFFECT"
    )


async def test_generic_blocked_task_is_not_recovery_quarantine(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.block_task(tasks[0].id, agent.id, "unrelated blocking reason")
    with pytest.raises(StateTransitionError, match="not a recovered quarantine"):
        await _decision(harness.orch, tasks[0].id, "UNKNOWN")
    assert await harness.queries.list_recovery_quarantine() == []


async def test_nonblocked_tasks_cannot_be_reconciled(harness):
    _, _, _, _, tasks = await seed_workflow(harness.orch, harness.queries)
    with pytest.raises(StateTransitionError):
        await _decision(harness.orch, tasks[0].id, "UNKNOWN")


@pytest.mark.parametrize("bad_ref,bad_digest", [
    ("https://example.org/?token=secret", DIGEST),
    ("name@secret", DIGEST),
    ("bad", "not-sha256"),
    ("x", DIGEST),
])
async def test_invalid_evidence_never_persisted(harness, bad_ref, bad_digest):
    _, _, task = await _quarantine(harness)
    with pytest.raises(Exception, match="Evidence"):
        await harness.orch.reconcile_quarantined_task(
            task.id, decision="UNKNOWN", evidence_ref=bad_ref,
            evidence_sha256=bad_digest, operator_subject="key-admin",
        )
    with pytest.raises(Exception, match="not found"):
        await harness.queries.get_reconciliation(task.id)


async def test_unknown_upgrade_race_has_only_one_winner(harness):
    _, run, task = await _quarantine(harness)
    await _decision(harness.orch, task.id, "UNKNOWN")
    results = await asyncio.gather(
        _decision(harness.orch, task.id, "CONFIRMED_SIDE_EFFECT", operator="key-a"),
        _decision(harness.orch, task.id, "CONFIRMED_NO_SIDE_EFFECT", operator="key-b"),
        return_exceptions=True,
    )
    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert len([r for r in results if isinstance(r, ConflictError)]) == 1
    async with harness.sf() as session:
        events = (await session.scalars(select(SagaEvent).where(
            SagaEvent.run_id == run.id,
            SagaEvent.event_type == "task.reconciliation_attested",
        ))).all()
    assert len(events) == 2


async def test_decision_survives_new_connection(harness_factory):
    h1 = await harness_factory()
    _, _, agent, run, tasks = await seed_workflow(h1.orch, h1.queries)
    await h1.orch.claim_task(tasks[0].id, agent.id)
    await h1.orch.recover()
    await _decision(h1.orch, tasks[0].id, "CONFIRMED_SIDE_EFFECT")
    await h1.stop()
    h2 = await harness_factory()
    saved = await h2.queries.get_reconciliation(tasks[0].id)
    assert saved.decision == "CONFIRMED_SIDE_EFFECT"
    assert (await h2.queries.get_task(tasks[0].id)).status == "blocked"
    assert await h2.orch.recover() == {
        "recovered_attempts": 0, "recovered_tasks": 0,
    }
