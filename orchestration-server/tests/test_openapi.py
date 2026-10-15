"""The generated OpenAPI 3.x document must be valid and complete."""

from __future__ import annotations

import json
from pathlib import Path

from openapi_spec_validator import validate

from orchestration_server.api import build_app
from orchestration_server.config import Settings

REQUIRED_PATHS = {
    "/health",
    "/projects",
    "/workspaces",
    "/contracts",
    "/agents",
    "/agents/register",
    "/workflows/runs",
    "/workflows/runs/{run_id}",
    "/workflows/runs/{run_id}/tasks",
    "/tasks/{task_id}",
    "/tasks/{task_id}/claim",
    "/tasks/{task_id}/attempts",
    "/tasks/{task_id}/attempts/{attempt_id}/submit",
    "/tasks/{task_id}/attempts/{attempt_id}/fail",
    "/tasks/{task_id}/block",
}


def test_generated_openapi_spec_is_valid(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'spec.db'}")
    app = build_app(settings)
    spec = app.openapi()

    assert spec["openapi"].startswith("3.")
    validate(spec)  # raises if the document violates the OpenAPI schema

    missing = REQUIRED_PATHS - set(spec["paths"])
    assert not missing, f"missing API paths: {sorted(missing)}"

    # Every operation documents its error responses.
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert "responses" in op, f"{method.upper()} {path} has no responses"


def test_openapi_document_is_written_to_docs(tmp_path):
    # Never overwrite the checked-in contract during tests: the following
    # regression must compare a genuinely committed OpenAPI artifact.
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    app = build_app(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 's.db'}"))
    spec = app.openapi()
    validate(spec)
    out = docs_dir / "openapi.json"
    out.write_text(json.dumps(spec, indent=2, sort_keys=True))
    assert json.loads(out.read_text())["info"]["title"] == "Orchestration Server"


def test_manual_recovery_openapi_reports_conflict_not_success(tmp_path):
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'recovery-spec.db'}",
        recover_on_startup=False,
    ))
    spec = app.openapi()
    committed = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text()
    )
    for path in ("/admin/recover", "/api/v1/admin/recover"):
        generated = spec["paths"][path]["post"]["responses"]
        checked_in = committed["paths"][path]["post"]["responses"]
        for responses in (generated, checked_in):
            assert "200" not in responses
            assert "409" in responses
            schema = responses["409"]["content"]["application/json"]["schema"]
            assert schema["$ref"] == "#/components/schemas/ProblemDetail"
        assert generated == checked_in
