"""Gateway preflight never opens SQLite or starts serving HTTPS."""
import os
import pytest

from agent_management.trusted_gateway_cli import main, validate_local_config


def configuration(tmp_path):
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "out").mkdir()
    control = tmp_path / "control"
    control.mkdir(mode=0o700)
    db = control / "orch.db"
    db.write_bytes(b"not-opened-by-preflight")
    key = control / "gateway.key"
    key.write_text("g" * 40)
    tls_key = control / "tls.key"
    tls_key.write_text("not-a-real-cert-key")
    cert = control / "tls.crt"
    cert.write_text("not-a-real-cert")
    for path in (db, key, tls_key):
        os.chmod(path, 0o600)
    return {
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_GATEWAY_WORKSPACE_ROOT": str(root),
        "MAW_GATEWAY_ORCHESTRATION_SQLITE": str(db),
        "MAW_GATEWAY_LEDGER_SQLITE": str(control / "ledger.db"),
        "MAW_GATEWAY_KEY_FILE": str(key),
        "MAW_GATEWAY_TLS_CERT_FILE": str(cert),
        "MAW_GATEWAY_TLS_KEY_FILE": str(tls_key),
    }


def test_preflight_rejects_default_without_creating_files(monkeypatch, capsys):
    monkeypatch.delenv("MAW_TRUSTED_GATEWAY_ENABLED", raising=False)
    assert main(["preflight"]) == 2
    assert "FAILED" in capsys.readouterr().err


def test_preflight_reads_metadata_not_orchestration_or_ledger(tmp_path):
    config = configuration(tmp_path)
    validate_local_config(config)
    assert not os.path.exists(config["MAW_GATEWAY_LEDGER_SQLITE"])


@pytest.mark.parametrize("field,value", [
    ("MAW_TRUSTED_GATEWAY_ENABLED", "0"),
    ("MAW_GATEWAY_ORCHESTRATION_SQLITE", "/does/not/exist"),
    ("MAW_GATEWAY_LEDGER_SQLITE", "relative/ledger.db"),
    ("MAW_GATEWAY_TLS_KEY_FILE", "/missing.key"),
])
def test_preflight_rejects_bad_config(tmp_path, field, value):
    with pytest.raises((ValueError, OSError)):
        validate_local_config({**configuration(tmp_path), field: value})


def test_preflight_denies_readable_secret(tmp_path):
    env = configuration(tmp_path)
    os.chmod(env["MAW_GATEWAY_KEY_FILE"], 0o644)
    with pytest.raises(ValueError):
        validate_local_config(env)


def test_preflight_denies_control_file_inside_workspace(tmp_path):
    env = configuration(tmp_path)
    env["MAW_GATEWAY_LEDGER_SQLITE"] = str(tmp_path / "workspace" / "ledger.db")
    with pytest.raises(ValueError):
        validate_local_config(env)
