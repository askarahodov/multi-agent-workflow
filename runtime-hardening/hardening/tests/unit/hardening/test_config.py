"""Unit tests for configuration loading and quota validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from runtime.hardening.config import (
    DEFAULT_QUOTA_CONFIG,
    ResilienceSettings,
    RuntimeSettings,
    load_quota_config,
)


def test_default_quota_config_exists() -> None:
    assert DEFAULT_QUOTA_CONFIG.is_file()


def test_example_quota_config_validates_against_schema() -> None:
    """Phase-0 exit: resource-quotas.example.yaml validates against the schema.

    We load the YAML through the pydantic model (which enforces the cgroup
    invariants) and assert the enum/schemaVersion contract.
    """
    cfg = load_quota_config()
    assert cfg.schemaVersion == "1.0.0"
    assert "trusted" in cfg.resourceClasses
    assert "untrusted" in cfg.resourceClasses
    assert "high-isolation" in cfg.resourceClasses
    # swapMax == max invariant is enforced by the model on every class.
    for _name, limits in cfg.resourceClasses.items():
        if limits.memory is not None:
            assert limits.memory.swapMaxBytes == limits.memory.maxBytes
            if limits.memory.highBytes is not None:
                assert limits.memory.highBytes <= limits.memory.maxBytes


def test_example_quota_config_agents_reference_valid_classes() -> None:
    cfg = load_quota_config()
    for agent_id, quota in cfg.agents.items():
        assert quota.cls in cfg.resourceClasses, agent_id


def test_load_quota_config_missing_file() -> None:
    with pytest.raises(OSError):
        load_quota_config("/nonexistent/quota.yaml")


def test_load_quota_config_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: [valid: yaml: [", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_quota_config(bad)


def test_resilience_settings_defaults() -> None:
    s = ResilienceSettings()
    assert s.failure_rate_threshold == 0.5
    assert s.wait_duration_in_open_state == 30.0
    assert s.retry_max_attempts == 3
    assert s.retry_budget_ratio == 0.1


def test_runtime_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARBOR_LOG_LEVEL", "DEBUG")
    settings = RuntimeSettings()
    assert settings.log_level == "DEBUG"


def test_runtime_settings_defaults() -> None:
    settings = RuntimeSettings()
    assert settings.isolation.parent_slice == "agent.slice"
    assert settings.isolation.default_non_root_uid == 65532
