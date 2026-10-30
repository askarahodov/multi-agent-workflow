"""Protected Compose Git tool-mode requires coherent worker/gateway trust wiring."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
def load(name):
    return yaml.safe_load((ROOT / name).read_text())


def test_git_is_disabled_by_default_for_worker_and_gateway():
    worker = load("compose.native-worker-runtime.yml")["services"]["native-worker"]
    gateway = load("compose.trusted-sqlite-control.yml")["services"]["trusted-gateway"]
    assert worker["environment"].get("MAW_TRUSTED_GIT_ENABLED") != "1"
    assert gateway["environment"].get("MAW_GATEWAY_GIT_ENABLED") != "1"


def test_opt_in_enables_both_sides_and_does_not_mount_git_on_worker():
    services = load("compose.native-trusted-git-runtime.yml")["services"]
    assert set(services) == {"native-worker", "trusted-gateway"}
    assert services["native-worker"]["environment"] == {"MAW_TRUSTED_GIT_ENABLED": "1"}
    assert "volumes" not in services["native-worker"]
    gateway = services["trusted-gateway"]
    assert gateway["environment"]["MAW_GATEWAY_GIT_ENABLED"] == "1"
    assert gateway["environment"]["MAW_GATEWAY_GIT_EXECUTABLE"] == "/usr/bin/git"
    volumes = gateway["volumes"]
    assert len(volumes) == 2
    assert {v["target"] for v in volumes} == {
        gateway["environment"]["MAW_GATEWAY_GIT_SOURCE_REPOSITORY"],
        gateway["environment"]["MAW_GATEWAY_GIT_WORKTREE_HOME"],
    }
    for v in volumes:
        assert v["type"] == "bind"
        assert v["bind"]["create_host_path"] is False
        assert v["read_only"] is False
        assert "NOT-CONFIGURED" in v["source"]
        assert "docker.sock" not in v["source"]
        assert "docker.sock" not in v["target"]


def test_git_overlay_never_opens_gateway_or_control_egress():
    overlay = load("compose.native-trusted-git-runtime.yml")
    assert "networks" not in overlay
    for service in overlay["services"].values():
        assert "networks" not in service
        assert "privileged" not in service
        assert "network_mode" not in service
        assert "ports" not in service
