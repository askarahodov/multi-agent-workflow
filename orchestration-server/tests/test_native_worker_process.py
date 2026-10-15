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
