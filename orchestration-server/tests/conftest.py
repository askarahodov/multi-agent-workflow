"""Shared pytest fixtures for the orchestration server test suite.

Tests run against a real (file-backed) SQLite database so that durability and
restart behaviour can be exercised end to end: a fresh harness on the same URL
is exactly what a server restart looks like from the engine's point of view.
"""

from __future__ import annotations

import os

import pytest_asyncio

# Disable authentication for the test suite (auth is exercised separately).
os.environ["AUTH_ENABLED"] = "false"

from orchestration_server.db import build_engine, build_session_factory, create_all
from orchestration_server.engine import OrchestrationEngine
from orchestration_server.queries import OrchestrationQueries

# A JSON Schema (Draft 2020-12) used as a task contract throughout the tests.
SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "additionalProperties": False,
}


class Harness:
    """An engine + session factory bound to one database URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = None
        self.sf = None

    async def start(self) -> "Harness":
        self.engine = build_engine(self.url)
        await create_all(self.engine)
        self.sf = build_session_factory(self.engine)
        return self

    async def stop(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None

    @property
    def orch(self) -> OrchestrationEngine:
        return OrchestrationEngine(self.sf)

    @property
    def queries(self) -> OrchestrationQueries:
        return OrchestrationQueries(self.sf)


@pytest_asyncio.fixture
async def harness_factory(tmp_path):
    """Factory returning harnesses that all share one SQLite file URL."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'orchestration.db'}"
    started: list[Harness] = []

    async def _make() -> Harness:
        h = Harness(url)
        await h.start()
        started.append(h)
        return h

    yield _make

    for h in started:
        await h.stop()


@pytest_asyncio.fixture
async def harness(harness_factory) -> Harness:
    return await harness_factory()


async def seed_workflow(
    orch: OrchestrationEngine,
    queries: OrchestrationQueries,
    *,
    max_attempts: int = 1,
    with_contract: bool = True,
    task_count: int = 1,
    retry_base: float = 0.0,
):
    """Create a project, contract, agent and a run with N tasks.

    Returns ``(project, contract, agent, run, tasks)`` where ``tasks`` is sorted
    by the query helper's ordering.
    """
    project = await orch.create_project("proj")
    contract = None
    if with_contract:
        contract = await orch.create_contract(
            "contract", SUMMARY_SCHEMA, project_id=project.id
        )
    agent = await orch.register_agent("agent-1")
    specs = []
    for i in range(task_count):
        spec: dict = {"title": f"task-{i}"}
        if contract is not None:
            spec["contract_id"] = contract.id
        specs.append(spec)
    run = await orch.launch_run(
        project.id,
        "run",
        specs,
        retry_policy={
            "max_attempts": max_attempts,
            "base_delay_seconds": retry_base,
            "max_delay_seconds": retry_base,
            "backoff_multiplier": 1.0,
        },
    )
    tasks = await queries.list_tasks(run.id)
    return project, contract, agent, run, tasks
