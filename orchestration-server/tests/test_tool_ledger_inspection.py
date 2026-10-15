"""Read-only recovery ledger inspection with real SQLite and admin RBAC."""
from __future__ import annotations

import os
import sqlite3

import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.errors import BusinessRuleError
from orchestration_server.tool_ledger_inspection import TrustedToolLedgerReader
from test_security_auth import _enable_auth


def make_ledger(path, rows=()):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE tool_execution (scope TEXT NOT NULL, "
            "call_id TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL, "
            "PRIMARY KEY (scope,call_id))"
        )
        connection.executemany(
            "INSERT INTO tool_execution (scope,call_id,name,state) VALUES (?,?,?,?)",
            rows,
        )
        connection.commit()
    os.chmod(path, 0o600)
    return path


async def quarantine(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    return run, tasks[0], attempt


@pytest.mark.asyncio
async def test_admin_can_inspect_only_redacted_interrupted_scope(harness, tmp_path, monkeypatch):
    run, task, attempt = await quarantine(harness)
    scope = f"run-{run.id}/attempt-{attempt.id}"
    path = make_ledger(tmp_path / "tool-ledger.sqlite3", [
        (scope, "call-sensitive-provider-token", "write_file", "SUCCEEDED"),
        (scope, "call-inflight", "write_file", "CLAIMED"),
        (scope, "call-denied", "read_file", "DENIED"),
        ("run-00000000-0000-0000-0000-000000000000/attempt-" + attempt.id,
         "other-scope", "write_file", "SUCCEEDED"),
    ])
    _enable_auth(monkeypatch, admin=["admin-secret"], write=["writer-secret"], read=["reader-secret"])
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        reconciliation_tool_ledger_path=str(path),
    ))
    endpoint = f"/api/v1/admin/tasks/{task.id}/tool-ledger"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            assert (await client.get(endpoint)).status_code == 401
            assert (await client.get(endpoint, headers={"X-API-Key": "reader-secret"})).status_code == 403
            assert (await client.get(endpoint, headers={"X-API-Key": "writer-secret"})).status_code == 403
            response = await client.get(endpoint, headers={"X-API-Key": "admin-secret"})
            assert response.status_code == 200, response.text
            value = response.json()
            assert value["task_id"] == task.id
            assert value["ledger_status"] == "AVAILABLE"
            assert len(value["attempts"]) == 1
            report = value["attempts"][0]
            assert report["attempt_id"] == attempt.id
            assert report["record_status"] == "RECORDS"
            assert {r["state"] for r in report["entries"]} == {
                "CLAIMED", "SUCCEEDED", "DENIED",
            }
            assert all(r["tool"] in ("read_file", "write_file") for r in report["entries"])
            assert all(len(r["call_ref"]) == 16 for r in report["entries"])
            raw = response.text
            assert "call-sensitive-provider-token" not in raw
            assert "other-scope" not in raw
            assert str(path) not in raw
            assert "admin-secret" not in raw
    assert (await harness.queries.get_task(task.id)).status == "blocked"


@pytest.mark.asyncio
async def test_missing_ledger_is_explicitly_unconfigured(harness):
    _, task, _ = await quarantine(harness)
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            result = await client.get(f"/api/v1/admin/tasks/{task.id}/tool-ledger")
            assert result.status_code == 503
            assert "not configured" in result.text


@pytest.mark.asyncio
async def test_nonquarantined_task_rejected_even_with_valid_ledger(harness, tmp_path):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    path = make_ledger(tmp_path / "claims.db")
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False,
                             reconciliation_tool_ledger_path=str(path)))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            result = await client.get(f"/api/v1/admin/tasks/{tasks[0].id}/tool-ledger")
            assert result.status_code == 422  # existing StateTransitionError API contract


@pytest.mark.asyncio
async def test_absence_of_claims_is_explicit_and_never_implies_safe_replay(harness, tmp_path):
    _, task, attempt = await quarantine(harness)
    path = make_ledger(tmp_path / "claims.db", [
        ("run-00000000-0000-0000-0000-000000000000/attempt-" + attempt.id,
         "unrelated", "write_file", "CLAIMED"),
    ])
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False,
                             reconciliation_tool_ledger_path=str(path)))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            result = await client.get(f"/api/v1/admin/tasks/{task.id}/tool-ledger")
            assert result.status_code == 200
            entry = result.json()["attempts"][0]
            assert entry["record_status"] == "NO_RECORDS"
            assert entry["entries"] == []
    assert (await harness.queries.get_task(task.id)).status == "blocked"


def test_ledger_never_created_implicitly(tmp_path):
    path = tmp_path / "nonexistent.db"
    with pytest.raises(BusinessRuleError):
        TrustedToolLedgerReader(path)
    assert not path.exists()


def test_bad_modes_and_symlink_fail_closed(tmp_path):
    path = make_ledger(tmp_path / "ledger.db")
    os.chmod(path, 0o644)
    with pytest.raises(BusinessRuleError):
        TrustedToolLedgerReader(path)
    os.chmod(path, 0o600)
    link = tmp_path / "link.db"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        TrustedToolLedgerReader(link)


