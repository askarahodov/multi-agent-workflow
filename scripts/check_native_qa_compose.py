"""Offline Docker Compose policy check for explicit native QA runtime.

No image build, key material, Docker daemon containers, provider calls or
network requests are required. Fails closed on accidental dev/auth fallback.
"""
from __future__ import annotations

import json
import argparse
import subprocess
import sys


COMPOSE = (
    "docker", "compose", "--project-directory", ".",
    "-f", "deploy/compose/secure/compose.trusted-sqlite-control.yml",
    "-f", "deploy/compose/secure/compose.native-worker-runtime.yml",
    "-f", "deploy/compose/secure/compose.native-qa-runtime.yml",
    "--profile", "trusted-sqlite-control",
    "--profile", "native-worker-runtime",
    "--profile", "native-qa-runtime",
)


LIVE_OVERLAYS = (
    'deploy/compose/secure/compose.native-autonomous-dispatch.yml',
    'deploy/compose/secure/compose.native-autonomous-qa-dispatch.yml',
    'deploy/compose/secure/compose.native-trusted-git-runtime.yml',
    'deploy/compose/secure/compose.native-openrouter-egress.yml',
    'deploy/compose/secure/compose.release-approval.yml',
)


def validate(config: dict) -> None:
    services = config.get("services", {})
    required = {
        "secure-orchestration", "trusted-gateway", "native-worker",
        "secure-quality-gates", "native-qa-controller",
    }
    if not required.issubset(services):
        raise ValueError("Native QA Compose services are incomplete")
    for name in required:
        service = services[name]
        if (service.get("privileged", False) is not False
                or service.get("read_only") is not True
                or service.get("cap_drop") != ["ALL"]
                or service.get("restart", "no") != "no"):
            raise ValueError(f"QA profile lacks least-privilege boundary: {name}")
        if any("/var/run/docker.sock" in str(v) for v in service.get("volumes", [])):
            raise ValueError("Docker socket cannot be mounted in native QA services")
        env = service.get("environment", {})
        if env.get("AUTH_ENABLED") == "false":
            raise ValueError("Dev-mode AUTH disabled in native QA stack")
        if any(k in env for k in (
            "ADMIN_API_KEYS", "WRITE_API_KEYS", "READ_API_KEYS",
            "ORCH_QA_ATTESTATION_KEY", "QG_QA_ATTESTATION_KEY",
        )):
            raise ValueError("Raw API or signing secrets in Compose environment")
    orchestrator = services["secure-orchestration"]["environment"]
    if orchestrator.get("AUTH_ENABLED") != "true":
        raise ValueError("Secure orchestration must authenticate requests")
    if orchestrator.get("ORCH_ATTEMPT_LEASE_ENABLED") != "1":
        raise ValueError("Native lease fencing required")
    qg = services["secure-quality-gates"]["environment"]
    if qg.get("AUTH_ENABLED") != "true" or qg.get("MAW_SECURE_QG_ENABLED") != "1":
        raise ValueError("QG must be an authenticated dedicated service")
    worker = services["native-worker"]
    forbidden = ("/run/maw-secrets/qa-", "/srv/maw/qa-", "/srv/maw/operator-source")
    if any(any(prefix in str(v) for prefix in forbidden) for v in worker.get("volumes", [])):
        raise ValueError("Native worker must never have operator QA mounts")
    controller = services["native-qa-controller"]
    if controller.get("command")[-1] != "preflight":
        raise ValueError("QA controller cannot run automatically on Compose up")
    networks = config.get("networks", {})
    if not any(item.get("internal") is True for item in networks.values()):
        raise ValueError("Trusted QA control network must be internal")


