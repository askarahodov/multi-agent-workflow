"""TLS configuration tests for all four services (SEC-002).

Each service's Settings exposes ``cert_file``/``key_file``/``ca_file`` plus
``tls_enabled`` and ``ssl_config`` helpers. These tests set the relevant
per-service TLS env vars (agreed naming: ``ORCH_``/``AGENT_MGMT_``/
``AGENT_RUNTIME_``/``QG_`` prefix) and assert the resolved behaviour, then
clear the env and assert TLS is disabled.
"""

from __future__ import annotations

import os

import pytest

# Env keys per service, in the form used by each package.
ORCH_KEYS = {
    "cert": "ORCH_TLS_CERT_FILE",
    "key": "ORCH_TLS_KEY_FILE",
    "ca": "ORCH_TLS_CA_FILE",
}
AM_KEYS = {
    "cert": "AGENT_MGMT_TLS_CERT_FILE",
    "key": "AGENT_MGMT_TLS_KEY_FILE",
    "ca": "AGENT_MGMT_TLS_CA_FILE",
}
RT_KEYS = {
    "cert": "AGENT_RUNTIME_TLS_CERT_FILE",
    "key": "AGENT_RUNTIME_TLS_KEY_FILE",
    "ca": "AGENT_RUNTIME_TLS_CA_FILE",
}
QG_KEYS = {
    "cert": "QG_TLS_CERT_FILE",
    "key": "QG_TLS_KEY_FILE",
    "ca": "QG_TLS_CA_FILE",
}

ALL_KEYS = list(ORCH_KEYS.values()) + list(AM_KEYS.values()) + list(RT_KEYS.values()) + list(QG_KEYS.values())


@pytest.fixture(autouse=True)
def _tls_env_clean():
    for k in ALL_KEYS:
        os.environ.pop(k, None)
    yield
    for k in ALL_KEYS:
        os.environ.pop(k, None)


def _enable(keys: dict[str, str]) -> None:
    os.environ[keys["cert"]] = "/tmp/cert.pem"
    os.environ[keys["key"]] = "/tmp/key.pem"
    os.environ[keys["ca"]] = "/tmp/ca.pem"


def _enable_no_ca(keys: dict[str, str]) -> None:
    os.environ[keys["cert"]] = "/tmp/cert.pem"
    os.environ[keys["key"]] = "/tmp/key.pem"


# --------------------------------------------------------------------------- #
# orchestration-server (dataclass Settings)
# --------------------------------------------------------------------------- #
def test_orchestration_tls_disabled_by_default():
    from orchestration_server.config import get_settings

    s = get_settings()
    assert s.tls_enabled is False
    assert s.ssl_config == {}


def test_orchestration_tls_enabled_with_cert_and_key():
    _enable(ORCH_KEYS)
    from orchestration_server.config import get_settings

    s = get_settings()
    assert s.cert_file == "/tmp/cert.pem"
    assert s.key_file == "/tmp/key.pem"
    assert s.ca_file == "/tmp/ca.pem"
    assert s.tls_enabled is True
    assert s.ssl_config == {
        "ssl_certfile": "/tmp/cert.pem",
        "ssl_keyfile": "/tmp/key.pem",
        "ssl_ca_certs": "/tmp/ca.pem",
    }


def test_orchestration_tls_enabled_without_ca():
    _enable_no_ca(ORCH_KEYS)
    from orchestration_server.config import get_settings

    s = get_settings()
    assert s.tls_enabled is True
    assert "ssl_ca_certs" not in s.ssl_config


# --------------------------------------------------------------------------- #
# agent-management (dataclass Settings)
# --------------------------------------------------------------------------- #
def test_agent_management_tls_disabled_by_default():
    from agent_management.config import get_settings

    s = get_settings()
    assert s.tls_enabled is False
    assert s.ssl_config == {}


def test_agent_management_tls_enabled():
    _enable(AM_KEYS)
    from agent_management.config import get_settings

    s = get_settings()
    assert s.tls_enabled is True
    assert s.ssl_config["ssl_certfile"] == "/tmp/cert.pem"
    assert s.ssl_config["ssl_keyfile"] == "/tmp/key.pem"
    assert s.ssl_config["ssl_ca_certs"] == "/tmp/ca.pem"


# --------------------------------------------------------------------------- #
# runtime-hardening (pydantic RuntimeSettings)
# --------------------------------------------------------------------------- #
def test_runtime_tls_disabled_by_default():
    from runtime.config import RuntimeSettings

    s = RuntimeSettings()
    assert s.tls_enabled is False
    assert s.ssl_config == {}


def test_runtime_tls_enabled():
    _enable(RT_KEYS)
    from runtime.config import RuntimeSettings

    s = RuntimeSettings()
    assert s.cert_file == "/tmp/cert.pem"
    assert s.key_file == "/tmp/key.pem"
    assert s.tls_enabled is True
    assert s.ssl_config["ssl_certfile"] == "/tmp/cert.pem"
    assert s.ssl_config["ssl_ca_certs"] == "/tmp/ca.pem"


# --------------------------------------------------------------------------- #
# quality-gates (dataclass Settings)
# --------------------------------------------------------------------------- #
def test_quality_gates_tls_disabled_by_default():
    from quality_gates.config import Settings

    s = Settings()
    assert s.tls_enabled is False
    assert s.ssl_config == {}


def test_quality_gates_tls_enabled():
    _enable(QG_KEYS)
    from quality_gates.config import Settings

    s = Settings()
    assert s.tls_enabled is True
    assert s.ssl_config["ssl_certfile"] == "/tmp/cert.pem"
    assert s.ssl_config["ssl_keyfile"] == "/tmp/key.pem"
    assert s.ssl_config["ssl_ca_certs"] == "/tmp/ca.pem"