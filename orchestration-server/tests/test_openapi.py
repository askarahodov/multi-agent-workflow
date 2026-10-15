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
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    app = build_app(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 's.db'}"))
    spec = app.openapi()
    validate(spec)
    out = docs_dir / "openapi.json"
    out.write_text(json.dumps(spec, indent=2, sort_keys=True))
    assert json.loads(out.read_text())["info"]["title"] == "Orchestration Server"


def test_attempt_lease_openapi_matches_checked_in_contract(tmp_path):
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'lease-api.db'}",
        attempt_lease_enabled=True, recover_on_startup=False,
    ))
    generated = app.openapi()
    committed = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text()
    )
    validate(generated)
    validate(committed)
    for prefix in ("", "/api/v1"):
        claim = f"{prefix}/tasks/{{task_id}}/claim"
        renew = f"{prefix}/tasks/{{task_id}}/attempts/{{attempt_id}}/lease/renew"
        revoke = f"{prefix}/tasks/{{task_id}}/attempts/{{attempt_id}}/lease/revoke"
        for document in (generated, committed):
            paths = document["paths"]
            assert paths[claim]["post"]["responses"]["201"]["content"][
                "application/json"
            ]["schema"]["$ref"] == "#/components/schemas/ClaimAttemptResponse"
            assert paths[renew]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["$ref"] == "#/components/schemas/AttemptLeaseResponse"
            assert paths[revoke]["post"]["responses"]["200"]
            assert paths[renew]["post"]["requestBody"]["content"]["application/json"][
                "schema"
            ]["$ref"] == "#/components/schemas/AttemptLeaseRenewRequest"
        for path in (claim, renew, revoke):
            assert generated["paths"][path]["post"]["responses"] == committed["paths"][path]["post"]["responses"]
    for document in (generated, committed):
        token = document["components"]["schemas"]["ClaimAttemptResponse"][
            "properties"]["lease_token"]
        assert token["readOnly"] is True
        assert "writeOnly" not in token
        request_token = document["components"]["schemas"]["AttemptLeaseRenewRequest"][
            "properties"]["lease_token"]
        assert request_token["writeOnly"] is True
        assert "lease_token" not in document["components"]["schemas"]["AttemptResponse"]["properties"]
