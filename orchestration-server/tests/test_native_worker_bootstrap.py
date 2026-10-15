"""Offline fail-closed bootstrap contract; no network or paid providers."""
import asyncio
import os

import pytest

from orchestration_server.native_worker_bootstrap import (
    NativeWorkerConfig, config_from_env, run_trusted_worker,
)


def private_config(tmp_path):
    path = tmp_path / "worker-key"
    path.write_text("local-private-api-key", encoding="ascii")
    os.chmod(path, 0o600)
    return {
        "MAW_NATIVE_WORKER_ENABLED": "1",
        "MAW_NATIVE_WORKER_LEASE_REQUIRED": "1",
        "MAW_NATIVE_WORKER_SERVER_URL": "https://orchestrator.internal",
        "MAW_NATIVE_WORKER_API_KEY_FILE": str(path),
        "MAW_NATIVE_WORKER_AGENT_ID": "trusted-agent",
        "MAW_NATIVE_WORKER_MAX_POLLS": "2",
        "MAW_NATIVE_WORKER_POLL_SECONDS": "0.01",
    }


def test_requires_explicit_enablement_and_lease(tmp_path):
    env = private_config(tmp_path)
    for key in ("MAW_NATIVE_WORKER_ENABLED", "MAW_NATIVE_WORKER_LEASE_REQUIRED"):
        disabled = {**env, key: "0"}
        with pytest.raises(ValueError):
            config_from_env(disabled)


def test_trusted_private_file_only(tmp_path):
    env = private_config(tmp_path)
    good = config_from_env(env)
    assert good.api_key == "local-private-api-key"
    assert good.max_polls == 2
    assert "local-private-api-key" not in repr(good)
    file = tmp_path / "worker-key"
    os.chmod(file, 0o644)
    with pytest.raises(ValueError, match="private"):
        config_from_env(env)
    os.chmod(file, 0o600)
    link = tmp_path / "key-link"
    link.symlink_to(file)
    with pytest.raises(ValueError):
        config_from_env({**env, "MAW_NATIVE_WORKER_API_KEY_FILE": str(link)})


@pytest.mark.parametrize("url", [
    "http://remote.example", "http://localhost", "https://example.org/path",
    "https://someone:secret@example.org", "https://example.org?key=abc",
    "file:///tmp/worker", "http://169.254.169.254",
])
def test_unsafe_origin_denied_without_network(tmp_path, url):
    with pytest.raises(ValueError):
        config_from_env({**private_config(tmp_path), "MAW_NATIVE_WORKER_SERVER_URL": url})


@pytest.mark.parametrize("key,value", [
    ("MAW_NATIVE_WORKER_MAX_POLLS", "0"),
    ("MAW_NATIVE_WORKER_MAX_POLLS", "1001"),
    ("MAW_NATIVE_WORKER_POLL_SECONDS", "0"),
    ("MAW_NATIVE_WORKER_POLL_SECONDS", "3601"),
    ("MAW_NATIVE_WORKER_BATCH_SIZE", "101"),
])
def test_bounded_worker_config(tmp_path, key, value):
    with pytest.raises(ValueError):
        config_from_env({**private_config(tmp_path), key: value})


async def test_finite_worker_does_not_run_when_explicitly_stopped(monkeypatch):
    config = NativeWorkerConfig(
        "https://orchestrator.internal", "test-private-key", "agent",
        max_polls=2, poll_interval_seconds=0.01,
        max_attempts_per_poll=1,
    )
    stop = asyncio.Event()
    stop.set()

    async def forbidden(*_args):
        raise AssertionError("No provider action before stop")

    report = await run_trusted_worker(config, leased_runner=forbidden, stop_event=stop)
    assert report.polls == 0
    assert report.reason == "STOPPED"
