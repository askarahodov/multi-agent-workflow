"""Tests for GitHub -> Kanban ingest (Issue #192 §2)."""

from __future__ import annotations

import httpx
import pytest

from tools.github_kanban_sync import links
from tools.github_kanban_sync.config import Settings
from tools.github_kanban_sync.ingest import Ingestor, is_sync_authored
from tools.github_kanban_sync.store import Store
from tools.tests._gks_helpers import add_task, board, client_with, json_response, make_kanban_db

REPO = "askarahodov/multi-agent-workflow"


def _settings(tmp_path) -> Settings:
    return Settings(repo=REPO, board="me", coord_db=tmp_path / "coord.db",
                    kanban_db=tmp_path / "kanban.db")


def _ingestor(tmp_path, handler, *, token="t"):
    settings = _settings(tmp_path)
    store = Store(settings.coord_db)
    kb = board(settings.kanban_db)
    ing = Ingestor(store, client_with(handler, token=token), kb, settings)
    return settings, store, kb, ing


def test_ingest_issue_creates_event_and_delivers(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    store = Store(tmp_path / "coord.db")
    links.bind(store, REPO, 192, "me", "t_dev", owner="sdlc-developer")
    store.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{
            "number": 192, "title": "sync", "state": "open",
            "updated_at": "2026-10-30T09:00:00Z", "html_url": "u",
        }])

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    out = ing.ingest_issues()
    assert out["new_events"] == 1
    comments = kb.comments("t_dev")
    assert len(comments) == 1 and "Issue #192" in comments[0]["body"]
    assert store.delivery_journal()[0]["status"] == "delivered"
    assert store.counts()["pending"] == 0
    store.close(); kb.close()


def test_duplicate_issue_not_redelivered(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    store0 = Store(tmp_path / "coord.db")
    links.bind(store0, REPO, 192, "me", "t_dev")
    store0.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{"number": 192, "title": "sync", "state": "open",
                               "updated_at": "2026-10-30T09:00:00Z"}])

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    ing.ingest_issues()
    second = ing.ingest_issues()
    assert second["new_events"] == 0
    assert len(kb.comments("t_dev")) == 1
    store.close(); kb.close()


def test_handoff_comment_is_delivered(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_mig")
    store0 = Store(tmp_path / "coord.db")
    links.bind(store0, REPO, 182, "me", "t_mig")
    store0.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{
            "id": 6518899017, "body": "MIGRATION_182_HANDOFF reserved frontend/",
            "user": {"login": "askarahodov"}, "created_at": "2026-10-30T09:00:00Z",
        }])

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    out = ing.ingest_issue_comments(182)
    assert out["new_events"] == 1
    body = kb.comments("t_mig")[0]["body"]
    assert "handoff" in body and "MIGRATION_182_HANDOFF" in body
    kind = store._query("SELECT kind FROM coord_event")[0]["kind"]
    assert kind == "handoff"
    store.close(); kb.close()


def test_sync_authored_comment_is_ignored(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{"id": 1, "body": "<!-- gks:v1 channel=publish --> x",
                               "user": {"login": "bot"}, "created_at": "x"}])

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    assert ing.ingest_issue_comments(192)["new_events"] == 0
    assert is_sync_authored("<!-- gks:v1 x -->")
    store.close(); kb.close()


def test_unlinked_issue_records_unlinked(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{"number": 999, "state": "open", "updated_at": "2026-10-30T09:00:00Z"}])

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    ing.ingest_issues()
    assert store.delivery_journal()[0]["status"] == "unlinked"
    # an unlinked finding is handled, not a retryable error: nothing left pending
    assert store.counts()["pending"] == 0
    assert store.counts()["delivery_errors"] == 0
    store.close(); kb.close()


def test_pr_merge_updates_link_and_revision(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    store0 = Store(tmp_path / "coord.db")
    links.bind(store0, REPO, 192, "me", "t_dev")
    store0.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{
            "number": 195, "title": "sync", "state": "closed", "merged_at": "2026-10-30T10:00:00Z",
            "updated_at": "2026-10-30T10:00:00Z", "body": "Closes #192",
            "html_url": "u",
            "head": {"sha": "head123", "ref": "wt/t_abc"}, "base": {"sha": "base456"},
            "merge_commit_sha": "merge789",
        }])

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    out = ing.ingest_pulls()
    assert out["new_events"] == 1
    link = links.get_by_issue(store, REPO, 192)
    assert link["pr_number"] == 195 and link["branch"] == "wt/t_abc"
    assert link["head_sha"] == "merge789"
    store.close(); kb.close()


def test_ci_state_collapses(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            return json_response({"statuses": [{"state": "success"}]})
        return json_response({"check_runs": [{"conclusion": "success"}]})

    settings, store, kb, ing = _ingestor(tmp_path, handler)
    assert ing.ci_state("abc") == "success"
    store.close(); kb.close()


def test_ci_state_failure_and_pending(tmp_path):
    def failing(request):
        if request.url.path.endswith("/status"):
            return json_response({"statuses": [{"state": "failure"}]})
        return json_response({"check_runs": []})

    settings, store, kb, ing = _ingestor(tmp_path, failing)
    assert ing.ci_state("abc") == "failure"
    store.close(); kb.close()

    def pending(request):
        if request.url.path.endswith("/status"):
            return json_response({"statuses": []})
        return json_response({"check_runs": [{"conclusion": None, "status": "in_progress"}]})

    settings, store, kb, ing = _ingestor(tmp_path, pending)
    assert ing.ci_state("abc") in ("pending", "unknown")
    store.close(); kb.close()
