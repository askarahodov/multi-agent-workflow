"""Offline Docker Compose policy check for explicit native QA runtime.

No image build, key material, Docker daemon containers, provider calls or
network requests are required. Fails closed on accidental dev/auth fallback.
"""
from __future__ import annotations

import json
import subprocess
import sys


COMPOSE = (
    "docker", "compose",
    "-f", "compose.trusted-sqlite-control.yml",
    "-f", "compose.native-worker-runtime.yml",
    "-f", "compose.native-qa-runtime.yml",
    "--profile", "trusted-sqlite-control",
    "--profile", "native-worker-runtime",
    "--profile", "native-qa-runtime",
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
        if (service.get("privileged") is not False
                or service.get("read_only") is not True
                or service.get("cap_drop") != ["ALL"]
                or service.get("restart") != "no"):
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


def main() -> int:
    try:
        result = subprocess.run(
            [*COMPOSE, "config", "--format", "json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True, timeout=45,
        )
        validate(json.loads(result.stdout))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        print("Native QA Compose policy FAIL_CLOSED", file=sys.stderr)
        return 3
    print("Native QA Compose static policy OK (no containers started)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