def test_ledger_symlink_ancestor_is_rejected(tmp_path):
    actual = tmp_path / "actual" / "nested"
    actual.mkdir(parents=True)
    make_ledger(actual / "ledger.db")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "actual", target_is_directory=True)
    # Immediate parent is a real directory; only an ancestor is a symlink.
    with pytest.raises((BusinessRuleError, ValueError), match="unsafe"):
        TrustedToolLedgerReader(alias / "nested" / "ledger.db")


def test_ledger_ancestor_rechecked_before_inspection(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    path = make_ledger(actual / "ledger.db")
    reader = TrustedToolLedgerReader(path)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    # Simulate the configured path becoming aliased after setup.
    reader.path = alias / "ledger.db"
    with pytest.raises(BusinessRuleError, match="unsafe"):
        reader.inspect(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )


def test_corrupted_sqlite_does_not_claim_success(tmp_path):
    path = tmp_path / "broken.db"
    path.write_bytes(b"not a sqlite database")
    os.chmod(path, 0o600)
    with pytest.raises(BusinessRuleError, match="unreadable"):
        TrustedToolLedgerReader(path).inspect(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )


def test_scope_from_fake_identifier_is_rejected_before_sql(tmp_path):
    path = make_ledger(tmp_path / "ledger.db")
    reader = TrustedToolLedgerReader(path)
    with pytest.raises(BusinessRuleError, match="attempt identity"):
        reader.inspect("../../other", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def test_invalid_ledger_state_fails_closed(tmp_path):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    attempt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    path = make_ledger(tmp_path / "ledger.db", [
        (f"run-{run_id}/attempt-{attempt_id}", "id", "write_file", "UNEXPECTED"),
    ])
    with pytest.raises(BusinessRuleError, match="Invalid tool ledger record"):
        TrustedToolLedgerReader(path).inspect(run_id, attempt_id)


@pytest.mark.parametrize("invalid_limit", [True, False, 0, 1001, "10", 1.5])
def test_ledger_read_limit_rejects_non_integer_or_out_of_range(tmp_path, invalid_limit):
    path = make_ledger(tmp_path / "ledger.db")
    with pytest.raises(ValueError, match="Ledger read limit"):
        TrustedToolLedgerReader(path, max_entries=invalid_limit)


@pytest.mark.parametrize("invalid_id", ["", "x" * 129, " ", "with.dot", "nonascii-é", "call/id"])
def test_ledger_rejects_malformed_tool_call_ids(tmp_path, invalid_id):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    attempt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    path = make_ledger(tmp_path / "ledger.db", [
        (f"run-{run_id}/attempt-{attempt_id}", invalid_id, "write_file", "CLAIMED"),
    ])
    with pytest.raises(BusinessRuleError, match="Invalid tool ledger record"):
        TrustedToolLedgerReader(path).inspect(run_id, attempt_id)


@pytest.mark.parametrize("invalid_name", [b"binary-name", b"\x00unsafe", "x" * 65])
def test_reader_rejects_tool_names_writer_cannot_persist(tmp_path, invalid_name):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    attempt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    path = make_ledger(tmp_path / "ledger.db", [
        (f"run-{run_id}/attempt-{attempt_id}", "call-1", invalid_name, "CLAIMED"),
    ])
    with pytest.raises(BusinessRuleError, match="Invalid tool ledger record"):
        TrustedToolLedgerReader(path).inspect(run_id, attempt_id)


def test_reader_retains_redaction_for_supported_length_unknown_tool(tmp_path):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    attempt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    path = make_ledger(tmp_path / "ledger.db", [
        (f"run-{run_id}/attempt-{attempt_id}", "call-2", "unknown_tool", "DENIED"),
    ])
    rows = TrustedToolLedgerReader(path).inspect(run_id, attempt_id)
    assert len(rows) == 1
    assert rows[0].tool == "<unsupported>"
    assert rows[0].state == "DENIED"
    assert rows[0].call_ref != "call-2"


def test_reader_accepts_writer_maximum_tool_name_length(tmp_path):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    attempt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    path = make_ledger(tmp_path / "ledger.db", [
        (f"run-{run_id}/attempt-{attempt_id}", "call-3", "x" * 64, "DENIED"),
    ])
    assert TrustedToolLedgerReader(path).inspect(run_id, attempt_id)[0].tool == "<unsupported>"


def test_result_limit_prevents_incomplete_pagination(tmp_path):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    attempt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    scope = f"run-{run_id}/attempt-{attempt_id}"
    path = make_ledger(tmp_path / "ledger.db", [
        (scope, "one", "write_file", "SUCCEEDED"),
        (scope, "two", "write_file", "CLAIMED"),
    ])
    with pytest.raises(BusinessRuleError, match="inspection limit"):
        TrustedToolLedgerReader(path, max_entries=1).inspect(run_id, attempt_id)
