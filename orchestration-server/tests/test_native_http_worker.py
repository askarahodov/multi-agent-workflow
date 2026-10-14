"""REST integration tests for an authenticated, bounded native worker client."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.models import Task
from orchestration_server.native_http_worker import NativeHttpWorker, RemoteWorkerError
from orchestration_server.native_worker_supervisor import NativeWorkerSupervisor


@asynccontextmanager
async def online_worker(harness, *, agent_id, runner):
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with NativeHttpWorker(
            server_url="https://control.example",
            api_key="integration-test-token",
            agent_id=agent_id,
            runner=runner,
            transport=transport,
        ) as worker:
            yield worker


async def test_remote_worker_claims_and_completes_real_sqlite_task(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    calls = []

    async def runner(task, attempt_id):
        calls.append((task["id"], attempt_id))
        return '{"summary":"checked by contract"}'

    async with online_worker(harness, agent_id=agent.id, runner=runner) as worker:
        result = await worker.run_once()
        assert result is not None and result.verified
        assert result.status == "completed"
        assert calls == [(tasks[0].id, result.attempt_id)]
        assert await worker.run_once() is None
    assert (await harness.queries.get_run(run.id)).status == "completed"


async def test_empty_queue_has_zero_runner_calls(harness):
    agent = await harness.orch.register_agent("idle-remote")
    called = []

    async def runner(_task, _attempt):
        called.append(True)
        return '{"summary":"never"}'

    async with online_worker(harness, agent_id=agent.id, runner=runner) as worker:
        batch = await worker.run_batch(max_attempts=3)
    assert batch.attempts == () and not batch.stopped_on_failure
    assert not called


async def test_remote_worker_respects_retry_deadline(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    async with harness.sf() as session:
        task = await session.get(Task, tasks[0].id)
        task.retry_at = datetime.now(timezone.utc) + timedelta(hours=10)
        await session.commit()

    async def forbidden(_task, _attempt):
        raise AssertionError("Future retry never authorizes runner")

    async with online_worker(harness, agent_id=agent.id, runner=forbidden) as worker:
        page = await worker._page(
            f"/workflows/runs/{tasks[0].workflow_run_id}/tasks",
            params={}, max_items=1,
        )
        stamped = datetime.fromisoformat(page[0]["retry_at"].replace("Z", "+00:00"))
        assert stamped.tzinfo is not None
        assert stamped > datetime.now(timezone.utc) + timedelta(hours=9)
        assert await worker.run_once() is None
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


async def test_bad_json_is_safely_recorded_as_failed_attempt(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=1,
    )

    async def bad(_task, _attempt):
        return '{"summary":"a","summary":"duplicated"}'

    async with online_worker(harness, agent_id=agent.id, runner=bad) as worker:
        batch = await worker.run_batch(max_attempts=5)
    assert len(batch.attempts) == 1 and batch.stopped_on_failure
    assert not batch.attempts[0].verified
    assert (await harness.queries.get_task(tasks[0].id)).status == "failed"


async def test_provider_exception_does_not_leak_secret_to_database(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=1,
    )

    async def failing(_task, _attempt):
        raise RuntimeError("sk-live-secret-provider-url")

    async with online_worker(harness, agent_id=agent.id, runner=failing) as worker:
        result = await worker.run_once()
        assert result is not None and not result.verified
    attempt = (await harness.queries.list_attempts(tasks[0].id))[0]
    assert attempt.error == "native_runner_failed"


async def test_two_remote_workers_cannot_claim_same_task(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    other = await harness.orch.register_agent("remote-2")
    calls = []

    async def runner(task, attempt):
        calls.append((task["id"], attempt))
        await asyncio.sleep(0.05)
        return '{"summary":"once"}'

    async with online_worker(harness, agent_id=agent.id, runner=runner) as one:
        async with online_worker(harness, agent_id=other.id, runner=runner) as two:
            out = await asyncio.gather(one.run_once(), two.run_once())
    winners = [x for x in out if x is not None]
    assert len(winners) == 1 and winners[0].verified
    assert len(calls) == 1
    assert (await harness.queries.get_task(tasks[0].id)).attempt_count == 1


@pytest.mark.parametrize("bad_url", [
    "http://example.org", "http://localhost", "http://192.168.0.1",
    "https://name:pass@example.org", "https://example.org/path",
    "https://example.org?token=secret", "file:///etc/passwd",
])
def test_remote_urls_fail_closed(bad_url):
    async def runner(*args): return "{}"
    with pytest.raises(ValueError):
        NativeHttpWorker(
            server_url=bad_url, api_key="worker-test-key",
            agent_id="agent", runner=runner,
        )


def test_empty_api_key_and_arbitrary_http_rejected():
    async def runner(*args): return "{}"
    with pytest.raises(ValueError):
        NativeHttpWorker(
            server_url="https://example.org", api_key="",
            agent_id="agent", runner=runner,
        )
    with pytest.raises(ValueError):
        NativeHttpWorker(
            server_url="http://10.0.0.1", allow_loopback_http=True,
            api_key="worker-test-key", agent_id="agent", runner=runner,
        )


async def test_redirect_is_not_followed_and_cannot_leak_key():
    calls = []

    def handler(req):
        calls.append((str(req.url), req.headers.get("x-api-key")))
        return httpx.Response(307, headers={"Location": "https://steal.example/collect"})

    async def runner(*args):
        raise AssertionError("Redirect is never a task")

    async with NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="a", runner=runner,
        transport=httpx.MockTransport(handler),
    ) as worker:
        with pytest.raises(RemoteWorkerError):
            await worker.run_once()
    assert calls == [("https://control.example/api/v1/workflows/runs?status=running&limit=20", "worker-test-key")]


async def test_rejected_credentials_stop_before_runner():
    invoked = []

    def handler(req):
        return httpx.Response(401, json={"detail": "internal API key detail"})

    async def runner(*args):
        invoked.append(True)
        return "{}"

    async with NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="a", runner=runner,
        transport=httpx.MockTransport(handler),
    ) as worker:
        with pytest.raises(RemoteWorkerError, match="API request rejected") as exc:
            await worker.run_once()
    assert "internal API key detail" not in str(exc.value)
    assert not invoked


def test_invalid_batch_bound_rejected_without_io():
    async def runner(*args): return "{}"
    client = NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="a", runner=runner,
    )
    async def exercise():
        async with client:
            with pytest.raises(ValueError):
                await client.run_batch(max_attempts=0)
    asyncio.run(exercise())


async def test_supervisor_runs_real_http_contract_once_then_idles(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    calls = []

    async def runner(task, attempt):
        calls.append((task["id"], attempt))
        return '{"summary":"supervised result"}'

    async with online_worker(harness, agent_id=agent.id, runner=runner) as worker:
        report = await NativeWorkerSupervisor(
            worker, max_polls=2, poll_interval_seconds=0.01,
        ).run(asyncio.Event())
    assert report.polls == 2
    assert report.completed_attempts == 1
    assert report.failed_attempts == 0
    assert report.reason == "POLL_LIMIT"
    assert len(calls) == 1
    assert (await harness.queries.get_run(run.id)).status == "completed"


async def test_supervisor_stops_after_contract_verification_failure(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, max_attempts=2,
    )
    calls = []

    async def invalid(task, attempt):
        calls.append(task["id"])
        return '{"summary":""}'

    async with online_worker(harness, agent_id=agent.id, runner=invalid) as worker:
        report = await NativeWorkerSupervisor(
            worker, max_polls=5, poll_interval_seconds=0.01,
        ).run(asyncio.Event())
    assert report.reason == "FAIL_CLOSED"
    assert report.polls == 1 and report.failed_attempts == 1
    assert len(calls) == 1
