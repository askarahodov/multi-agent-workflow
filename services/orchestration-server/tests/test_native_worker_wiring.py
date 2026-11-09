"""Offline trust-boundary tests: no OpenRouter request is made."""
from __future__ import annotations

import os

import pytest

from orchestration_server.native_worker_wiring import (
    trusted_runner_config_from_env,
)


def trusted_env(tmp_path):
    gateway = tmp_path / "gateway-secret"
    provider = tmp_path / "provider-secret"
    gateway.write_text("gateway-secret-with-32-characters-0001", encoding="ascii")
    provider.write_text("provider-secret-with-32-characters-0002", encoding="ascii")
    os.chmod(gateway, 0o600)
    os.chmod(provider, 0o600)
    return {
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_TRUSTED_GATEWAY_URL": "https://gateway.internal",
        "MAW_TRUSTED_GATEWAY_KEY_FILE": str(gateway),
        "MAW_OPENROUTER_KEY_FILE": str(provider),
        "MAW_NATIVE_WORKER_AGENT_ID": "agent-owned-by-control-plane",
        "MAW_OPENROUTER_MODEL": "openai/gpt-4o-mini",
        "MAW_NATIVE_WORKER_TRUSTED_PROMPT": "Use only approved file tools.",
        "MAW_NATIVE_WORKER_MAX_TURNS": "2",
        "MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS": "256",
        "MAW_NATIVE_WORKER_MAX_TOOL_CALLS": "2",
    }


def test_trusted_runner_defaults_to_disabled(tmp_path):
    e = trusted_env(tmp_path)
    e.pop("MAW_TRUSTED_GATEWAY_ENABLED")
    with pytest.raises(ValueError, match="opt-in"):
        trusted_runner_config_from_env(e)


@pytest.mark.parametrize("url", [
    "http://gateway.internal", "https://gateway.internal/dispatch",
    "https://user:key@gateway.internal", "https://gateway.internal?x=secret",
    "http://127.0.0.1",
])
def test_untrusted_gateway_urls_denied(tmp_path, url):
    with pytest.raises(ValueError):
        trusted_runner_config_from_env({**trusted_env(tmp_path), "MAW_TRUSTED_GATEWAY_URL": url})


def test_reusing_gateway_and_provider_key_denied(tmp_path):
    e = trusted_env(tmp_path)
    e["MAW_OPENROUTER_KEY_FILE"] = e["MAW_TRUSTED_GATEWAY_KEY_FILE"]
    with pytest.raises(ValueError, match="separation"):
        trusted_runner_config_from_env(e)


@pytest.mark.parametrize("var,bad", [
    ("MAW_OPENROUTER_MODEL", ""),
    ("MAW_OPENROUTER_MODEL", "https://attacker"),
    ("MAW_OPENROUTER_MODEL", "bad model"),
    ("MAW_NATIVE_WORKER_MAX_TURNS", "17"),
    ("MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS", "16385"),
    ("MAW_NATIVE_WORKER_MAX_TOOL_CALLS", "33"),
    ("MAW_NATIVE_WORKER_TRUSTED_PROMPT", ""),
])
def test_unbounded_or_untrusted_settings_denied(tmp_path, var, bad):
    with pytest.raises(ValueError):
        trusted_runner_config_from_env({**trusted_env(tmp_path), var: bad})



def test_explicit_gateway_ca_path_is_preserved(tmp_path):
    env = trusted_env(tmp_path)
    cert = tmp_path / "trusted-gateway-ca.pem"
    cert.write_text("placeholder-test-certificate", encoding="ascii")
    env["MAW_TRUSTED_GATEWAY_CA_FILE"] = str(cert)
    assert trusted_runner_config_from_env(env).gateway_ca_file == str(cert)


@pytest.mark.parametrize("bad", ["relative.pem", "/missing/ca.pem"])
def test_gateway_ca_requires_existing_absolute_file(tmp_path, bad):
    env = trusted_env(tmp_path)
    env["MAW_TRUSTED_GATEWAY_CA_FILE"] = bad
    with pytest.raises(ValueError, match="CA file"):
        trusted_runner_config_from_env(env)


def test_gateway_ca_symlink_rejected(tmp_path):
    env = trusted_env(tmp_path)
    cert = tmp_path / "actual.pem"
    cert.write_text("placeholder")
    link = tmp_path / "link.pem"
    link.symlink_to(cert)
    env["MAW_TRUSTED_GATEWAY_CA_FILE"] = str(link)
    with pytest.raises(ValueError, match="CA file"):
        trusted_runner_config_from_env(env)



