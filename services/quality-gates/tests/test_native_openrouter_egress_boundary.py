"""Operator opt-in provider egress must not extend control-plane trust boundary."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def read(name):
    return yaml.safe_load((ROOT / 'deploy' / 'compose' / 'secure' / name).read_text())


def test_default_trusted_runtime_has_no_provider_egress():
    control = read("compose.trusted-sqlite-control.yml")
    worker = read("compose.native-worker-runtime.yml")
    assert control["networks"]["trusted-control"]["internal"] is True
    assert worker["networks"]["trusted-control"]["internal"] is True
    assert worker["services"]["native-worker"]["networks"] == ["trusted-control"]
    for name in ("secure-orchestration", "trusted-gateway"):
        assert control["services"][name]["networks"] == ["trusted-control"] or (
            "networks" not in control["services"][name]
            and control["x-runtime"]["networks"] == ["trusted-control"]
        )


def test_openrouter_egress_requires_explicit_overlay_and_only_worker_joins():
    overlay = read("compose.native-openrouter-egress.yml")
    assert set(overlay["services"]) == {"native-worker"}
    assert overlay["services"]["native-worker"]["networks"] == [
        "trusted-control", "native-provider-egress",
    ]
    network = overlay["networks"]["native-provider-egress"]
    assert network["internal"] is False
    assert network["driver"] == "bridge"
    assert "network_mode" not in overlay["services"]["native-worker"]
    assert "privileged" not in overlay["services"]["native-worker"]
    assert "volumes" not in overlay["services"]["native-worker"]


def test_qa_dispatch_overlay_never_enables_provider_egress():
    for name in ("compose.native-autonomous-dispatch.yml",
                 "compose.native-autonomous-qa-dispatch.yml",
                 "compose.native-qa-runtime.yml",
                 "compose.release-approval.yml"):
        overlay = read(name)
        assert "native-provider-egress" not in overlay.get("networks", {})
        for service in overlay["services"].values():
            assert "native-provider-egress" not in service.get("networks", [])
