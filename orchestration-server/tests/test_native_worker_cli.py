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
