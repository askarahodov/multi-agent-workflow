"""Regression: protected native Compose cannot depend on third-party agent CLIs."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = spec_from_file_location("native_compose_policy", _ROOT / "scripts" / "check_native_qa_compose.py")
policy = module_from_spec(_SPEC)
_SPEC.loader.exec_module(policy)


@pytest.mark.parametrize("command", [
    ["hermes", "chat", "-q"],
    "sh -c 'exec hermes -p default chat'",
    ["bash", "-lc", "/usr/local/bin/codex exec 'task'"],
    ["claude", "--print", "task"],
    ["env", "HOME=/tmp", "/opt/tools/hermes", "kanban"],
])
def test_rejects_external_cli_in_any_resolved_container_command(command):
    with pytest.raises(ValueError, match="External agent CLI forbidden"):
        policy.reject_external_agent_cli({
            "services": {"native-worker": {"command": command}}
        })


@pytest.mark.parametrize("field", ["command", "entrypoint"])
def test_checks_all_compose_services_and_both_command_forms(field):
    with pytest.raises(ValueError, match="external-helper"):
        policy.reject_external_agent_cli({
            "services": {
                "native-worker": {"command": ["python", "-m", "native_worker"]},
                "external-helper": {field: ["bash", "-lc", "hermes chat"]},
            }
        })


def test_allows_native_python_git_and_openrouter_commands():
    policy.reject_external_agent_cli({
        "services": {
            "native-worker": {"entrypoint": ["python", "-m", "native_worker"],
                              "command": ["dispatch"]},
            "trusted-gateway": {"command": ["/usr/local/bin/git", "status"]},
            "qa": {"command": ["python", "-m", "quality_gates"]},
        }
    })


def test_live_policy_denies_external_qa_command_before_credentials():
    services = {
        name: {} for name in (
            "native-worker", "trusted-gateway", "native-qa-controller",
            "secure-orchestration", "secure-quality-gates",
        )
    }
    services["native-worker"] = {
        "command": ["python", "-m", "native_worker", "dispatch"],
        "environment": {"MAW_TRUSTED_GIT_ENABLED": "1"},
    }
    services["trusted-gateway"] = {"environment": {"MAW_GATEWAY_GIT_ENABLED": "1"}}
    services["native-qa-controller"] = {
        "command": ["python", "-m", "native_qa", "dispatch"],
        "environment": {
            "MAW_QA_AUTONOMOUS_ENABLED": "1",
            "MAW_QA_TEST_COMMAND_JSON": '["bash","-lc","hermes chat"]',
        },
    }
    with pytest.raises(ValueError, match="External agent CLI forbidden in independent QA"):
        policy.validate_live_sdlc({"services": services})
