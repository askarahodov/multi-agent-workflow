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
from orchestration_server.models import AttemptLease, Task
from orchestration_server.native_http_worker import NativeHttpWorker, RemoteWorkerError, TrustedAttemptLease
from orchestration_server.native_worker_supervisor import NativeWorkerSupervisor


@asynccontextmanager
async def online_worker(
    harness, *, agent_id, runner=None, leased_runner=None,
    lease_enabled=False, require_lease=False, renew_interval=0.05,
):
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=lease_enabled,
        attempt_lease_ttl_seconds=5,
    ))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with NativeHttpWorker(
            server_url="https://control.example",
            api_key="integration-test-token",
            agent_id=agent_id,
            runner=runner,
            leased_runner=leased_runner,
            require_lease=require_lease,
            lease_renew_interval_seconds=renew_interval,
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


async def test_opt_in_http_worker_renews_server_lease_without_provider_token(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    seen = []

    async def leased(task, attempt_id, lease):
        assert task["id"] == tasks[0].id
        assert "lease_token" not in task
        assert isinstance(lease, TrustedAttemptLease)
        assert lease.token not in repr(lease)
        assert lease.generation == 1
        seen.append(attempt_id)
        await asyncio.sleep(0.18)
        return '{"summary":"renewed safely"}'

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=leased,
        lease_enabled=True, require_lease=True, renew_interval=0.03,
    ) as worker:
        result = await worker.run_once()
        assert result is not None and result.verified
    assert len(seen) == 1
    async with harness.sf() as session:
        entry = await session.get(AttemptLease, result.attempt_id)
        assert entry is not None and entry.renewed_at is not None
    assert (await harness.queries.get_run(run.id)).status == "completed"


async def test_http_worker_refuses_missing_lease_before_runner_and_does_not_submit(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    calls = []

    async def forbidden(_task, _attempt, _lease):
        calls.append(True)
        return '{"summary":"should never run"}'

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=forbidden,
        lease_enabled=False, require_lease=True,
    ) as worker:
        with pytest.raises(RemoteWorkerError, match="lease"):
            await worker.run_once()

    assert calls == []
    attempts = await harness.queries.list_attempts(tasks[0].id)
    assert len(attempts) == 1 and attempts[0].status == "running"
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"


async def test_remote_lease_revocation_interrupts_renewal_without_submitting(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    started = asyncio.Event()
    observed_cancel = asyncio.Event()

    async def paused(_task, _attempt, _lease):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed_cancel.set()
            raise

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=paused,
        lease_enabled=True, require_lease=True, renew_interval=0.03,
    ) as worker:
        running = asyncio.create_task(worker.run_once())
        try:
            await asyncio.wait_for(started.wait(), 5)
            attempt = (await harness.queries.list_attempts(tasks[0].id))[0]
            from orchestration_server.attempt_leases import AttemptLeaseService
            assert await AttemptLeaseService(harness.sf).revoke(attempt.id)
            with pytest.raises(RemoteWorkerError, match="reconciliation"):
                await asyncio.wait_for(running, 5)
        finally:
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

    assert observed_cancel.is_set()
    attempt = (await harness.queries.list_attempts(tasks[0].id))[0]
    assert attempt.status == "running"
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"


def test_http_worker_requires_trusted_lease_runner_and_bounded_polling():
    async def classic(_task, _attempt):
        return "{}"

    async def leased(_task, _attempt, _lease):
        return "{}"

    with pytest.raises(TypeError, match="leased runner"):
        NativeHttpWorker(
            server_url="https://control.example", api_key="worker-test-key",
            agent_id="agent", runner=classic, require_lease=True,
        )
    with pytest.raises(TypeError, match="native runner"):
        NativeHttpWorker(
            server_url="https://control.example", api_key="worker-test-key",
            agent_id="agent", leased_runner=leased, require_lease=False,
        )
    for seconds in (0, -1, 31):
        with pytest.raises(ValueError, match="interval"):
            NativeHttpWorker(
                server_url="https://control.example", api_key="worker-test-key",
                agent_id="agent", leased_runner=leased, require_lease=True,
                lease_renew_interval_seconds=seconds,
            )


@pytest.mark.parametrize("failure_mode", ["unavailable", "wrong_generation"])
async def test_remote_worker_fails_closed_on_broken_renewal(harness, failure_mode):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    began, canceled = asyncio.Event(), asyncio.Event()

    class BrokenRenewTransport(httpx.AsyncBaseTransport):
        def __init__(self, delegate):
            self.delegate = delegate

        async def handle_async_request(self, request):
            if str(request.url.path).endswith("/lease/renew"):
                if failure_mode == "unavailable":
                    return httpx.Response(503, json={"detail": "internal-secret-must-not-leak"})
                return httpx.Response(200, json={
                    "generation": 999,
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=30)
                    ).isoformat(),
                })
            return await self.delegate.handle_async_request(request)

        async def aclose(self):
            await self.delegate.aclose()

    async def waiting(_task, _attempt, _lease):
        began.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.set()
            raise

    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True, attempt_lease_ttl_seconds=5,
    ))
    async with app.router.lifespan_context(app):
        transport = BrokenRenewTransport(httpx.ASGITransport(app=app))
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="worker-test-key",
            agent_id=agent.id, leased_runner=waiting, require_lease=True,
            lease_renew_interval_seconds=0.02, transport=transport,
        ) as worker:
            with pytest.raises(RemoteWorkerError, match="reconciliation") as exc:
                await asyncio.wait_for(worker.run_once(), 5)
            assert "internal-secret" not in str(exc.value)
            assert "wrong_generation" not in str(exc.value)

    assert began.is_set() and canceled.is_set()
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"
    attempts = await harness.queries.list_attempts(tasks[0].id)
    assert len(attempts) == 1 and attempts[0].status == "running"
