"""The generated OpenAPI 3.x document must be valid and complete.

Also enforces that the committed ``docs/openapi.json`` contract stays in sync
with the application. An earlier version of this file REGENERATED that tracked
document as a side effect of the test run, which (a) dirtied the git tree on
every ``pytest`` invocation and (b) let the committed contract silently drift
from the code. Regenerating the document is an explicit step; this suite only
verifies it.
"""

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
    "/workflows/runs/{run_id}/events",
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


def test_checked_in_openapi_is_not_modified_by_test_run():
    """A test run must never rewrite the tracked contract."""
    docs_file = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    assert docs_file.is_file(), (
        "docs/openapi.json is missing; regenerate it from app.openapi() and commit"
    )
    before = docs_file.read_bytes()
    build_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    assert docs_file.read_bytes() == before


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


def test_terminal_lease_header_is_documented_for_both_api_aliases(tmp_path):
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'terminal-lease-spec.db'}",
        recover_on_startup=False, attempt_lease_enabled=True,
    ))
    live = app.openapi()
    committed = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text()
    )
    validate(live)
    validate(committed)
    for prefix in ("", "/api/v1"):
        for operation in ("submit", "fail"):
            path = f"{prefix}/tasks/{{task_id}}/attempts/{{attempt_id}}/{operation}"
            live_params = live["paths"][path]["post"]["parameters"]
            checked_params = committed["paths"][path]["post"]["parameters"]
            assert live_params == checked_params
            header = [p for p in live_params if p["in"] == "header"]
            assert len(header) == 1
            assert header[0]["name"] == "X-Attempt-Lease"
            assert header[0]["required"] is False

def test_task_and_git_artifact_contract_positive_and_negative():
    import pytest
    from pydantic import ValidationError
    from orchestration_server.schemas import TaskSpec, SubmitRequest

    task = TaskSpec.model_validate({"title": "verify", "depends_on": [0]})
    assert task.depends_on == [0]
    for deps in ([True], ["0"], [0] * 17):
        with pytest.raises(ValidationError):
            TaskSpec.model_validate({"title": "verify", "depends_on": deps})
    payload = {"output": {"summary": "example"}, "git_artifact": {
        "commit_sha": "a" * 40, "changed_paths": ["out/report.md"]}}
    result = SubmitRequest.model_validate(payload)
    assert result.git_artifact.commit_sha == "a" * 40
    for bad in ({"commit_sha": "short", "changed_paths": ["out/report.md"]},
                {"commit_sha": "a" * 40, "changed_paths": ["out/../secret"]},
                {"commit_sha": "a" * 40, "changed_paths": ["out/a", "out/a"]}):
        with pytest.raises(ValidationError):
            SubmitRequest.model_validate({"output": {}, "git_artifact": bad})
    with pytest.raises(ValidationError):
        SubmitRequest.model_validate({"output": "not an object"})


def test_task_git_contract_documentation_matches_generated_openapi(tmp_path):
    """Compare a bounded projection of actual API; print generated data on drift."""
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'git-spec.db'}",
        recover_on_startup=False,
    ))
    actual = app.openapi()
    checked = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text()
    )
    names = ("TaskSpec", "SubmitRequest", "GitArtifactReport", "GitEvidenceResponse")
    paths = ("/tasks/{task_id}/git-evidence", "/api/v1/tasks/{task_id}/git-evidence")

    def projection(doc):
        schemas = doc["components"]["schemas"]
        # Only this audited contract boundary; do not normalize away wire fields.
        return {"schemas": {name: schemas.get(name) for name in names},
                "paths": {path: doc["paths"].get(path) for path in paths}}

    expected = projection(actual)
    observed = projection(checked)
    assert all(expected["schemas"].values()) and all(expected["paths"].values())
    assert observed == expected, (
        "TASK_GIT_OPENAPI_GENERATED=" + json.dumps(expected, sort_keys=True, ensure_ascii=True)
    )


def test_full_default_http_openapi_matches_checked_in_contract(tmp_path):
    """Enforce the whole default HTTP contract, not only selected projections.

    The optional stream-ticket API is explicitly disabled for this artifact.
    Report exact generated sections so drift is repaired from the real app,
    never by guessing schemas or rewriting the tracked file during pytest.
    """
    import pytest

    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'full-spec.db'}",
        api_prefix="/api/v1",
        recover_on_startup=False,
        stream_tickets_enabled=False,
        attempt_lease_enabled=False,
        require_git_artifact=False,
        release_approval_key=None,
        qa_attestation_key=None,
        reconciliation_evidence_root=None,
        reconciliation_tool_ledger_path=None,
        git_verification_repository=None,
        cert_file=None, key_file=None, ca_file=None,
    ))
    generated = app.openapi()
    checked = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text(
            encoding="utf-8"
        )
    )
    validate(generated)
    validate(checked)
    if checked == generated:
        return

    # Emit deterministic, individually parseable JSON changes. Keep the
    # comparison exact; no normalization of operation IDs, required fields,
    # validation bounds, response models, aliases or security metadata.
    def differences(before, after, prefix=()):
        if before == after:
            return
        if isinstance(before, dict) and isinstance(after, dict) and (
            prefix == () or prefix == ("paths",) or prefix == ("components",)
            or prefix == ("components", "schemas")
        ):
            for key in sorted(before.keys() | after.keys()):
                if key not in after:
                    yield {"path": [*prefix, key], "op": "remove"}
                elif key not in before:
                    yield {"path": [*prefix, key], "op": "set", "value": after[key]}
                else:
                    yield from differences(before[key], after[key], (*prefix, key))
            return
        yield {"path": list(prefix), "op": "set", "value": after}

    changes = list(differences(checked, generated))
    assert changes, "OpenAPI mismatch without diagnostics"
    for change in changes:
        print("OPENAPI_DRIFT_JSON=" + json.dumps(change, ensure_ascii=True, sort_keys=True))
    pytest.fail(
        f"Committed default HTTP OpenAPI differs in {len(changes)} sections; "
        "apply the generated OPENAPI_DRIFT_JSON diagnostics and re-run CI.",
        pytrace=False,
    )
