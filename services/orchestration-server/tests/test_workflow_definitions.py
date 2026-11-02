"""REST contract tests for the design-time workflow domain (ADR-101/102).

Covers the new ``/api/v1/workflows/definitions*`` endpoints that the frontend
depends on for real (non-mock) save/load of workflow definitions: create, read,
update, version snapshots and cursor pagination. Exercises the /api/v1 alias so
this is a true contract test against the canonical base path.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from orchestration_server.api import build_app
from orchestration_server.config import Settings

API = "/api/v1"

VALID_DEFINITION = {
    "schema_version": "1.0",
    "metadata": {"name": "demo", "version": 1, "created_at": "2026-10-09T00:00:00Z"},
    "nodes": [
        {"id": "n_start", "type": "start", "label": "Start", "position": {"x": 0, "y": 0}, "config": {}},
        {"id": "n_end", "type": "end", "label": "End", "position": {"x": 100, "y": 0}, "config": {}},
    ],
    "edges": [],
}


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'workflows.db'}",
        recover_on_startup=False,
    )


@pytest_asyncio.fixture
async def api(tmp_path):
    app = build_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def test_workflow_definition_crud_lifecycle_via_api_v1(api):
    # Create -> 201 + DTO with version=1
    r = await api.post(
        f"{API}/workflows/definitions",
        json={"name": "Test WF", "description": "integration", "definition": VALID_DEFINITION},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "Test WF"
    assert created["version"] == 1
    assert created["is_active"] is True
    assert created["definition"] == VALID_DEFINITION

    # Load -> identical DTO
    r = await api.get(f"{API}/workflows/definitions/{created['id']}")
    assert r.status_code == 200, r.text
    assert r.json() == created

    # Update -> revision bumped
    r = await api.put(
        f"{API}/workflows/definitions/{created['id']}",
        json={"name": "Test WF renamed", "is_active": False},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["version"] == 2
    assert updated["name"] == "Test WF renamed"
    assert updated["is_active"] is False
    assert updated["definition"] == VALID_DEFINITION


async def test_workflow_versions_snapshot_and_pagination(api):
    created = (
        await api.post(
            f"{API}/workflows/definitions",
            json={"name": "v-wf", "definition": VALID_DEFINITION},
        )
    ).json()

    for i, changelog in enumerate(["initial", "revision"], start=1):
        snapshot = dict(VALID_DEFINITION)
        snapshot["metadata"] = {**snapshot["metadata"], "version": i}
        r = await api.post(
            f"{API}/workflows/definitions/{created['id']}/versions",
            json={"definition_snapshot": snapshot, "changelog": changelog},
        )
        assert r.status_code == 201, r.text
        assert r.json()["version_number"] == i

    page = (
        await api.get(f"{API}/workflows/definitions/{created['id']}/versions")
    ).json()
    numbers = {v["version_number"] for v in page["items"]}
    assert numbers == {1, 2}
    by_number = {v["version_number"]: v for v in page["items"]}
    assert by_number[2]["changelog"] == "revision"
    assert by_number[2]["definition_snapshot"]["metadata"]["version"] == 2


async def test_workflow_definitions_cursor_pagination(api):
    ids = []
    for i in range(5):
        r = await api.post(
            f"{API}/workflows/definitions",
            json={"name": f"wf-{i}", "definition": VALID_DEFINITION},
        )
        ids.append(r.json()["id"])

    page1 = (await api.get(f"{API}/workflows/definitions?limit=2")).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = (await api.get(f"{API}/workflows/definitions?limit=2&after={page1['next_cursor']}")).json()
    seen = {w["id"] for w in page1["items"]}.union({w["id"] for w in page2["items"]})
    assert len(seen) == 4  # no overlap across pages
    assert page2["next_cursor"] is not None


async def test_workflow_definition_errors_are_problem_details(api):
    # Duplicate name -> 409
    payload = {"name": "dup", "definition": VALID_DEFINITION}
    r1 = await api.post(f"{API}/workflows/definitions", json=payload)
    assert r1.status_code == 201
    r2 = await api.post(f"{API}/workflows/definitions", json=payload)
    assert r2.status_code == 409
    body = r2.json()
    assert body["type"] == "urn:orchestration:error:duplicate-key"

    # Missing definition -> 404
    r = await api.get(f"{API}/workflows/definitions/does-not-exist")
    assert r.status_code == 404
    assert r.json()["type"] == "urn:orchestration:error:not-found"

    # Version on missing definition -> 404
    r = await api.post(
        f"{API}/workflows/definitions/does-not-exist/versions",
        json={"definition_snapshot": VALID_DEFINITION},
    )
    assert r.status_code == 404


async def test_new_workflow_routes_also_served_unprefixed(api):
    """Legacy prefixed-less clients keep working via the unprefixed alias."""
    r = await api.post(
        "/workflows/definitions",
        json={"name": "legacy", "definition": VALID_DEFINITION},
    )
    assert r.status_code == 201, r.text
    wf_id = r.json()["id"]
    r = await api.get(f"/workflows/definitions/{wf_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "legacy"


async def test_run_and_tasks_lists_are_cursor_pages(api):
    project = (await api.post(f"{API}/projects", json={"name": "p"})).json()
    run = (
        await api.post(
            f"{API}/workflows/runs",
            json={"project_id": project["id"], "name": "r", "tasks": [{"title": "t"}]},
        )
    ).json()
    runs_page = (await api.get(f"{API}/workflows/runs")).json()
    assert "items" in runs_page and "next_cursor" in runs_page
    assert any(r["id"] == run["id"] for r in runs_page["items"])

    tasks_page = (await api.get(f"{API}/workflows/runs/{run['id']}/tasks")).json()
    assert "items" in tasks_page and "next_cursor" in tasks_page
    assert len(tasks_page["items"]) == 1