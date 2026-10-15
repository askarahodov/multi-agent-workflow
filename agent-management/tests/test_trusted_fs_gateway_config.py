"""Deployment fail-closed checks for the optional filesystem tool gateway."""
from __future__ import annotations

import os

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.trusted_fs_gateway import trusted_gateway_from_env


@pytest.fixture
def trusted_paths(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "out").mkdir()
    secret = tmp_path / "dedicated-gateway.key"
    secret.write_text("trusted-gateway-dedicated-secret-01234567890", encoding="ascii")
    os.chmod(secret, 0o600)
    orchestrator = tmp_path / "orchestrator.sqlite3"
    orchestrator.touch(mode=0o600)
    os.chmod(orchestrator, 0o600)
    ledger = tmp_path / "ledger.sqlite3"
    for env, path in (
        ("MAW_GATEWAY_WORKSPACE_ROOT", workspace),
        ("MAW_GATEWAY_ORCHESTRATION_SQLITE", orchestrator),
        ("MAW_GATEWAY_LEDGER_SQLITE", ledger),
        ("MAW_GATEWAY_KEY_FILE", secret),
    ):
        monkeypatch.setenv(env, str(path))
    return workspace, secret


def test_gateway_cannot_boot_without_operator_configuration(monkeypatch):
    for env in (
        "MAW_GATEWAY_WORKSPACE_ROOT", "MAW_GATEWAY_ORCHESTRATION_SQLITE",
        "MAW_GATEWAY_LEDGER_SQLITE", "MAW_GATEWAY_KEY_FILE",
    ):
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(ValueError, match="incomplete"):
        trusted_gateway_from_env()


def test_gateway_factory_boots_with_only_private_control_plane_paths(trusted_paths):
    app = trusted_gateway_from_env()
    assert app.title == "Trusted Native Filesystem Gateway"
    assert app.openapi_url is None


@pytest.mark.parametrize("invalid", ["world_readable", "symlink", "inside_workspace", "short_secret"])
def test_gateway_factory_rejects_unsafe_credentials(trusted_paths, monkeypatch, tmp_path, invalid):
    workspace, secret = trusted_paths
    if invalid == "world_readable":
        os.chmod(secret, 0o644)
    elif invalid == "symlink":
        alias = tmp_path / "key-symlink"
        alias.symlink_to(secret)
        monkeypatch.setenv("MAW_GATEWAY_KEY_FILE", str(alias))
    elif invalid == "inside_workspace":
        relocated = workspace / "out" / "gateway.key"
        relocated.write_text(secret.read_text(), encoding="ascii")
        os.chmod(relocated, 0o600)
        monkeypatch.setenv("MAW_GATEWAY_KEY_FILE", str(relocated))
    elif invalid == "short_secret":
        secret.write_text("weak", encoding="ascii")
    with pytest.raises((ValueError, ToolPolicyDenied)):
        trusted_gateway_from_env()
