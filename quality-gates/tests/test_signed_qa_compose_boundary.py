"""Fail if privileged Docker access leaks into signed QA Compose services."""
from __future__ import annotations

from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "compose.native-qa-runtime.yml"


def test_credential_bearing_qa_services_have_no_docker_host_access():
    compose = yaml.safe_load(CONFIG.read_text())
    for name in ("secure-quality-gates", "native-qa-controller", "secure-orchestration"):
        config = compose["services"][name]
        assert config.get("privileged") is not True, name
        assert "ALL" in config.get("cap_drop", compose.get("x-qa-runtime", {}).get("cap_drop", [])), name
        assert config.get("network_mode") != "host", name
        assert config.get("pid") != "host", name
        assert config.get("ipc") != "host", name
        for entry in config.get("volumes", []):
            if isinstance(entry, str):
                source, _, target = entry.partition(":")
            else:
                source = str(entry.get("source", ""))
                target = str(entry.get("target", ""))
            assert "docker.sock" not in source and "docker.sock" not in target, name
            assert source != "/var/run" and target != "/var/run", name


def test_qa_service_and_controller_cannot_gain_privileged_by_runtime_anchor():
    text = CONFIG.read_text()
    # Inherited properties are also checked, not only explicit service fields.
    compose = yaml.safe_load(text)
    runtime = compose["x-qa-runtime"]
    assert runtime["privileged"] is False
    assert runtime["read_only"] is True
    assert runtime["user"] == "10003:10003"
    assert "ALL" in runtime["cap_drop"]
