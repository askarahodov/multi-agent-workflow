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


# -- board-level idempotency (Issue #192 rework) ---------------------------

def test_ingest_marker_embeds_source_event_id():
    from tools.github_kanban_sync.ingest import render_kanban_comment

    body = render_kanban_comment("issue_comment", {"issue": 192, "body": "x"}, "issue:192",
                                 source_event_id="repo:issue_comment:192:6519063860")
    marker = body.splitlines()[0]
    assert marker == ("<!-- gks:v1 id=issue:192 "
                      "event=repo:issue_comment:192:6519063860 channel=ingest -->")
    # backwards compatible: no source_event_id -> no event= token
    legacy = render_kanban_comment("issue_comment", {"issue": 192, "body": "x"}, "issue:192")
    assert "event=" not in legacy.splitlines()[0]


def _comment_handler(comment_id=6519063860, body="## STATUS — running"):
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([{"id": comment_id, "body": body,
                               "user": {"login": "askarahodov"},
                               "created_at": "2026-10-30T09:00:00Z"}])
    return handler


def _bind(store_path, task_id="t_dev", issue=192):
    store = Store(store_path)
    links.bind(store, REPO, issue, "me", task_id)
    store.close()


def test_fresh_ledger_reingest_does_not_duplicate_board(tmp_path):
    """The tester's repro: a reset journal must not re-append a board comment."""
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path)
    _bind(settings.coord_db)
    kb = board(settings.kanban_db)

    # run 1 — event is new, one comment lands on the card
    store1 = Store(settings.coord_db)
    ing1 = Ingestor(store1, client_with(_comment_handler()), kb, settings)
    assert ing1.ingest_issue_comments(192)["new_events"] == 1
    assert len(kb.ingest_comments("t_dev")) == 1
    store1.close()

    # run 2 — a brand-new (post "full reset") journal re-observes the same event
    fresh = tmp_path / "fresh_coord.db"
    _bind(fresh)
    store2 = Store(fresh)
    ing2 = Ingestor(store2, client_with(_comment_handler()), kb, settings)
    out = ing2.ingest_issue_comments(192)
    assert out["new_events"] == 1                       # new to THIS ledger ...
    assert len(kb.comments("t_dev")) == 1               # ... but no board duplicate
    assert len(kb.ingest_comments("t_dev")) == 1
    assert store2.delivery_journal(1)[0]["status"] == "duplicate"
    assert store2.counts()["pending"] == 0              # handled, not left pending
    store2.close(); kb.close()


def test_dedupe_removes_duplicate_ingest_comments(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    kb = board(db)
    marker_a = "<!-- gks:v1 id=issue:192 event=repo:issue_comment:192:1 channel=ingest -->"
    marker_b = "<!-- gks:v1 id=issue:192 event=repo:issue_comment:192:2 channel=ingest -->"
    kb.add_comment("t_dev", f"{marker_a}\n**handoff**\n\n> ownership\n")
    kb.add_comment("t_dev", f"{marker_a}\n**handoff**\n\n> ownership\n")   # duplicate
    kb.add_comment("t_dev", f"{marker_b}\n**comment**\n\n> status\n")
    kb.add_comment("t_dev", "a human note")                              # untouched

    out = kb.dedupe_ingest_comments("t_dev")
    assert out["duplicates_removed"] == 1
    assert len(kb.ingest_comments("t_dev")) == 2
    assert [c["body"] for c in kb.comments("t_dev") if c["body"] == "a human note"]
    # idempotent: a second pass removes nothing
    assert kb.dedupe_ingest_comments("t_dev")["duplicates_removed"] == 0
    # comments and their comment.added events stay in sync (2 ingest bodies -> 2 events)
    events = kb.conn.execute(
        "SELECT COUNT(*) FROM task_events WHERE task_id='t_dev' AND kind='comment.added'"
    ).fetchone()[0]
    assert events == 3  # 2 kept ingest comments + 1 human note
    kb.close()


def test_dedupe_all_removes_every_ingest_comment(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    kb = board(db)
    kb.add_comment("t_dev", "<!-- gks:v1 id=issue:192 event=e1 channel=ingest -->\nA\n")
    kb.add_comment("t_dev", "<!-- gks:v1 id=issue:192 event=e2 channel=ingest -->\nB\n")
    out = kb.dedupe_ingest_comments("t_dev", keep="none")
    assert out["duplicates_removed"] == 2
    assert kb.ingest_comments("t_dev") == []
    kb.close()


def test_has_comment_marker_matches_literally_not_as_like_pattern(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    kb = board(db)
    # '_' is a LIKE wildcard; a marker with a different char must NOT match
    kb.add_comment("t_dev", "<!-- gks:v1 event=repo:X:1 channel=ingest -->\nA\n")
    assert kb.has_comment_marker("t_dev", "event=repo:X:1") is True
    assert kb.has_comment_marker("t_dev", "event=repo:Y:1") is False
    kb.close()
