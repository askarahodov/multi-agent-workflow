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
    stop_event=None, git_required=False,
):
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=lease_enabled,
        attempt_lease_ttl_seconds=5,
        require_git_artifact=git_required,
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
            transport=transport, stop_event=stop_event,
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


@pytest.mark.parametrize("setting,value", [
    ("max_runs", True), ("max_runs", False), ("max_runs", "10"),
    ("max_runs", None), ("max_runs", 1.5), ("max_runs", 10**400),
    ("max_tasks_per_run", True), ("max_tasks_per_run", 1.5),
    ("max_tasks_per_run", "10"), ("max_tasks_per_run", None),
    ("lease_renew_interval_seconds", True),
    ("lease_renew_interval_seconds", None),
    ("lease_renew_interval_seconds", float("nan")),
    ("lease_renew_interval_seconds", float("inf")),
    ("lease_renew_interval_seconds", 10**400),
    ("timeout_seconds", False), ("timeout_seconds", "1"),
    ("timeout_seconds", None), ("timeout_seconds", float("nan")),
    ("timeout_seconds", float("inf")), ("timeout_seconds", 10**400),
])
def test_http_worker_invalid_bounds_fail_before_transport(setting, value):
    async def runner(*_args):
        raise AssertionError("Runner must never execute")
    with pytest.raises(ValueError):
        NativeHttpWorker(
            server_url="https://control.example",
            api_key="worker-test-key", agent_id="agent", runner=runner,
            **{setting: value},
        )


@pytest.mark.parametrize("bad", [True, False, 0, 101, 1.5, "2", None, 10**400])
async def test_http_worker_invalid_batch_never_polls(bad):
    requests = []
    def handler(request):
        requests.append(request)
        raise AssertionError("Invalid batch must not perform HTTP I/O")
    async def runner(*_args):
        raise AssertionError("Invalid batch must not call provider")
    async with NativeHttpWorker(
        server_url="https://control.example",
        api_key="worker-test-key", agent_id="agent", runner=runner,
        transport=httpx.MockTransport(handler),
    ) as worker:
        with pytest.raises(ValueError, match="batch limit"):
            await worker.run_batch(max_attempts=bad)
    assert requests == []


async def test_preengaged_stop_never_contacts_orchestrator_or_provider():
    stop = asyncio.Event()
    stop.set()
    async def never_called(*_args):
        pytest.fail("Stop must prevent model use")
    def forbidden(_request):
        pytest.fail("Stop must prevent HTTP polling")
    async with NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="agent", leased_runner=never_called, require_lease=True,
        transport=httpx.MockTransport(forbidden), stop_event=stop,
    ) as worker:
        assert await worker.run_once() is None


async def test_stop_during_leased_runner_quarantines_attempt_and_denies_reclaim(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    other = await harness.orch.register_agent("no-replay-after-stop")
    stop = asyncio.Event()
    began, cancelled = asyncio.Event(), asyncio.Event()
    effects = []

    async def leased(_task, _attempt, _lease):
        began.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=leased,
        lease_enabled=True, require_lease=True,
        renew_interval=0.03, stop_event=stop,
    ) as worker:
        active = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(began.wait(), 5)
        stop.set()
        with pytest.raises(RemoteWorkerError, match="reconciliation"):
            await asyncio.wait_for(active, 5)
        assert cancelled.is_set()
        # The interrupted attempt stays owned by the orchestration engine.
        assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"

    async with online_worker(
        harness, agent_id=other.id,
        runner=lambda *_: pytest.fail("Interrupted task must not be replayed"),
    ) as restarted:
        assert await restarted.run_once() is None
    assert (await harness.queries.get_task(tasks[0].id)).attempt_count == 1
    attempts = await harness.queries.list_attempts(tasks[0].id)
    assert len(attempts) == 1 and attempts[0].status == "running"
    await harness.orch.recover()
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"
    assert effects == []


async def test_wrong_run_ownership_rejected_before_claim():
    seen = []
    def handler(req):
        seen.append((req.method, req.url.path))
        if req.url.path.endswith("/workflows/runs"):
            return httpx.Response(200, json={
                "items": [{"id": "run-one"}], "next_cursor": None,
            })
        if req.url.path.endswith("/workflows/runs/run-one/tasks"):
            return httpx.Response(200, json={
                "items": [{"id": "task-one", "workflow_run_id": "run-other",
                           "status": "pending"}],
                "next_cursor": None,
            })
        pytest.fail("Mismatched task must never be claimed")
    async def forbidden(*_args):
        pytest.fail("Untrusted task must not invoke the runner")
    async with NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="trusted", runner=forbidden,
        transport=httpx.MockTransport(handler),
    ) as worker:
        with pytest.raises(RemoteWorkerError, match="belong"):
            await worker.run_once()
    assert len(seen) == 2


