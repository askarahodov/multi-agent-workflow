"""Offline contract for the operator preflight CLI."""
from __future__ import annotations

import os

from orchestration_server.native_worker_cli import main


def test_preflight_rejects_default_without_side_effects(monkeypatch, capsys):
    monkeypatch.delenv("MAW_NATIVE_WORKER_ENABLED", raising=False)
    assert main(["preflight"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "FAILED" in captured.err


def test_preflight_success_is_only_local_validation(tmp_path, monkeypatch, capsys):
    path = tmp_path / "worker.secret"
    path.write_text("private-api-secret-for-tests", encoding="ascii")
    os.chmod(path, 0o600)
    settings = {
        "MAW_NATIVE_WORKER_ENABLED": "1",
        "MAW_NATIVE_WORKER_LEASE_REQUIRED": "1",
        "MAW_NATIVE_WORKER_SERVER_URL": "https://orch.example",
        "MAW_NATIVE_WORKER_API_KEY_FILE": str(path),
        "MAW_NATIVE_WORKER_AGENT_ID": "agent-safe",
        "MAW_NATIVE_WORKER_MAX_POLLS": "1",
        "MAW_NATIVE_WORKER_POLL_SECONDS": "1",
    }
    gateway = tmp_path / "gateway.secret"
    provider = tmp_path / "provider.secret"
    gateway.write_text("gateway-secret-unique-0000000000001", encoding="ascii")
    provider.write_text("provider-secret-unique-0000000000002", encoding="ascii")
    os.chmod(gateway, 0o600)
    os.chmod(provider, 0o600)
    settings.update({
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_TRUSTED_GATEWAY_URL": "https://gateway.internal",
        "MAW_TRUSTED_GATEWAY_KEY_FILE": str(gateway),
        "MAW_OPENROUTER_KEY_FILE": str(provider),
        "MAW_OPENROUTER_MODEL": "openai/gpt-4o-mini",
        "MAW_NATIVE_WORKER_TRUSTED_PROMPT": "Only approved tools.",
        "MAW_NATIVE_WORKER_MAX_TURNS": "2",
        "MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS": "256",
        "MAW_NATIVE_WORKER_MAX_TOOL_CALLS": "1",
    })
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    assert main(["preflight"]) == 0
    output = capsys.readouterr()
    assert "no connection or execution tested" in output.out
    assert "private-api-secret" not in output.out + output.err
    assert str(path) not in output.out + output.err


def test_preflight_redacts_os_path_and_bad_secret(tmp_path, monkeypatch, capsys):
    bad_path = tmp_path / "sensitive-customer-private-file"
    monkeypatch.setenv("MAW_NATIVE_WORKER_ENABLED", "1")
    monkeypatch.setenv("MAW_NATIVE_WORKER_LEASE_REQUIRED", "1")
    monkeypatch.setenv("MAW_NATIVE_WORKER_SERVER_URL", "https://orch.example")
    monkeypatch.setenv("MAW_NATIVE_WORKER_API_KEY_FILE", str(bad_path))
    monkeypatch.setenv("MAW_NATIVE_WORKER_AGENT_ID", "agent-safe")
    monkeypatch.setenv("MAW_NATIVE_WORKER_MAX_POLLS", "1")
    monkeypatch.setenv("MAW_NATIVE_WORKER_POLL_SECONDS", "1")
    assert main(["preflight"]) == 2
    err = capsys.readouterr().err
    assert "FAILED" in err
    assert str(bad_path) not in err


def test_preflight_denies_missing_provider_configuration(tmp_path, monkeypatch, capsys):
    key = tmp_path / "orchestrator.key"
    key.write_text("orchestration-secret-for-tests", encoding="ascii")
    os.chmod(key, 0o600)
    values = {
        "MAW_NATIVE_WORKER_ENABLED": "1",
        "MAW_NATIVE_WORKER_LEASE_REQUIRED": "1",
        "MAW_NATIVE_WORKER_SERVER_URL": "https://orch.example",
        "MAW_NATIVE_WORKER_API_KEY_FILE": str(key),
        "MAW_NATIVE_WORKER_AGENT_ID": "agent-safe",
        "MAW_NATIVE_WORKER_MAX_POLLS": "1",
        "MAW_NATIVE_WORKER_POLL_SECONDS": "1",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MAW_TRUSTED_GATEWAY_ENABLED", raising=False)
    assert main(["preflight"]) == 2
    captured = capsys.readouterr()
    assert "FAILED" in captured.err
    assert "orchestration-secret" not in captured.err


def test_preflight_denies_reused_runtime_credentials(tmp_path, monkeypatch, capsys):
    key = tmp_path / "shared.key"
    provider = tmp_path / "provider.key"
    key.write_text("shared-secret-over-thirty-two-characters-0001", encoding="ascii")
    provider.write_text("provider-secret-over-thirty-two-characters-0002", encoding="ascii")
    os.chmod(key, 0o600)
    os.chmod(provider, 0o600)
    values = {
        "MAW_NATIVE_WORKER_ENABLED": "1",
        "MAW_NATIVE_WORKER_LEASE_REQUIRED": "1",
        "MAW_NATIVE_WORKER_SERVER_URL": "https://orch.example",
        "MAW_NATIVE_WORKER_API_KEY_FILE": str(key),
        "MAW_NATIVE_WORKER_AGENT_ID": "agent-safe",
        "MAW_NATIVE_WORKER_MAX_POLLS": "1",
        "MAW_NATIVE_WORKER_POLL_SECONDS": "1",
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_TRUSTED_GATEWAY_URL": "https://gateway.internal",
        "MAW_TRUSTED_GATEWAY_KEY_FILE": str(key),
        "MAW_OPENROUTER_KEY_FILE": str(provider),
        "MAW_OPENROUTER_MODEL": "openai/gpt-4o-mini",
        "MAW_NATIVE_WORKER_TRUSTED_PROMPT": "Only approved tools.",
        "MAW_NATIVE_WORKER_MAX_TURNS": "2",
        "MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS": "256",
        "MAW_NATIVE_WORKER_MAX_TOOL_CALLS": "1",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert main(["preflight"]) == 2
    assert "shared-secret" not in capsys.readouterr().err
