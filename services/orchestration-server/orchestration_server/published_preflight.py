"""Read-only, server-owned preflight for immutable published workflow runs.

Preflight checks only facts available to orchestration's own database. It must
never present a registered agent, UUID-shaped profile, or passing graph compiler
as proof of a connected native worker, provider credentials or release approval.
The actual launch re-evaluates this gate before writing, and OrchestrationEngine
remains responsible for enforcing the contract and project constraints.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from .errors import ValidationError
from .models import Contract, Project, Workspace, WorkflowDefinition, WorkflowVersion
from .published_graph import compile_published_graph


async def inspect_published_run(
    session_factory: async_sessionmaker,
    definition: WorkflowDefinition,
    version: WorkflowVersion,
    *,
    project_id: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def record(code: str, status: str, detail: str) -> None:
        checks.append({"code": code, "status": status, "detail": detail})

    compiled: list[dict[str, Any]] = []
    if not definition.is_active:
        record("definition", "block", "Workflow definition is inactive")
    elif definition.project_id not in (None, project_id):
        record("definition", "block", "Workflow belongs to another project")
    else:
        record("definition", "pass", "Published definition belongs to the selected project")

    try:
        compiled = compile_published_graph(version.definition_snapshot)
    except ValidationError as exc:
        record("graph", "block", str(exc))
    else:
        record("graph", "pass", f"Immutable graph compiles into {len(compiled)} contracted tasks")

    async with session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            record("project", "block", "Selected project does not exist")
        else:
            record("project", "pass", "Selected project exists")

        if workspace_id is not None:
            workspace = await session.get(Workspace, workspace_id)
            if workspace is None or workspace.project_id != project_id:
                record("workspace", "block", "Selected workspace does not belong to the project")
            else:
                record("workspace", "pass", "Workspace belongs to the selected project")

        missing: list[str] = []
        foreign: list[str] = []
        for contract_id in sorted({task["contract_id"] for task in compiled}):
            contract = await session.get(Contract, contract_id)
            if contract is None:
                missing.append(contract_id)
            elif contract.project_id not in (None, project_id):
                foreign.append(contract_id)
        if missing:
            record("contracts", "block", "Missing Contract Gate references: " + ", ".join(missing))
        elif foreign:
            record("contracts", "block", "Contract Gate references belong to another project: " + ", ".join(foreign))
        elif compiled:
            record("contracts", "pass", "All Contract Gate references exist and match the project")

    # These deliberately remain UNKNOWN. Neither the editor's agent/model/tool
    # references nor the agents table proves that a native leased process is
    # online, has usable credentials, or is enforcing the selected policy.
    record("worker", "unknown", "Native worker connectivity and task lease availability are not verified")
    record("provider_policy", "unknown", "Model credentials, budgets, and Agent/ToolPolicy enforcement require live verification")
    record("release_approval", "unknown", "Independent QA and human release approval are not preflight attestations")
    return {
        "can_create_run": not any(check["status"] == "block" for check in checks),
        "execution_ready": False,
        "task_count": len(compiled),
        "workflow_definition_id": definition.id,
        "workflow_version_id": version.id,
        "checks": checks,
    }
