"""Black-box local MVP API acceptance through the *frontend* reverse proxy.

Runs after Docker Compose health, without mocks and without any paid provider calls.
The create/verify phases straddle a real orchestration container restart.
State file contains only smoke resource IDs, not credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


SCHEMA = {
    "type": "object", "required": ["summary"],
    "properties": {"summary": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}
DEFINITION = {
    "schema_version": "1.0",
    "metadata": {"name": "Compose acceptance", "version": 1,
                 "created_at": "2026-10-16T00:00:00Z"},
    "nodes": [
        {"id": "start", "type": "start", "label": "Start",
         "position": {"x": 0, "y": 0}, "config": {}},
        {"id": "end", "type": "end", "label": "End",
         "position": {"x": 100, "y": 0}, "config": {}},
    ],
    "edges": [],
}


def request(base: str, method: str, path: str, data: dict | None = None,
            status: int = 200) -> dict:
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + "/api/v1" + path,
        method=method, data=payload,
        headers={"Accept": "application/json",
                 **({"Content-Type": "application/json"} if payload is not None else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            actual = response.status
            body = response.read(524288)
    except urllib.error.HTTPError as exc:
        actual, body = exc.code, exc.read(524288)
    if actual != status:
        # Only report path/status, never echo response bodies or credentials.
        raise AssertionError(f"{method} {path.split('?')[0]}: HTTP {actual}, expected {status}")
    return json.loads(body) if body else {}


def find(items: list[dict], key: str, value: str) -> dict:
    return next((item for item in items if item.get(key) == value), None) or (
        (_ for _ in ()).throw(AssertionError(f"Missing expected {key} in API list"))
    )


def create(base: str, state_file: Path) -> None:
    tag = uuid4().hex[:10]
    project = request(base, "POST", "/projects",
                      {"name": "acceptance-" + tag, "description": "real HTTP smoke"}, 201)
    project_id = project["id"]
    definition = request(base, "POST", "/workflows/definitions",
                         {"name": "definition-" + tag, "definition": DEFINITION}, 201)
    version = request(
        base, "POST", f"/workflows/definitions/{definition['id']}/versions",
        {"definition_snapshot": DEFINITION, "changelog": "Compose smoke"}, 201,
    )
    assert version["version_number"] == 1
    contract = request(base, "POST", "/contracts",
                       {"name": "contract-" + tag, "project_id": project_id,
                        "schema": SCHEMA}, 201)
    agent = request(base, "POST", "/agents/register",
                    {"name": "agent-" + tag}, 201)
    invalid_run = request(base, "POST", "/workflows/runs", {
        "project_id": project_id, "name": "invalid-" + tag,
        "retry_policy": {"max_attempts": 1},
        "tasks": [{"title": "contract-rejection", "contract_id": contract["id"]}],
    }, 201)
    invalid_task = request(base, "GET",
                           f"/workflows/runs/{invalid_run['id']}/tasks")["items"][0]
    invalid_attempt = request(base, "POST", f"/tasks/{invalid_task['id']}/claim",
                              {"agent_id": agent["id"]}, 201)
    denied = request(
        base, "POST", f"/tasks/{invalid_task['id']}/attempts/{invalid_attempt['id']}/submit"
        f"?agent_id={agent['id']}", {"output": {"success": True}}, 200,
    )
    assert denied["status"] == "verification_failed"
    assert request(base, "GET", f"/tasks/{invalid_task['id']}")["status"] == "failed"
    assert request(base, "GET", f"/workflows/runs/{invalid_run['id']}")["status"] == "failed"

    valid_run = request(base, "POST", "/workflows/runs", {
        "project_id": project_id, "name": "valid-" + tag,
        "retry_policy": {"max_attempts": 1},
        "tasks": [{"title": "contract-accepted", "contract_id": contract["id"]}],
    }, 201)
    task = request(base, "GET", f"/workflows/runs/{valid_run['id']}/tasks")["items"][0]
    assert task["status"] == "pending"
    attempt = request(base, "POST", f"/tasks/{task['id']}/claim",
                      {"agent_id": agent["id"]}, 201)
    accepted = request(
        base, "POST", f"/tasks/{task['id']}/attempts/{attempt['id']}/submit"
        f"?agent_id={agent['id']}", {"output": {"summary": "verified by server contract"}}, 200,
    )
    assert accepted["status"] == "completed"
    assert request(base, "GET", f"/workflows/runs/{valid_run['id']}")["status"] == "completed"

    snapshot = {
        "project_id": project_id, "definition_id": definition["id"],
        "version_number": version["version_number"],
        "run_id": valid_run["id"], "task_id": task["id"],
        "invalid_run_id": invalid_run["id"], "invalid_task_id": invalid_task["id"],
    }
    state_file.write_text(json.dumps(snapshot))
    print("LOCAL_API_ACCEPTANCE create: PASS (project, definition/version, "
          "Contract Gate rejection/acceptance, task/run state)")


def verify(base: str, state_file: Path) -> None:
    state = json.loads(state_file.read_text())
    project_id = state["project_id"]
    projects = request(base, "GET", "/projects")
    assert any(p["id"] == project_id for p in projects)
    wf = request(base, "GET", f"/workflows/definitions/{state['definition_id']}")
    assert wf["definition"] == DEFINITION
    versions = request(
        base, "GET", f"/workflows/definitions/{state['definition_id']}/versions",
    )["items"]
    assert any(v["version_number"] == state["version_number"] for v in versions)
    run = request(base, "GET", f"/workflows/runs/{state['run_id']}")
    task = request(base, "GET", f"/tasks/{state['task_id']}")
    assert run["status"] == "completed" and task["status"] == "completed"
    assert task["output_data"]["summary"] == "verified by server contract"
    invalid_run = request(base, "GET", f"/workflows/runs/{state['invalid_run_id']}")
    invalid_task = request(base, "GET", f"/tasks/{state['invalid_task_id']}")
    assert invalid_run["status"] == "failed" and invalid_task["status"] == "failed"
    assert len(request(base, "GET",
                       f"/tasks/{state['task_id']}/attempts")) == 1
    print("LOCAL_API_ACCEPTANCE restart: PASS (persistent project, workflow revision, "
          "accepted/rejected Contract Gate evidence)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("create", "verify"))
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "create":
        create(args.base_url, args.state_file)
    else:
        verify(args.base_url, args.state_file)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, KeyError, ValueError) as exc:
        print(f"LOCAL_API_ACCEPTANCE FAILED: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
