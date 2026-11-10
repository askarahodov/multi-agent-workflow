"""Offline tests for the read-only post-run acceptance evidence auditor."""
from __future__ import annotations

import copy
import uuid

import pytest

from orchestration_server.native_live_acceptance import (
    STAGES, EvidenceAuditError, audit_native_sdlc_run, main,
)


def uid() -> str:
    return str(uuid.uuid4())


def acceptance_fixture():
    project_id, run_id, definition_id, version_id = (uid() for _ in range(4))
    contract_id = uid()
    config = {
        "agent_definition_id": uid(), "model_profile_id": uid(),
        "tool_policy_id": uid(),
    }
    nodes = [
        {"id": "start", "type": "start", "label": "start",
         "position": {"x": 0, "y": 0}, "config": {}},
    ]
    for index, stage in enumerate(STAGES):
        nodes.extend([
            {"id": f"node-{index}", "type": "agent", "label": stage,
             "position": {"x": index * 200 + 100, "y": 0}, "config": config.copy()},
            {"id": f"gate-{index}", "type": "gate", "label": stage + " gate",
             "position": {"x": index * 200 + 200, "y": 0},
             "config": {"gate_type": "automatic", "contract_id": contract_id}},
        ])
    nodes.append({"id": "end", "type": "end", "label": "end",
                  "position": {"x": 2000, "y": 0}, "config": {}})
    edges = [
        {"id": f"edge-{i}", "source_node_id": nodes[i]["id"],
         "target_node_id": nodes[i + 1]["id"], "output_mapping": {},
         "on_error": "fail", "max_retries": 0}
        for i in range(len(nodes) - 1)
    ]
    snapshot = {
        "schema_version": "1.0",
        "metadata": {"name": "Protected seven-stage run", "version": 1,
                     "created_at": "2026-11-10T00:00:00Z"},
        "nodes": nodes, "edges": edges,
    }
    endpoints = {
        f"/workflows/runs/{run_id}": {
            "id": run_id, "project_id": project_id, "status": "completed",
            "input_data": {"_workflow_definition_id": definition_id,
                           "_workflow_version_id": version_id},
        },
        f"/workflows/definitions/{definition_id}/versions": {
            "items": [{"id": version_id, "workflow_definition_id": definition_id,
                       "version_number": 1, "definition_snapshot": snapshot}],
            "next_cursor": None,
        },
        f"/workflows/runs/{run_id}/tasks": {"items": [], "next_cursor": None},
        f"/workflows/runs/{run_id}/release-approval": {
            "run_id": run_id, "required": True, "status": "approved",
            "approved_at": "2026-11-10T13:00:00Z",
        },
    }
    stages = []
    for index, stage in enumerate(STAGES):
        tid, aid = uid(), uid()
        task = {
            "id": tid, "node_id": f"node-{index}", "workflow_run_id": run_id,
            "title": stage, "contract_id": contract_id,
            "status": "completed", "attempt_count": 1,
            "input_data": {
                "workflow_node_id": f"node-{index}",
                "workflow_agent_reference": config.copy(),
            },
        }
        if index:
            task["input_data"]["_maw_upstream"] = [
                {"task_id": stages[-1]["id"], "summary": "verified handoff"},
            ]
        endpoints[f"/workflows/runs/{run_id}/tasks"]["items"].append(task)
        endpoints[f"/tasks/{tid}/attempts"] = [
            {"id": aid, "task_id": tid, "status": "completed",
             "verification_result": {"valid": True}},
        ]
        sha = f"{index + 1:040x}"
        endpoints[f"/tasks/{tid}/git-evidence"] = [
            {"task_id": tid, "attempt_id": aid, "commit_sha": sha,
             "provenance": "worker_reported",
             "changed_paths": [f"out/{stage}.txt"]},
        ]
        endpoints[f"/tasks/{tid}/qa-attestation"] = {
            "task_id": tid, "attempt_id": aid,
            "status": "verified", "commit_sha": sha,
            "issued_by": "independent-controller",
            "gate_run_ids": {role: uid() for role in ("tester", "reviewer", "security")},
        }
        stages.append(task)
    return endpoints, project_id, run_id, definition_id, version_id, stages