@pytest.mark.parametrize("credential_var,basename", [
    ("MAW_TRUSTED_GATEWAY_KEY_FILE", "gateway-secret"),
    ("MAW_OPENROUTER_KEY_FILE", "provider-secret"),
])
def test_provider_and_gateway_credentials_reject_symlinked_ancestor(tmp_path, credential_var, basename):
    env = trusted_env(tmp_path)
    private = tmp_path / "private"
    private.mkdir()
    key = private / basename
    source = tmp_path / basename
    source.rename(key)
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    env[credential_var] = str(alias / basename)
    with pytest.raises(ValueError, match="path invalid"):
        trusted_runner_config_from_env(env)


def test_bound_native_worker_requires_private_profile_snapshot(tmp_path):
    from orchestration_server.native_profile_binding import ENV_KEYS
    ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    env = {**trusted_env(tmp_path), **dict(zip(ENV_KEYS, ids))}
    with pytest.raises(ValueError, match="execution snapshot"):
        trusted_runner_config_from_env(env)


def test_private_profile_snapshot_locks_model_prompt_and_permissions(tmp_path):
    import json
    from orchestration_server.native_profile_binding import ENV_KEYS
    ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    env = {
        **trusted_env(tmp_path), **dict(zip(ENV_KEYS, ids)),
        "MAW_NATIVE_PROFILE_GATEWAY_ROOT": "/workspace",
    }
    snapshot = {
        "schema_version": 1,
        "agent_definition_id": ids[0], "agent_definition_version": 2,
        "model_profile_id": ids[1], "model_profile_version": 3,
        "tool_policy_id": ids[2], "tool_policy_version": 1,
        "provider_id": "44444444-4444-4444-8444-444444444444",
        "provider_version": 1, "provider_type": "openrouter",
        "model_id": env["MAW_OPENROUTER_MODEL"],
        "system_prompt": env["MAW_NATIVE_WORKER_TRUSTED_PROMPT"],
        "model_max_tokens": 12,
        "permissions": {
            "fs_read": ["/workspace/src/**"], "fs_write": [],
            "git": [], "shell": [], "network": [],
        },
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    os.chmod(path, 0o600)
    env["MAW_NATIVE_PROFILE_SNAPSHOT_FILE"] = str(path)
    config = trusted_runner_config_from_env(env)
    assert config.profile_snapshot is not None
    assert config.profile_snapshot.model_max_tokens == 12
    assert config.profile_snapshot.permissions["fs_write"] == []
    assert config.model not in repr(config)
    assert config.prompt not in repr(config)
    assert "/workspace/src/**" not in repr(config)
    with pytest.raises(ValueError, match="Model or instructions"):
        trusted_runner_config_from_env({**env, "MAW_OPENROUTER_MODEL": "openai/different"})
    with pytest.raises(ValueError, match="Model or instructions"):
        trusted_runner_config_from_env({**env, "MAW_NATIVE_WORKER_TRUSTED_PROMPT": "forged"})
    with pytest.raises(ValueError, match="workspace root"):
        trusted_runner_config_from_env({**env, "MAW_NATIVE_PROFILE_GATEWAY_ROOT": ""})
    path.chmod(0o644)
    with pytest.raises(ValueError, match="snapshot"):
        trusted_runner_config_from_env(env)


def test_private_profile_snapshot_rejects_forged_ids_and_duplicate_json(tmp_path):
    from orchestration_server.native_profile_binding import TrustedProfileBinding
    from orchestration_server.native_profile_snapshot import (
        NativeProfileSnapshotError, read_native_profile_snapshot,
    )
    path = tmp_path / "snapshot.json"
    binding = TrustedProfileBinding(
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    path.write_text('{"schema_version":1,"schema_version":1}')
    os.chmod(path, 0o600)
    with pytest.raises(NativeProfileSnapshotError, match="snapshot unavailable"):
        read_native_profile_snapshot(str(path), binding)
    path.unlink()
    path.symlink_to(tmp_path / "forged.json")
    with pytest.raises(NativeProfileSnapshotError, match="path invalid"):
        read_native_profile_snapshot(str(path), binding)


def test_secure_compose_snapshot_overlay_uses_no_created_host_paths():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    content = (repo / "deploy/compose/secure/compose.native-profile-snapshot.yml").read_text()
    assert "create_host_path: false" in content
    assert "read_only: true" in content
    assert "MAW_NATIVE_PROFILE_GATEWAY_ROOT: /srv/maw/workspace" in content
    assert "MAW_NATIVE_PROFILE_SNAPSHOT_FILE: /run/maw-profile/approved.json" in content
