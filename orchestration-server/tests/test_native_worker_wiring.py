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
