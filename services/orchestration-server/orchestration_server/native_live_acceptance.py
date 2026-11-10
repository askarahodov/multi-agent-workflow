"""Read-only post-run evidence audit for operator-approved native SDLC acceptance.

No provider, worker, tool, git, QA-signing or release mutation entrypoint.
This checks *server-reported* evidence; it cannot independently prove that a
live OpenRouter request occurred, that a Git object exists on disk, or that a
protected deployment survived restart. Those need separate operator evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import re
import ssl
import sys
from typing import Any
from urllib.parse import quote, urlsplit

from .native_profile_binding import UUID
from .published_graph import compile_published_graph

STAGES = (
    "research", "architecture", "implementation", "tests",
    "review", "security", "release-prep",
)
SHA = re.compile(r"^[0-9a-f]{40}$")
GATES = ("tester", "reviewer", "security")
MAX_PAGES = 100
PAGE_LIMIT = 100

Read = Callable[[str, dict[str, str | int] | None], Awaitable[Any]]


class EvidenceAuditError(ValueError):
    """Static error code only: no server payloads, secrets or IDs are logged."""


def _require(condition: Any, code: str) -> None:
    if not condition:
        raise EvidenceAuditError(code)


def _identifier(value: Any) -> bool:
    return type(value) is str and UUID.fullmatch(value) is not None


def _mapping(value: Any, code: str) -> dict[str, Any]:
    _require(type(value) is dict, code)
    return value


def _get(field: dict[str, Any], key: str, code: str) -> str:
    value = field.get(key)
    _require(_identifier(value), code)
    return value


async def _read(read: Read, path: str, params: dict[str, str | int] | None = None) -> Any:
    # The run/version/QA endpoints return objects, while attempts and
    # Git evidence return JSON arrays. Validate each at its call site.
    try:
        return await read(path, params)
    except Exception:
        raise EvidenceAuditError("REMOTE_EVIDENCE_UNAVAILABLE") from None


async def _pages(read: Read, path: str, name: str) -> list[dict]:
    entries: list[dict] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    after: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if after is not None:
            params["after"] = after
        page = _mapping(await _read(read, path, params), "INVALID_" + name + "_PAGE")
        items = page.get("items")
        _require(type(items) is list and len(items) <= PAGE_LIMIT,
                 "INVALID_" + name + "_PAGE")
        for item in items:
            _require(type(item) is dict and _identifier(item.get("id")) and
                     item["id"] not in seen_ids, "INVALID_" + name + "_IDENTITY")
            seen_ids.add(item["id"])
            entries.append(item)
        cursor = page.get("next_cursor")
        if cursor is None:
            return entries
        _require(
            type(cursor) is str and 0 < len(cursor) <= 512 and
            cursor not in seen_cursors and bool(items),
            "INVALID_" + name + "_CURSOR",
        )
        seen_cursors.add(cursor)
        after = cursor
    raise EvidenceAuditError("EXCESSIVE_" + name + "_PAGES")


@dataclass(frozen=True)
class EvidenceSummary:
    status: str
    published_stages: int
    verified_contracts: int
    qa_receipts: int
    worker_reported_git_artifacts: int
    operator_release_approval: bool
    actual_provider_call: str = "NOT_PROVEN_BY_READ_API"
    git_object_readback: str = "NOT_PROVEN_BY_READ_API"
    compose_restart: str = "NOT_PROVEN_BY_READ_API"


async def audit_native_sdlc_run(read: Read, *, run_id: str, project_id: str) -> EvidenceSummary:
    """Verify one complete published seven-stage run from authoritative read APIs.

    Even success returns REVIEW_REQUIRED rather than LIVE_ACCEPTED. The
    operator independently verifies provider logs, trusted Git objects and
    restart evidence, then seeks separate review/signoff.
    """
    _require(_identifier(run_id) and _identifier(project_id), "INVALID_OPERATOR_SCOPE")
    run = _mapping(await _read(read, "/workflows/runs/" + quote(run_id, safe="")),
                   "INVALID_RUN_RESPONSE")
    _require(run.get("id") == run_id and run.get("project_id") == project_id,
             "RUN_PROJECT_MISMATCH")
    _require(run.get("status") == "completed", "RUN_NOT_COMPLETED")
    data = _mapping(run.get("input_data"), "RUN_PUBLICATION_MISSING")
    definition_id = _get(data, "_workflow_definition_id", "RUN_PUBLICATION_MISSING")
    version_id = _get(data, "_workflow_version_id", "RUN_PUBLICATION_MISSING")

    versions = await _pages(
        read, "/workflows/definitions/" + quote(definition_id, safe="") + "/versions",
        "VERSION",
    )
    version = next((v for v in versions if v["id"] == version_id), None)
    _require(version is not None and all(
        v.get("workflow_definition_id") == definition_id and
        type(v.get("version_number")) is int and v["version_number"] > 0
        for v in versions
    ), "PUBLISHED_VERSION_UNTRUSTED")
    try:
        specs = compile_published_graph(version.get("definition_snapshot"))
    except Exception:
        raise EvidenceAuditError("PUBLISHED_GRAPH_INVALID") from None
    _require(len(specs) == len(STAGES) and all(
        spec["title"].strip().lower() == stage and
        _identifier(spec["contract_id"]) and
        type(spec.get("node_id")) is str and bool(spec["node_id"])
        for spec, stage in zip(specs, STAGES)
    ), "SEVEN_STAGE_GRAPH_UNPROVEN")

    tasks = await _pages(read, "/workflows/runs/" + quote(run_id, safe="") + "/tasks", "TASK")
    by_node = {task.get("node_id"): task for task in tasks}
    _require(len(tasks) == len(STAGES) and len(by_node) == len(tasks), "STAGE_TASK_COUNT_INVALID")
    for spec in specs:
        task = by_node.get(spec["node_id"])
        _require(
            type(task) is dict and task.get("workflow_run_id") == run_id and
            type(task.get("title")) is str and
            task["title"].strip().lower() == spec["title"].lower() and
            task.get("contract_id") == spec["contract_id"] and
            task.get("status") == "completed" and
            type(task.get("attempt_count")) is int and task["attempt_count"] > 0 and
            type(task.get("input_data")) is dict and
            task["input_data"].get("workflow_node_id") == spec["node_id"] and
            task["input_data"].get("workflow_agent_reference") ==
            spec["input_data"]["workflow_agent_reference"],
            "STAGE_OWNERSHIP_OR_CONTRACT_INVALID",
        )

    gate_runs: set[str] = set()
    git_artifacts = 0
    for idx, spec in enumerate(specs):
        task = by_node[spec["node_id"]]
        tid = task["id"]
        if idx:
            upstream = task["input_data"].get("_maw_upstream")
            _require(type(upstream) is list and bool(upstream) and
                     type(upstream[-1]) is dict and
                     upstream[-1].get("task_id") == by_node[specs[idx - 1]["node_id"]]["id"],
                     "STAGE_HANDOFF_UNPROVEN")
        attempts = await _read(read, "/tasks/" + quote(tid, safe="") + "/attempts")
        # This endpoint is an unpaginated bounded list, unlike the run catalog.
        _require(type(attempts) is list and 1 <= len(attempts) <= 100,
                 "ATTEMPT_HISTORY_INVALID")
        attempt_ids: set[str] = set()
        finished: list[dict] = []
        for attempt in attempts:
            _require(type(attempt) is dict and _identifier(attempt.get("id")) and
                     attempt.get("task_id") == tid and attempt["id"] not in attempt_ids,
                     "ATTEMPT_IDENTITY_INVALID")
            attempt_ids.add(attempt["id"])
            if attempt.get("status") == "completed":
                _require(type(attempt.get("verification_result")) is dict and
                         attempt["verification_result"].get("valid") is True,
                         "CONTRACT_GATE_UNVERIFIED")
                finished.append(attempt)
        _require(len(finished) == 1, "FINAL_ATTEMPT_NOT_UNIQUE")
        attempt_id = finished[0]["id"]

        evidence = await _read(read, "/tasks/" + quote(tid, safe="") + "/git-evidence")
        _require(type(evidence) is list and 1 <= len(evidence) <= 100,
                 "GIT_EVIDENCE_MISSING")
        matching = [entry for entry in evidence if
                    type(entry) is dict and entry.get("attempt_id") == attempt_id]
        _require(len(matching) == 1, "GIT_ATTEMPT_MISMATCH")
        artifact = matching[0]
        paths = artifact.get("changed_paths")
        sha = artifact.get("commit_sha")
        _require(artifact.get("task_id") == tid and
                 artifact.get("provenance") == "worker_reported" and
                 type(sha) is str and SHA.fullmatch(sha) and
                 type(paths) is list and 1 <= len(paths) <= 100 and
                 all(type(path) is str and 0 < len(path) <= 4096 and
                     not path.startswith("/") and "\\" not in path and
                     ".." not in path.split("/") and "" not in path.split("/")
                     for path in paths),
                 "GIT_EVIDENCE_INVALID")
        git_artifacts += 1

        qa = _mapping(
            await _read(read, "/tasks/" + quote(tid, safe="") + "/qa-attestation"),
            "INDEPENDENT_QA_UNVERIFIED",
        )
        gate_ids = qa.get("gate_run_ids")
        _require(qa.get("task_id") == tid and qa.get("status") == "verified" and
                 qa.get("attempt_id") == attempt_id and
                 qa.get("commit_sha") == sha and
                 type(qa.get("issued_by")) is str and bool(qa["issued_by"].strip()) and
                 type(gate_ids) is dict and set(gate_ids) == set(GATES) and
                 all(_identifier(gate_ids[g]) and gate_ids[g] not in gate_runs
                     for g in GATES) and len(set(gate_ids.values())) == len(GATES),
                 "INDEPENDENT_QA_UNVERIFIED")
        gate_runs.update(gate_ids.values())

    approval = _mapping(await _read(
        read, "/workflows/runs/" + quote(run_id, safe="") + "/release-approval",
    ), "HUMAN_APPROVAL_NOT_CONFIRMED")
    timestamp = approval.get("approved_at")
    _require(
        approval.get("run_id") == run_id and approval.get("required") is True and
        approval.get("status") == "approved" and type(timestamp) is str,
        "HUMAN_APPROVAL_NOT_CONFIRMED",
    )
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        _require(dt.tzinfo is not None and dt.utcoffset() is not None,
                 "HUMAN_APPROVAL_NOT_CONFIRMED")
    except (ValueError, OverflowError):
        raise EvidenceAuditError("HUMAN_APPROVAL_NOT_CONFIRMED") from None
    return EvidenceSummary(
        status="REVIEW_REQUIRED_EVIDENCE_PRESENT",
        published_stages=len(specs), verified_contracts=len(specs),
        qa_receipts=len(specs),
        worker_reported_git_artifacts=git_artifacts,
        operator_release_approval=True,
    )


async def _audit_cli(run_id: str, project_id: str) -> EvidenceSummary:
    import httpx

    # Reuse the worker's private-key ownership and trusted TLS preflight;
    # unlike the worker this command neither loads OpenRouter credentials
    # nor constructs a runner or issues a single mutation.
    from .native_worker_bootstrap import config_from_env
    config = config_from_env()
    parsed = urlsplit(config.server_url)
    _require(parsed.scheme == "https" and not config.allow_loopback_http and
             bool(config.orchestration_ca_file),
             "PROTECTED_TLS_CONFIG_REQUIRED")
    context = ssl.create_default_context(cafile=config.orchestration_ca_file)
    async with httpx.AsyncClient(
        base_url=config.server_url.rstrip("/"), verify=context,
        headers={"X-API-Key": config.api_key}, timeout=15,
        follow_redirects=False, trust_env=False,
    ) as client:
        async def read(path: str, params: dict[str, str | int] | None = None) -> Any:
            response = await client.get("/api/v1" + path, params=params)
            if response.status_code != 200:
                raise EvidenceAuditError("REMOTE_EVIDENCE_UNAVAILABLE")
            return response.json()
        return await audit_native_sdlc_run(
            read, run_id=run_id, project_id=project_id,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only native SDLC post-run evidence audit (no paid provider calls)",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(_audit_cli(args.run_id, args.project_id))
    except EvidenceAuditError as exc:
        print("LIVE_SDLC_EVIDENCE_FAIL_CLOSED " + str(exc), file=sys.stderr)
        return 3
    except Exception:
        # No HTTP body, local secret filename, exception or task data in logs.
        print("LIVE_SDLC_EVIDENCE_FAIL_CLOSED CONFIG_OR_TRANSPORT", file=sys.stderr)
        return 3
    print(json.dumps(asdict(summary), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