class FakeControlPlane:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __call__(self, path, params=None):
        self.calls.append((path, params))
        return self.responses[path]


@pytest.mark.asyncio
async def test_verified_server_evidence_is_review_ready_not_claimed_live():
    responses, project_id, run_id, *_ = acceptance_fixture()
    api = FakeControlPlane(responses)
    summary = await audit_native_sdlc_run(api, run_id=run_id, project_id=project_id)
    assert summary.status == "REVIEW_REQUIRED_EVIDENCE_PRESENT"
    assert (summary.published_stages, summary.verified_contracts,
            summary.qa_receipts, summary.worker_reported_git_artifacts) == (7, 7, 7, 7)
    assert summary.operator_release_approval
    assert summary.actual_provider_call == "NOT_PROVEN_BY_READ_API"
    assert summary.git_object_readback == "NOT_PROVEN_BY_READ_API"
    assert summary.compose_restart == "NOT_PROVEN_BY_READ_API"
    assert all(path.startswith("/") and "preflight" not in path for path, _ in api.calls)
    assert len(api.calls) == 4 + 7 * 3


@pytest.mark.asyncio
@pytest.mark.parametrize(("case", "expected"), [
    ("foreign-project", "RUN_PROJECT_MISMATCH"),
    ("running", "RUN_NOT_COMPLETED"),
    ("manual-run", "RUN_PUBLICATION_MISSING"),
    ("foreign-version", "PUBLISHED_VERSION_UNTRUSTED"),
    ("unsupported-graph", "PUBLISHED_GRAPH_INVALID"),
    ("missing-stage", "SEVEN_STAGE_GRAPH_UNPROVEN"),
    ("missing-task", "STAGE_TASK_COUNT_INVALID"),
    ("foreign-task", "STAGE_OWNERSHIP_OR_CONTRACT_INVALID"),
    ("skipped-handoff", "STAGE_HANDOFF_UNPROVEN"),
    ("missing-attempt", "ATTEMPT_HISTORY_INVALID"),
    ("forged-contract", "CONTRACT_GATE_UNVERIFIED"),
    ("duplicate-completed", "FINAL_ATTEMPT_NOT_UNIQUE"),
    ("missing-git", "GIT_EVIDENCE_MISSING"),
    ("foreign-git", "GIT_ATTEMPT_MISMATCH"),
    ("invalid-git-path", "GIT_EVIDENCE_INVALID"),
    ("pending-qa", "INDEPENDENT_QA_UNVERIFIED"),
    ("foreign-qa-sha", "INDEPENDENT_QA_UNVERIFIED"),
    ("reused-qa-gate", "INDEPENDENT_QA_UNVERIFIED"),
    ("pending-approval", "HUMAN_APPROVAL_NOT_CONFIRMED"),
    ("approval-not-required", "HUMAN_APPROVAL_NOT_CONFIRMED"),
    ("duplicate-task", "INVALID_TASK_IDENTITY"),
    ("cursor-cycle", "INVALID_TASK_CURSOR"),
    ("malformed-page", "INVALID_TASK_PAGE"),
])
async def test_unsafe_or_partial_live_evidence_never_passes(case, expected):
    original, project_id, run_id, definition_id, version_id, stages = acceptance_fixture()
    data = copy.deepcopy(original)
    task = stages[0]
    first_id, second_id = stages[0]["id"], stages[1]["id"]
    if case == "foreign-project":
        data[f"/workflows/runs/{run_id}"]["project_id"] = uid()
    elif case == "running":
        data[f"/workflows/runs/{run_id}"]["status"] = "running"
    elif case == "manual-run":
        data[f"/workflows/runs/{run_id}"]["input_data"] = {}
    elif case == "foreign-version":
        data[f"/workflows/definitions/{definition_id}/versions"]["items"][0][
            "workflow_definition_id"
        ] = uid()
    elif case == "unsupported-graph":
        data[f"/workflows/definitions/{definition_id}/versions"]["items"][0][
            "definition_snapshot"
        ]["nodes"][1]["type"] = "shell"
    elif case == "missing-stage":
        data[f"/workflows/definitions/{definition_id}/versions"]["items"][0][
            "definition_snapshot"
        ]["nodes"][1]["label"] = "skipped"
    elif case == "missing-task":
        data[f"/workflows/runs/{run_id}/tasks"]["items"].pop()
    elif case == "foreign-task":
        data[f"/workflows/runs/{run_id}/tasks"]["items"][0]["contract_id"] = uid()
    elif case == "skipped-handoff":
        data[f"/workflows/runs/{run_id}/tasks"]["items"][1]["input_data"][
            "_maw_upstream"
        ] = []
    elif case == "missing-attempt":
        data[f"/tasks/{first_id}/attempts"] = []
    elif case == "forged-contract":
        data[f"/tasks/{first_id}/attempts"][0]["verification_result"]["valid"] = False
    elif case == "duplicate-completed":
        duplicate = data[f"/tasks/{first_id}/attempts"][0].copy()
        duplicate["id"] = uid()
        data[f"/tasks/{first_id}/attempts"].append(duplicate)
    elif case == "missing-git":
        data[f"/tasks/{first_id}/git-evidence"] = []
    elif case == "foreign-git":
        data[f"/tasks/{first_id}/git-evidence"][0]["attempt_id"] = uid()
    elif case == "invalid-git-path":
        data[f"/tasks/{first_id}/git-evidence"][0]["changed_paths"] = ["../escape"]
    elif case == "pending-qa":
        data[f"/tasks/{first_id}/qa-attestation"]["status"] = "pending"
    elif case == "foreign-qa-sha":
        data[f"/tasks/{first_id}/qa-attestation"]["commit_sha"] = "f" * 40
    elif case == "reused-qa-gate":
        data[f"/tasks/{second_id}/qa-attestation"]["gate_run_ids"] = data[
            f"/tasks/{first_id}/qa-attestation"
        ]["gate_run_ids"].copy()
    elif case == "pending-approval":
        data[f"/workflows/runs/{run_id}/release-approval"]["status"] = "pending"
    elif case == "approval-not-required":
        data[f"/workflows/runs/{run_id}/release-approval"]["required"] = False
    elif case == "duplicate-task":
        data[f"/workflows/runs/{run_id}/tasks"]["items"].append(
            data[f"/workflows/runs/{run_id}/tasks"]["items"][0].copy()
        )
    elif case == "cursor-cycle":
        data[f"/workflows/runs/{run_id}/tasks"]["next_cursor"] = "loop"
    elif case == "malformed-page":
        data[f"/workflows/runs/{run_id}/tasks"]["items"] = {"wrong": "type"}
    with pytest.raises(EvidenceAuditError, match=expected):
        await audit_native_sdlc_run(FakeControlPlane(data),
                                    run_id=run_id, project_id=project_id)


@pytest.mark.asyncio
async def test_readonly_transport_errors_are_redacted_and_fail_closed():
    _, project_id, run_id, *_ = acceptance_fixture()
    async def secret_bearing_failure(_path, _params=None):
        raise RuntimeError("SECRET_API_KEY_AND_PERSONAL_PROMPT")
    with pytest.raises(EvidenceAuditError, match="REMOTE_EVIDENCE_UNAVAILABLE") as caught:
        await audit_native_sdlc_run(secret_bearing_failure, run_id=run_id,
                                    project_id=project_id)
    assert "SECRET" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_invalid_scope_cli_never_attempts_live_requests(capsys):
    assert main(["--run-id", "foreign", "--project-id", "not-a-project"]) == 3
    output = capsys.readouterr()
    assert "FAIL_CLOSED" in output.err
    assert "foreign" not in output.err
    assert output.out == ""
