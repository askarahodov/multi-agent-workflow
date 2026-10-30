"""Tests for webhook signature verification + receiver (Issue #192 §2/§5)."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from tools.github_kanban_sync import links
from tools.github_kanban_sync.config import Settings
from tools.github_kanban_sync.ingest import Ingestor
from tools.github_kanban_sync.store import Store
from tools.github_kanban_sync.webhook import (
    WebhookReceiver,
    WebhookRejected,
    normalize_webhook,
    verify_signature,
)
from tools.tests._gks_helpers import add_task, board, client_with, json_response, make_kanban_db

REPO = "askarahodov/multi-agent-workflow"
SECRET = "s3cr3t"


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_ok_and_bad():
    body = b'{"a":1}'
    assert verify_signature(SECRET, body, _sign(SECRET, body)) is True
    assert verify_signature(SECRET, body, "sha256=deadbeef") is False
    assert verify_signature(SECRET, body, None) is False
    assert verify_signature("", body, _sign(SECRET, body)) is False


def test_receiver_rejects_bad_signature(tmp_path):
    db = make_kanban_db(tmp_path)
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "c.db", kanban_db=db)
    store = Store(settings.coord_db)
    kb = board(db)
    ing = Ingestor(store, client_with(lambda r: json_response({})), kb, settings)
    recv = WebhookReceiver(store, ing, SECRET, settings)
    with pytest.raises(WebhookRejected) as exc:
        recv.handle({"x-github-event": "issues", "x-hub-signature-256": "sha256=bad"}, b"{}")
    assert exc.value.status == 401
    store.close(); kb.close()


def test_receiver_accepts_and_delivers(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "c.db", kanban_db=db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)
    ing = Ingestor(store, client_with(lambda r: json_response({})), kb, settings)
    recv = WebhookReceiver(store, ing, SECRET, settings)

    payload = {"action": "edited", "issue": {"number": 192, "state": "open",
                                             "updated_at": "2026-10-30T11:00:00Z"}}
    body = json.dumps(payload).encode()
    out = recv.handle({"x-github-event": "issues",
                       "x-hub-signature-256": _sign(SECRET, body)}, body)
    assert out["status"] == "accepted" and out["outcome"] == "delivered"
    assert len(kb.comments("t_dev")) == 1

    # replay is a duplicate, not a second delivery
    again = recv.handle({"x-github-event": "issues",
                         "x-hub-signature-256": _sign(SECRET, body)}, body)
    assert again["status"] == "duplicate"
    assert len(kb.comments("t_dev")) == 1
    store.close(); kb.close()


def test_receiver_and_poll_converge_on_one_row(tmp_path):
    """V-8: a change seen by both poll and webhook yields exactly one coord_event."""
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "c.db", kanban_db=db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)

    # poll path: an issue_comment event with comment id 6519063860
    poll_eid = links.source_event_id(REPO, "issue_comment", 192, 6519063860)
    store.record_event(poll_eid, "issue_comment", {"issue": 192, "comment_id": 6519063860})

    ing = Ingestor(store, client_with(lambda r: json_response({})), kb, settings)
    recv = WebhookReceiver(store, ing, SECRET, settings)
    payload = {"action": "created",
               "issue": {"number": 192},
               "comment": {"id": 6519063860, "body": "hello", "user": {"login": "askarahodov"}}}
    body = json.dumps(payload).encode()
    out = recv.handle({"x-github-event": "issue_comment",
                       "x-hub-signature-256": _sign(SECRET, body)}, body)
    assert out["status"] == "duplicate"
    assert store.counts()["events"] == 1
    store.close(); kb.close()


def test_poll_and_webhook_converge_on_one_row_for_issue_pr_ci(tmp_path):
    """B1: a change seen by both poll and webhook must reduce to ONE coord_event.

    Covers every mirrorable kind (issue, pr, ci), not just ``issue_comment``.
    """
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "c.db", kanban_db=db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)

    def handler(request):
        path = request.url.path
        if path.endswith("/issues"):
            return json_response([{"number": 192, "title": "sync", "state": "open",
                                   "updated_at": "2026-10-30T11:00:00Z", "html_url": "u"}])
        if path.endswith("/pulls"):
            return json_response([{"number": 195, "title": "sync", "state": "closed",
                                   "merged_at": "2026-10-30T11:00:00Z",
                                   "updated_at": "2026-10-30T11:00:00Z", "body": "Closes #192",
                                   "html_url": "u", "head": {"sha": "head123", "ref": "wt/t_abc"},
                                   "base": {"sha": "base456"}, "merge_commit_sha": "merge789"}])
        if path.endswith("/status"):
            return json_response({"statuses": [{"state": "success"}]})
        return json_response({"check_runs": [{"conclusion": "success"}]})

    ing = Ingestor(store, client_with(handler), kb, settings)
    recv = WebhookReceiver(store, ing, SECRET, settings)

    # poll path observes all three changes
    assert ing.ingest_issues()["new_events"] == 1
    assert ing.ingest_pulls()["new_events"] == 1
    assert ing.ingest_ci("abcdef1234567890")["new_events"] == 1
    poll_events = store.counts()["events"]
    assert poll_events == 3

    def hook(event, payload):
        body = json.dumps(payload).encode()
        return recv.handle({"x-github-event": event,
                            "x-hub-signature-256": _sign(SECRET, body)}, body)

    out_issue = hook("issues", {"action": "edited", "issue": {
        "number": 192, "state": "open", "title": "sync",
        "updated_at": "2026-10-30T11:00:00Z"}})
    out_pr = hook("pull_request", {"action": "closed", "pull_request": {
        "number": 195, "merged": True, "state": "closed", "title": "sync",
        "updated_at": "2026-10-30T11:00:00Z"}})
    out_ci = hook("workflow_run", {"workflow_run": {
        "head_sha": "abcdef1234567890", "conclusion": "success", "id": 42}})

    # the webhook must reduce to the SAME source_event_id as the poll: duplicate
    assert out_issue["status"] == "duplicate", out_issue
    assert out_pr["status"] == "duplicate", out_pr
    assert out_ci["status"] == "duplicate", out_ci

    # exactly one coord_event row per change (the ledger convergence is the fix)
    assert store.counts()["events"] == 3
    # issue + pr are card-linked and comment; CI is ledger-only (informational N1)
    assert len(kb.ingest_comments("t_dev")) == 2
    store.close(); kb.close()


def test_normalize_unknown_event_is_none():
    assert normalize_webhook("ping", {"zen": "x"}, REPO) is None


def test_normalize_push_key_matches_poll_shape():
    normalized = normalize_webhook("push", {"after": "abc123def456", "ref": "refs/heads/main"}, REPO)
    assert normalized["source_event_id"] == f"{REPO}:push:abc123def:abc123def456"


def test_normalize_ignores_sync_authored_comment():
    payload = {"issue": {"number": 1}, "comment": {"id": 9, "body": "<!-- gks:v1 x -->"}}
    assert normalize_webhook("issue_comment", payload, REPO) is None