def test_worker_custom_ca_is_verified_and_fails_closed_on_invalid_path(tmp_path):
    import ssl
    from unittest.mock import patch
    context = ssl.create_default_context()
    ca = tmp_path / "trusted-ca.pem"
    ca.write_text("trusted-ca-placeholder")
    async def runner(*_args): return "{}"
    with patch(
        "orchestration_server.native_http_worker.ssl.create_default_context",
        return_value=context,
    ) as create_context:
        worker = NativeHttpWorker(
            server_url="https://control.example", api_key="worker-test-key",
            agent_id="agent", runner=runner, ca_file=str(ca),
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"items": []})),
        )
        create_context.assert_called_once_with(cafile=str(ca))
        asyncio.run(worker._client.aclose())
    for invalid in (str(tmp_path / "absent.pem"), "relative-ca.pem"):
        with pytest.raises(ValueError, match="CA"):
            NativeHttpWorker(
                server_url="https://control.example", api_key="worker-test-key",
                agent_id="agent", runner=runner, ca_file=invalid,
            )


async def test_stop_during_final_lease_renewal_prevents_submit(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    stop = asyncio.Event()
    async def prompt(_task, _attempt, _lease):
        return '{"summary":"must not submit after stop"}'

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=prompt,
        lease_enabled=True, require_lease=True, stop_event=stop,
    ) as worker:
        original = worker._renew_attempt
        async def renewal_then_stop(task_id, attempt_id, lease):
            result = await original(task_id, attempt_id, lease)
            stop.set()
            return result
        worker._renew_attempt = renewal_then_stop
        with pytest.raises(RemoteWorkerError, match="reconciliation"):
            await worker.run_once()

    task = await harness.queries.get_task(tasks[0].id)
    assert task.status == "in_progress"
    assert task.attempt_count == 1
    assert (await harness.queries.list_attempts(task.id))[0].status == "running"


async def test_git_required_native_worker_cannot_complete_without_commit(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)

    async def no_commit(_task, _attempt, _lease):
        return '{"summary":"model claims completion without a commit"}'

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=no_commit,
        lease_enabled=True, require_lease=True, git_required=True,
    ) as worker:
        with pytest.raises(RemoteWorkerError, match="request rejected"):
            await worker.run_once()
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"
    assert (await harness.queries.get_run(run.id)).status == "running"
    attempt = (await harness.queries.list_attempts(tasks[0].id))[0]
    assert attempt.status == "running"


async def test_git_required_native_worker_records_commit_provenance(harness):
    from shared.native_artifact import NativeArtifactResult

    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)

    async def committed(_task, _attempt, _lease):
        return NativeArtifactResult(
            output='{"summary":"verified contract result"}',
            commit_sha="a" * 40,
            changed_paths=("out/build.txt",),
        )

    async with online_worker(
        harness, agent_id=agent.id, leased_runner=committed,
        lease_enabled=True, require_lease=True, git_required=True,
    ) as worker:
        result = await worker.run_once()
    assert result is not None and result.verified
    assert (await harness.queries.get_run(run.id)).status == "completed"
    evidence = await harness.queries.get_git_evidence(tasks[0].id)
    assert len(evidence) == 1
    assert evidence[0].commit_sha == "a" * 40


def test_git_requirement_cannot_run_without_leased_engine(harness):
    from orchestration_server.engine import OrchestrationEngine

    with pytest.raises(ValueError, match="leased"):
        OrchestrationEngine(harness.sf, require_git_artifact=True)


async def test_bounded_run_cursor_reaches_later_workflows_without_starvation():
    observed = []

    def handler(req):
        if req.url.path.endswith("/workflows/runs"):
            cursor = req.url.params.get("after")
            observed.append(cursor)
            if cursor is None:
                return httpx.Response(200, json={
                    "items": [{"id": "run-first"}], "next_cursor": "second-page",
                })
            if cursor == "second-page":
                return httpx.Response(200, json={
                    "items": [{"id": "run-second"}], "next_cursor": None,
                })
            raise AssertionError("Unrecognized cursor")
        if req.url.path.endswith("/tasks"):
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        raise AssertionError(f"Unexpected URL: {req.url}")

    async def forbidden(*args):
        raise AssertionError("No ready task should execute")

    async with NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="agent", runner=forbidden, max_runs=1,
        transport=httpx.MockTransport(handler),
    ) as worker:
        assert await worker.run_once() is None
        assert await worker.run_once() is None
        assert await worker.run_once() is None
    assert observed == [None, "second-page", None]


async def test_native_worker_rejects_malformed_active_run_cursor_without_claim():
    def handler(req):
        if req.url.path.endswith("/workflows/runs"):
            return httpx.Response(200, json={
                "items": [{"id": "run-first"}], "next_cursor": 123,
            })
        raise AssertionError("Invalid page must fail before task lookup")

    async def forbidden(*args):
        raise AssertionError("No invocation on malformed cursor")

    async with NativeHttpWorker(
        server_url="https://control.example", api_key="worker-test-key",
        agent_id="agent", runner=forbidden, max_runs=1,
        transport=httpx.MockTransport(handler),
    ) as worker:
        with pytest.raises(RemoteWorkerError, match="active run page"):
            await worker.run_once()