def validate_live_sdlc(config: dict) -> None:
    """Check actual merged runtime, never infer overlay safety from YAML alone."""
    services = config.get('services', {})
    required = ('native-worker', 'trusted-gateway', 'secure-orchestration',
                'native-qa-controller', 'secure-quality-gates')
    if any(name not in services for name in required):
        raise ValueError('Live SDLC Compose missing protected services')
    worker = services['native-worker']
    gateway = services['trusted-gateway']
    qa = services['native-qa-controller']
    control = services['secure-orchestration']
    we, ge, qe, ce = (service.get('environment', {}) for service in
                      (worker, gateway, qa, control))
    if (we.get('MAW_TRUSTED_GIT_ENABLED') != '1'
            or ge.get('MAW_GATEWAY_GIT_ENABLED') != '1'
            or qe.get('MAW_QA_AUTONOMOUS_ENABLED') != '1'):
        raise ValueError('Live Git/QA activation incomplete')
    if (worker.get('command', [])[-1:] != ['dispatch']
            or qa.get('command', [])[-1:] != ['dispatch']):
        raise ValueError('Live autonomous dispatch not configured')
    # The default QA command is deliberately negative. Running it under
    # autonomous dispatch cannot produce a valid independent QA receipt.
    try:
        qa_command = json.loads(qe.get('MAW_QA_TEST_COMMAND_JSON', 'null'))
    except (TypeError, ValueError):
        raise ValueError('Autonomous QA test command malformed') from None
    if (type(qa_command) is not list or not qa_command
            or any(type(arg) is not str or not arg for arg in qa_command)
            or qa_command == ['python', '-B', '-c', 'raise SystemExit(1)']):
        raise ValueError('Autonomous QA requires explicit real test command')
    # Complete trusted profile requires every service to load private keys
    # from files. An absent file path must fail at static readiness time.
    for env, names in (
        (we, ('MAW_NATIVE_WORKER_API_KEY_FILE', 'MAW_TRUSTED_GATEWAY_KEY_FILE',
              'MAW_OPENROUTER_KEY_FILE')),
        (ge, ('MAW_GATEWAY_KEY_FILE',)),
        (qe, ('MAW_QA_ORCH_ADMIN_KEY_FILE', 'MAW_QA_SERVICE_ADMIN_KEY_FILE')),
        (ce, ('MAW_ORCH_API_KEY_FILE', 'MAW_ORCH_QA_ADMIN_KEY_FILE',
              'MAW_ORCH_QA_SIGNING_KEY_FILE')),
    ):
        if any(type(env.get(name)) is not str or not env[name].startswith('/')
               for name in names):
            raise ValueError('Trusted runtime credential file configuration missing')
    if not ce.get('MAW_ORCH_RELEASE_APPROVAL_KEY_FILE'):
        raise ValueError('Operator release approval missing')
    if not ge.get('MAW_GATEWAY_GIT_SOURCE_REPOSITORY') or not ge.get('MAW_GATEWAY_GIT_WORKTREE_HOME'):
        raise ValueError('Trusted Git directories missing')
    targets = {v.get('target') for v in gateway.get('volumes', []) if isinstance(v, dict)}
    if not {ge['MAW_GATEWAY_GIT_SOURCE_REPOSITORY'], ge['MAW_GATEWAY_GIT_WORKTREE_HOME']}.issubset(targets):
        raise ValueError('Git repository/worktree mounts missing on gateway')
    for name in ('native-worker', 'secure-orchestration'):
        if any(any(token in str(v) for token in ('/srv/maw/operator-source', '/srv/maw/git-attempts'))
               for v in services[name].get('volumes', [])):
            raise ValueError('Git data leaked outside trusted gateway')
    networks = config.get('networks', {})
    private = {name for name, item in networks.items() if item.get('internal') is True}
    external = {name for name, item in networks.items() if item.get('internal') is not True}
    if not private or not external:
        raise ValueError('Live provider/control network separation missing')
    def joined(name):
        value = services[name].get('networks', {})
        return set(value) if isinstance(value, (list, dict)) else set()
    if not joined('native-worker').intersection(private) or not joined('native-worker').intersection(external):
        raise ValueError('Worker lacks protected control or provider egress')
    for name in required:
        if name != 'native-worker' and joined(name).intersection(external):
            raise ValueError('Provider egress leaked into protected service')
    for name in required:
        service = services[name]
        if service.get('privileged') is True or service.get('read_only') is not True or service.get('restart', 'no') != 'no':
            raise ValueError('Live SDLC service privilege/restart boundary invalid')
        if any('docker.sock' in str(v) for v in service.get('volumes', [])):
            raise ValueError('Docker socket exposed to live SDLC')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Protected Compose policy (offline)')
    parser.add_argument('--live-sdlc', action='store_true')
    args = parser.parse_args(argv)
    overlays = tuple(part for path in LIVE_OVERLAYS for part in ('-f', path)) if args.live_sdlc else ()
    try:
        result = subprocess.run(
            [*COMPOSE, *overlays, "config", "--format", "json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True, timeout=45,
        )
        config = json.loads(result.stdout)
        if args.live_sdlc:
            validate_live_sdlc(config)
        else:
            validate(config)
    except subprocess.CalledProcessError:
        print("Native QA Compose config invalid (check YAML/volumes/profiles)", file=sys.stderr)
        return 3
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
        # Errors are authored static diagnostics, never print docker config
        # output or any operator-provided environment/secret values.
        detail = str(exc) if type(exc) is ValueError else type(exc).__name__
        print("Native QA Compose policy FAIL_CLOSED: " + detail[:120], file=sys.stderr)
        return 3
    print("Native SDLC Compose static policy OK (no containers started)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
