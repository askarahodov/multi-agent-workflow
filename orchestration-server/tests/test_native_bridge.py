"""Native runner → OrchestrationEngine integration with a real SQLite journal.

The fake runner stands in for agent_management.run_agent_loop, which is injected
by the future trusted worker. This suite does NOT assume the worker exists yet.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from orchestration_server.models import SagaEvent

from conftest import seed_workflow
from orchestration_server.errors import ConflictError, StateTransitionError
from orchestration_server.native_bridge import (
    InvalidNativeOutput, parse_native_output, run_native_task_attempt,
)


async def _events(harness, run_id):
    async with harness.sf() as session:
        return list((await session.scalars(
            select(SagaEvent).where(SagaEvent.run_id == run_id)
        )).all())


def test_strict_output_parser_only_accepts_unique_finite_json_objects():
    assert parse_native_output('{"summary":"ok","confidence":0.5}') == {
        "summary": "ok", "confidence": 0.5,
    }
    for invalid in (
        "not json",
        "```json\n{\"summary\":\"ok\"}\n```",
        '["an array"]',
        '"scalar"',
        "null",
        '{"summary":"ok","summary":"overwritten"}',
        '{"summary": NaN}',
        '{"confidence":Infinity}',
        '{"confidence":1e9999}',
        '{"confidence":-1e9999}',
        '{"summary":"\\uD800"}',
        '{"nested":{"x":1,"x":2}}',
        '{"summary":"too much"} trailing',
    ):
        with pytest.raises(InvalidNativeOutput):
            parse_native_output(invalid)
    with pytest.raises(InvalidNativeOutput, match="size limit"):
        parse_native_output('{"summary":"very long"}', max_bytes=10)


async def test_native_valid_result_passes_contract_and_completes_run(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    called = []

    async def runner(task_id, attempt_id):
        called.append((task_id, attempt_id))
        return json.dumps({"summary": "native result", "confidence": 0.9})

    result = await run_native_task_attempt(
        harness.orch, task_id=tasks[0].id, agent_id=agent.id, runner=runner,
    )
    assert result.status == "completed" and result.verified
    assert called == [(tasks[0].id, result.attempt_id)]
    task = await harness.queries.get_task(tasks[0].id)
    assert task.status == "completed"
    assert task.output_data == {"summary": "native result", "confidence": 0.9}
    assert (await harness.queries.get_run(run.id)).status == "completed"

    events = await _events(harness, run.id)
    kinds = [event.event_type for event in events]
    assert "task.claimed" in kinds
    assert "attempt.completed" in kinds
    assert "task.completed" in kinds
    assert "run.completed" in kinds


async def test_contract_rejects_invalid_but_well_formed_native_json(harness):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=1,
    )

    async def runner(_task, _attempt):
        return '{"summary":"","confidence":2}'

    outcome = await run_native_task_attempt(
        harness.orch, task_id=tasks[0].id, agent_id=agent.id, runner=runner,
    )
    assert outcome.status == "verification_failed"
    assert not outcome.verified
    assert (await harness.queries.get_task(tasks[0].id)).status == "failed"
    assert (await harness.queries.get_run(run.id)).status == "failed"


@pytest.mark.parametrize("bad", [
    "not-json", '{"summary":"one","summary":"two"}',
    '{"summary":NaN}', '["array"]',
])
async def test_unparseable_output_fails_engine_attempt_without_false_success(harness, bad):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=1,
    )
    result = await run_native_task_attempt(
        harness.orch,
        task_id=tasks[0].id,
        agent_id=agent.id,
        runner=lambda task, attempt: asyncio.sleep(0, result=bad),
    )
    assert result.status == "failed" and not result.verified
    t = await harness.queries.get_task(tasks[0].id)
    assert t.status == "failed" and t.output_data is None
    events = await _events(harness, run.id)
    kinds = [e.event_type for e in events]
    assert "attempt.failed" in kinds and "task.completed" not in kinds


async def test_runner_failure_does_not_store_secret_error(harness):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=1,
    )
    secret = "sk-PRIVATE-DO-NOT-PERSIST"

    async def exploding(_task, _attempt):
        raise RuntimeError(secret)

    result = await run_native_task_attempt(
        harness.orch, task_id=tasks[0].id, agent_id=agent.id, runner=exploding,
    )
    assert result.status == "failed" and not result.verified
    events = await _events(harness, run.id)
    assert not any(secret in str(e.payload) for e in events)
    assert any("native_runner_failed" in str(e.payload) for e in events)


async def test_recoverable_failure_is_requeued_by_engine_retry_policy(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=2, retry_base=0.0,
    )
    first = await run_native_task_attempt(
        harness.orch, task_id=tasks[0].id, agent_id=agent.id,
        runner=lambda t, a: asyncio.sleep(0, result='{"summary":"first","summary":"duplicate"}'),
    )
    assert first.status == "failed"
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"
    assert await harness.orch.tick() == 1

    second = await run_native_task_attempt(
        harness.orch, task_id=tasks[0].id, agent_id=agent.id,
        runner=lambda t, a: asyncio.sleep(0, result='{"summary":"recovered"}'),
    )
    assert second.status == "completed" and second.verified
    assert first.attempt_id != second.attempt_id


async def test_already_claimed_task_does_not_invoke_native_runner(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    was_run = False

    async def runner(_t, _a):
        nonlocal was_run
        was_run = True
        return '{"summary":"should not happen"}'

    with pytest.raises(ConflictError):
        await run_native_task_attempt(
            harness.orch, task_id=tasks[0].id, agent_id=agent.id, runner=runner,
        )
    assert not was_run


async def test_worker_cancellation_is_not_misreported_as_success(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)

    async def cancelled(_t, _a):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_native_task_attempt(
            harness.orch, task_id=tasks[0].id, agent_id=agent.id, runner=cancelled,
        )
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"


@pytest.mark.parametrize("invalid_limit", [True, False, None, -1, 0, 1.5, "5", [], {}])
def test_output_parser_rejects_invalid_limit_types(invalid_limit):
    with pytest.raises(ValueError, match="positive integer"):
        parse_native_output('{"summary":"ok"}', max_bytes=invalid_limit)


@pytest.mark.parametrize("invalid_limit", [True, False, None, -1, 0, 1.5, "5", [], {}])
async def test_bridge_rejects_invalid_limit_before_claim(harness, invalid_limit):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    called = False

    async def forbidden(_task, _attempt):
        nonlocal called
        called = True
        return '{"summary":"should-not-run"}'

    with pytest.raises(ValueError, match="positive integer"):
        await run_native_task_attempt(
            harness.orch, task_id=tasks[0].id, agent_id=agent.id,
            runner=forbidden, max_result_bytes=invalid_limit,
        )
    assert not called
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


@pytest.mark.parametrize("surrogate", [chr(0xD800), chr(0xDFFF)])
def test_parser_rejects_unpaired_surrogate_before_utf8_size_check(surrogate):
    with pytest.raises(InvalidNativeOutput, match="UTF-8"):
        parse_native_output('{"summary":"' + surrogate + '"}')


async def test_bridge_handles_raw_surrogate_without_false_completion(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=1,
    )
    result = await run_native_task_attempt(
        harness.orch, task_id=tasks[0].id, agent_id=agent.id,
        runner=lambda t, a: asyncio.sleep(0, result='{"summary":"' + chr(0xD800) + '"}'),
    )
    assert result.status == "failed" and not result.verified
    assert (await harness.queries.get_task(tasks[0].id)).status == "failed"


async def test_invalid_limit_or_runner_does_not_claim_task(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    with pytest.raises(ValueError):
        await run_native_task_attempt(
            harness.orch, task_id=tasks[0].id, agent_id=agent.id,
            runner=lambda t, a: asyncio.sleep(0, result="{}"), max_result_bytes=0,
        )
    with pytest.raises(TypeError):
        await run_native_task_attempt(
            harness.orch, task_id=tasks[0].id, agent_id=agent.id, runner=None,
        )
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"
