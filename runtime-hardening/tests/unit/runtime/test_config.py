"""Unit tests for configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.config import RuntimeSettings, load_quota_config

EXAMPLE = Path(__file__).resolve().parents[3] / "config" / "resource-quotas.example.yaml"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_CONTAINER_RUNTIME", "podman")
    monkeypatch.setenv("AGENT_RUNTIME_CGROUP_ROOT", str(tmp_path))
    settings = RuntimeSettings()
    assert settings.container_runtime == "podman"
    assert settings.cgroup_root == tmp_path


def test_settings_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("container_runtime: podman\nrootless: false\n", encoding="utf-8")
    settings = RuntimeSettings.from_yaml(cfg, service_name="x")
    assert settings.container_runtime == "podman"
    assert settings.rootless is False
    assert settings.service_name == "x"


def test_settings_from_yaml_rejects_non_mapping(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        RuntimeSettings.from_yaml(cfg)


def test_load_quota_config_example() -> None:
    if not EXAMPLE.is_file():
        pytest.skip("example quota config not available in workspace")
    quota = load_quota_config(EXAMPLE)
    assert "untrusted" in quota.resourceClasses
    assert quota.parentBudget.memory is not None
    parent_max = quota.parentBudget.memory.maxBytes
    assert parent_max is not None
    assert quota.agents["build-farm-01"].overrides is not None
    assert quota.agents["build-farm-01"].overrides.memory is not None
    assert quota.agents["build-farm-01"].overrides.memory.maxBytes is not None
    assert quota.agents["build-farm-01"].overrides.memory.maxBytes <= parent_max


def test_load_quota_config_rejects_bad_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_quota_config(bad)
