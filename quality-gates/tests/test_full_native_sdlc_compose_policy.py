"""Full secure native SDLC Compose policy denies partial and widened overlays."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('compose_policy', ROOT / 'scripts/check_native_qa_compose.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def complete_config():
    private = 'stack_trusted-control'
    outbound = 'stack_native-provider-egress'
    common = dict(read_only=True, privileged=False, restart='no', networks={private: None}, volumes=[])
    services = {name: copy.deepcopy(common) for name in (
        'native-worker', 'trusted-gateway', 'secure-orchestration',
        'native-qa-controller', 'secure-quality-gates')}
    services['native-worker'].update(
        command=['python', '-m', 'worker', 'dispatch'],
        environment={
            'MAW_TRUSTED_GIT_ENABLED': '1',
            'MAW_NATIVE_WORKER_API_KEY_FILE': '/run/secrets/worker.key',
            'MAW_TRUSTED_GATEWAY_KEY_FILE': '/run/secrets/gateway.key',
            'MAW_OPENROUTER_KEY_FILE': '/run/secrets/provider.key',
        },
        networks={private: None, outbound: None},
    )
    services['native-qa-controller'].update(
        command=['python', '-m', 'qa', 'dispatch'],
        environment={
            'MAW_QA_AUTONOMOUS_ENABLED': '1',
            'MAW_QA_TEST_COMMAND_JSON': '["python","-B","-m","pytest","-q"]',
            'MAW_QA_ORCH_ADMIN_KEY_FILE': '/run/secrets/qa-orch.key',
            'MAW_QA_SERVICE_ADMIN_KEY_FILE': '/run/secrets/qa-service.key',
        },
    )
    services['secure-orchestration']['environment'] = {
        'MAW_ORCH_RELEASE_APPROVAL_KEY_FILE': '/run/secrets/release.key',
        'MAW_ORCH_API_KEY_FILE': '/run/secrets/orch.key',
        'MAW_ORCH_QA_ADMIN_KEY_FILE': '/run/secrets/qa-admin.key',
        'MAW_ORCH_QA_SIGNING_KEY_FILE': '/run/secrets/qa-signing.key',
    }
    services['trusted-gateway'].update(
        environment={
            'MAW_GATEWAY_GIT_ENABLED': '1',
            'MAW_GATEWAY_KEY_FILE': '/run/secrets/gateway.key',
            'MAW_GATEWAY_GIT_SOURCE_REPOSITORY': '/srv/maw/operator-source',
            'MAW_GATEWAY_GIT_WORKTREE_HOME': '/srv/maw/git-attempts',
        },
        volumes=[
            {'target': '/srv/maw/operator-source'},
            {'target': '/srv/maw/git-attempts'},
        ],
    )
    return dict(services=services, networks={private: {'internal': True}, outbound: {'internal': False}})


def test_full_stack_passes_only_with_separate_egress_and_operator_gates():
    policy.validate_live_sdlc(complete_config())


@pytest.mark.parametrize('mutation', [
    lambda c: c['services']['native-worker']['environment'].update(MAW_TRUSTED_GIT_ENABLED='0'),
    lambda c: c['services']['trusted-gateway']['environment'].update(MAW_GATEWAY_GIT_ENABLED='0'),
    lambda c: c['services']['native-qa-controller']['environment'].update(MAW_QA_AUTONOMOUS_ENABLED='0'),
    lambda c: c['services']['native-worker'].update(command=['preflight']),
    lambda c: c['services']['native-qa-controller'].update(command=['preflight']),
    lambda c: c['services']['secure-orchestration']['environment'].clear(),
    lambda c: c['services']['native-worker']['networks'].pop('stack_native-provider-egress'),
    lambda c: c['services']['trusted-gateway']['networks'].update({'stack_native-provider-egress': None}),
    lambda c: c['services']['native-worker']['volumes'].append({'target': '/srv/maw/operator-source'}),
    lambda c: c['services']['trusted-gateway']['volumes'].clear(),
    lambda c: c['services']['secure-quality-gates'].update(privileged=True),
    lambda c: c['services']['native-qa-controller'].update(restart='always'),
    lambda c: c['services']['trusted-gateway']['volumes'].append({'source': '/var/run/docker.sock'}),
    lambda c: c['services']['native-qa-controller']['environment'].update(MAW_QA_TEST_COMMAND_JSON='["python","-B","-c","raise SystemExit(1)"]'),
    lambda c: c['services']['native-qa-controller']['environment'].update(MAW_QA_TEST_COMMAND_JSON='not-json'),
    lambda c: c['services']['native-qa-controller']['environment'].pop('MAW_QA_SERVICE_ADMIN_KEY_FILE'),
    lambda c: c['services']['native-worker']['environment'].pop('MAW_OPENROUTER_KEY_FILE'),
    lambda c: c['services']['secure-orchestration']['environment'].pop('MAW_ORCH_QA_SIGNING_KEY_FILE'),
])
def test_live_policy_rejects_partial_or_unsafe_stack(mutation):
    config = complete_config()
    mutation(config)
    with pytest.raises(ValueError):
        policy.validate_live_sdlc(config)


def test_live_mode_uses_all_overlays_not_default_dev_compose():
    assert len(policy.LIVE_OVERLAYS) == 5
    assert 'docker-compose.yml' not in policy.LIVE_OVERLAYS
    assert 'compose.native-openrouter-egress.yml' in policy.LIVE_OVERLAYS
    assert 'compose.native-trusted-git-runtime.yml' in policy.LIVE_OVERLAYS
