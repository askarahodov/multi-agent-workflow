"""Process CLI failure isolation and bounded delegated execution."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from orchestration_server import native_worker_cli
from orchestration_server.native_worker_bootstrap import NativeWorkerConfig
from orchestration_server.native_worker_wiring import TrustedRunnerConfig


def test_run_cannot_start_without_explicit_config(monkeypatch, capsys):
    monkeypatch.delenv("MAW_NATIVE_WORKER_ENABLED", raising=False)
    assert native_worker_cli.main(["run"]) == 3
    stderr = capsys.readouterr().err
    assert "FAIL_CLOSED" in stderr
    assert "Traceback" not in stderr


def test_run_redacts_internal_exception(monkeypatch, capsys):
    async def failure():
        raise RuntimeError("secret-provider-key-and-endpoint")
    monkeypatch.setattr(native_worker_cli, "run_worker", failure)
    assert native_worker_cli.main(["run"]) == 3
    result = capsys.readouterr()
    assert "secret-provider" not in result.err + result.out


@pytest.mark.asyncio
async def test_mismatched_identity_fails_before_provider_construction(monkeypatch):
    from orchestration_server import native_worker_bootstrap, native_worker_wiring
    worker = NativeWorkerConfig(
        server_url="https://orch.example", api_key="worker-private-key",
        agent_id="agent-one", max_polls=1, poll_interval_seconds=1,
        max_attempts_per_poll=1,
    )
    runner = TrustedRunnerConfig(
        gateway_url="https://gateway.example",
        gateway_key="gateway-private-key-with-32-characters-01",
        provider_key="provider-private-key-with-32-characters-01",
        agent_id="agent-two", model="model/fixed",
        prompt="Trusted prompt", max_turns=1,
        max_total_tokens=128, max_tool_calls=1,
    )
    monkeypatch.setattr(native_worker_cli, "config_from_env", lambda: worker)
    monkeypatch.setattr(native_worker_wiring, "trusted_runner_config_from_env", lambda env: runner)
    monkeypatch.setattr(
        native_worker_wiring, "construct_trusted_runner",
        lambda cfg: pytest.fail("Untrusted provider must not be constructed"),
    )
    with pytest.raises(ValueError, match="identities differ"):
        await native_worker_cli.run_worker()


@pytest.mark.asyncio
async def test_reused_secrets_fail_before_provider(monkeypatch):
    from orchestration_server import native_worker_wiring
    worker = NativeWorkerConfig(
        server_url="https://orch.example", api_key="same-secret",
        agent_id="agent-one", max_polls=1, poll_interval_seconds=1,
        max_attempts_per_poll=1,
    )
    runner = TrustedRunnerConfig(
        gateway_url="https://gateway.example",
        gateway_key="gateway-private-key-with-32-characters-01",
        provider_key="same-secret", agent_id="agent-one",
        model="model/fixed", prompt="Trusted prompt", max_turns=1,
        max_total_tokens=128, max_tool_calls=1,
    )
    monkeypatch.setattr(native_worker_cli, "config_from_env", lambda: worker)
    monkeypatch.setattr(native_worker_wiring, "trusted_runner_config_from_env", lambda env: runner)
    monkeypatch.setattr(
        native_worker_wiring, "construct_trusted_runner",
        lambda cfg: pytest.fail("Provider construction should not occur"),
    )
    with pytest.raises(ValueError, match="distinct"):
        await native_worker_cli.run_worker()


@pytest.mark.asyncio
async def test_dispatch_reuses_one_http_worker_and_cursor_across_sessions(monkeypatch):
    from orchestration_server import native_worker_bootstrap as boot
    from orchestration_server.native_http_worker import RemoteAttemptResult, RemoteWorkerBatch

    created = []
    class ScanningWorker:
        def __init__(self, **kwargs):
            self.cursor = 0
            self.attempts = 0
            created.append(self)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def run_batch(self, *, max_attempts=1):
            assert max_attempts == 1
            self.cursor += 1
            if self.cursor == 3:
                self.attempts += 1
                return RemoteWorkerBatch((
                    RemoteAttemptResult("late-task", "attempt", "completed", True),
                ), False)
            return RemoteWorkerBatch((), False)

    monkeypatch.setattr(boot, "NativeHttpWorker", ScanningWorker)
    config = NativeWorkerConfig(
        server_url="https://control.test", api_key="private-worker-key",
        agent_id="native", max_polls=1, poll_interval_seconds=0.01,
        max_attempts_per_poll=10,
    )
    result = await boot.run_trusted_dispatch(
        config, leased_runner=lambda *args: None,
        stop_event=asyncio.Event(), max_sessions=5, max_completions=1,
    )
    assert result.reason == "BUDGET_REACHED"
    assert result.completed_attempts == 1 and result.polls == 3
    assert len(created) == 1
    assert created[0].cursor == 3


@pytest.mark.asyncio
async def test_dispatch_fails_closed_without_reopening_http_worker(monkeypatch):
    from orchestration_server import native_worker_bootstrap as boot
    from orchestration_server.native_http_worker import RemoteAttemptResult, RemoteWorkerBatch
    creations = []
    class FailingWorker:
        def __init__(self, **kwargs):
            creations.append(1)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def run_batch(self, *, max_attempts=1):
            return RemoteWorkerBatch((
                RemoteAttemptResult("task", "attempt", "verification_failed", False),
            ), True)
    monkeypatch.setattr(boot, "NativeHttpWorker", FailingWorker)
    config = NativeWorkerConfig(
        server_url="https://control.test", api_key="private-worker-key",
        agent_id="native", max_polls=2, poll_interval_seconds=0.01,
        max_attempts_per_poll=1,
    )
    result = await boot.run_trusted_dispatch(
        config, leased_runner=lambda *args: None, stop_event=asyncio.Event(),
        max_sessions=10, max_completions=10,
    )
    assert result.reason == "FAIL_CLOSED" and result.polls == 1
    assert len(creations) == 1


@pytest.mark.parametrize("sessions,completions", [
    (0, 1), (101, 1), (1, 0), (1, 101), (True, 1), (1, "2"),
])
@pytest.mark.asyncio
async def test_dispatch_limits_fail_before_constructing_http(monkeypatch, sessions, completions):
    from orchestration_server import native_worker_bootstrap as boot
    monkeypatch.setattr(boot, "NativeHttpWorker", lambda **kwargs: pytest.fail("constructed"))
    config = NativeWorkerConfig(
        server_url="https://control.test", api_key="private-worker-key",
        agent_id="native", max_polls=1, poll_interval_seconds=0.01,
        max_attempts_per_poll=1,
    )
    with pytest.raises(ValueError):
        await boot.run_trusted_dispatch(
            config, leased_runner=lambda *args: None, stop_event=asyncio.Event(),
            max_sessions=sessions, max_completions=completions,
        )
