"""Real HTTPS/roles/SQLite-restart smoke from the QA controller container.

Run only against disposable auth-enabled Compose. It deliberately NEVER runs
an LLM provider, a shell tool, a QA tester command or a paid completion.
"""
from __future__ import annotations

import asyncio
import os
import ssl
import sys

import httpx

from .native_qa_controller import private_key, controller_from_env

PROJECT_NAME = "qa-tls-compose-restart-evidence"


def _check(response: httpx.Response, status: int, purpose: str):
    if response.status_code != status:
        raise RuntimeError(f"{purpose}: unexpected HTTP {response.status_code}")


async def check(mode: str) -> None:
    config, store, _, _ = controller_from_env()
    # Preconditions: Git is actually readable by UID10003 from mounted
    # operator storage; the preflight separately rejects symlinks/config.
    if not (store.repository / ".git").is_dir():
        raise RuntimeError("Trusted QA repository missing")
    if not store.home.is_dir():
        raise RuntimeError("QA checkout home missing")

    orch_ca = ssl.create_default_context(cafile=config.orch_ca_file)
    qg_ca = ssl.create_default_context(cafile=config.qg_ca_file)
    async with httpx.AsyncClient(
        base_url=config.orch_url, verify=orch_ca, trust_env=False,
        follow_redirects=False, timeout=10,
    ) as orch, httpx.AsyncClient(
        base_url=config.qg_url, verify=qg_ca, trust_env=False,
        follow_redirects=False, timeout=10,
    ) as qg:
        _check(await orch.get("/health"), 200, "orchestration TLS liveness")
        _check(await qg.get("/health"), 200, "QG TLS liveness")
        _check(await orch.get("/api/v1/projects"), 401,
               "orchestration must reject anonymous reads")
        _check(await qg.get("/api/v1/gates"), 401,
               "QG must reject anonymous reads")

        # Keys are different in this deployment. No cross-service privilege
        # propagation, including between two independent ADMIN identities.
        _check(await orch.get(
            "/api/v1/projects", headers={"X-API-Key": config.qg_admin_key},
        ), 401, "QG admin must not access orchestration")
        _check(await qg.get(
            "/api/v1/gates", headers={"X-API-Key": config.orch_admin_key},
        ), 401, "orchestration admin must not access QG")

        hdr_orch = {"X-API-Key": config.orch_admin_key}
        hdr_qg = {"X-API-Key": config.qg_admin_key}
        gate_resp = await qg.get("/api/v1/gates", headers=hdr_qg)
        _check(gate_resp, 200, "QG operator authorization")
        names = {g["name"] for g in gate_resp.json()}
        if not {"tester", "reviewer", "security"}.issubset(names):
            raise RuntimeError("Expected independent QG gates absent")

        if mode == "create":
            created = await orch.post(
                "/api/v1/projects",
                json={"name": PROJECT_NAME, "description": "isolated TLS smoke"},
                headers=hdr_orch,
            )
            _check(created, 201, "authenticated project creation")
            project = created.json()
            if project.get("name") != PROJECT_NAME or not project.get("id"):
                raise RuntimeError("Project response mismatch")
        else:
            listing = await orch.get("/api/v1/projects", headers=hdr_orch)
            _check(listing, 200, "authenticated project readback")
            projects = listing.json()
            if sum(p.get("name") == PROJECT_NAME for p in projects) != 1:
                raise RuntimeError("SQLite project did not survive container restart")

        # An authenticated operator is still subject to QG evidence checks:
        # absent signed runs cannot be fabricated into a valid QA receipt.
        unavailable = await qg.post(
            "/api/v1/tasks/nonexistent/qa-attestation",
            json={"attempt_id": "11111111-1111-1111-1111-111111111111",
                  "commit_sha": "a" * 40},
            headers=hdr_qg,
        )
        if unavailable.status_code != 409:
            raise RuntimeError("Missing signed QA evidence was not rejected")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("create", "verify"):
        return 2
    try:
        asyncio.run(check(sys.argv[1]))
    except (OSError, ValueError, httpx.HTTPError, RuntimeError, KeyError, TypeError):
        print("Protected native QA HTTPS smoke FAIL_CLOSED", file=sys.stderr)
        return 3
    print(f"Protected QA TLS/auth/SQLite {sys.argv[1]} smoke PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
