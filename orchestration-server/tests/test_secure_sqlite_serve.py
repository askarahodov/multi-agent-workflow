"""No-network fail-closed acceptance for an explicit secured SQLite server."""
from __future__ import annotations

import os
import pytest

from orchestration_server.secure_sqlite_serve import config_from_env, main


def configured(tmp_path):
    private = tmp_path / "control"
    private.mkdir(mode=0o700)
    db = private / "orch.db"
    db.write_bytes(b"not-a-valid-database-and-must-not-be-opened")
    key = private / "worker.key"
    key.write_text("worker-key-" + "a" * 36, encoding="ascii")
    tlskey = private / "server.key"
    tlskey.write_text("test-key")
    cert = private / "server.crt"
    cert.write_text("test-cert")
    os.chmod(key, 0o600)
    os.chmod(tlskey, 0o600)
    return {
        "MAW_SECURE_ORCH_ENABLED": "1",
        "ORCH_ATTEMPT_LEASE_ENABLED": "1",
        "AUTH_ENABLED": "true",
        "ORCH_DATABASE_URL": "sqlite+aiosqlite:////" + str(db).lstrip("/"),
        "ORCH_TLS_CERT_FILE": str(cert),
        "ORCH_TLS_KEY_FILE": str(tlskey),
        "MAW_ORCH_API_KEY_FILE": str(key),
    }


def test_secure_orchestration_disabled_by_default(monkeypatch, capsys):
    monkeypatch.delenv("MAW_SECURE_ORCH_ENABLED", raising=False)
    assert main() == 3
    assert "FAIL_CLOSED" in capsys.readouterr().err


def test_valid_settings_are_offline_only(tmp_path):
    config = configured(tmp_path)
    key, url, cert, tls = config_from_env(config)
    assert key.startswith("worker-key-")
    assert url == config["ORCH_DATABASE_URL"]
    assert not (tmp_path / "control" / "orch.db-wal").exists()


@pytest.mark.parametrize("variable,value", [
    ("MAW_SECURE_ORCH_ENABLED", "0"),
    ("ORCH_ATTEMPT_LEASE_ENABLED", "0"),
    ("AUTH_ENABLED", "false"),
    ("AUTH_ENABLED", "TRUE"),
    ("ADMIN_API_KEYS", "ambient-secret"),
    ("ORCH_DATABASE_URL", "postgresql+asyncpg://localhost/unsafe"),
    ("ORCH_DATABASE_URL", "sqlite+aiosqlite:///./relative.db"),
    ("ORCH_TLS_KEY_FILE", "/missing/private.key"),
])
def test_config_rejects_insecure_modes(tmp_path, variable, value):
    env = {**configured(tmp_path), variable: value}
    with pytest.raises((ValueError, OSError)):
        config_from_env(env)


def test_world_readable_worker_key_denied(tmp_path):
    env = configured(tmp_path)
    os.chmod(env["MAW_ORCH_API_KEY_FILE"], 0o644)
    with pytest.raises(ValueError):
        config_from_env(env)


def test_worker_key_symlink_denied(tmp_path):
    env = configured(tmp_path)
    link = tmp_path / "link.key"
    link.symlink_to(env["MAW_ORCH_API_KEY_FILE"])
    env["MAW_ORCH_API_KEY_FILE"] = str(link)
    with pytest.raises(ValueError):
        config_from_env(env)
