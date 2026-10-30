"""Tests for Kanban -> GitHub publish + the close gate (Issue #192 §3)."""

from __future__ import annotations

import json

import httpx

from tools.github_kanban_sync import links
from tools.github_kanban_sync.config import Settings
from tools.github_kanban_sync.publish import Publisher, render_publish_comment
from tools.github_kanban_sync.store import Store
from tools.tests._gks_helpers import (
    add_run,
    add_task,
    board,
    client_with,
    json_response,
    make_kanban_db,
)

REPO = "askarahodov/multi-agent-workflow"


class FakeGitHub:
    def __init__(self, *, merged=True, ci="success"):
        self.comments: dict[int, list[dict]] = {}
        self.next_id = 1000
        self.calls: list[tuple[str, str]] = []
        self.merged = merged
        self.ci = ci

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if method == "GET" and path.endswith("/comments"):
            issue = int(path.split("/issues/")[1].split("/")[0])
            return json_response(self.comments.get(issue, []))
        if method == "POST" and path.endswith("/comments"):
            issue = int(path.split("/issues/")[1].split("/")[0])
            body = json.loads(request.content)["body"]
            self.next_id += 1
            self.comments.setdefault(issue, []).append({"id": self.next_id, "body": body})
            return json_response({"id": self.next_id, "body": body}, status=201)
        if method == "PATCH" and "/issues/comments/" in path:
            cid = int(path.rsplit("/", 1)[1])
            body = json.loads(request.content)["body"]
            for issue, items in self.comments.items():
                for c in items:
                    if c["id"] == cid:
                        c["body"] = body
            return json_response({"id": cid})
        if method == "GET" and "/pulls/" in path:
            return json_response({
                "number": int(path.rsplit("/", 1)[1]), "merged": self.merged,
                "merge_commit_sha": "merge789",
                "head": {"sha": "head123"},
            })
        if method == "GET" and path.endswith("/status"):
            return json_response({"statuses": [{"state": self.ci}]})
        if method == "GET" and path.endswith("/check-runs"):
            return json_response({"check_runs": []})
        if method == "PATCH" and path.endswith("/issues/192"):
            return json_response({"number": 192, "state": "closed"})
        return json_response({}, status=404)


def _setup(tmp_path, fake: FakeGitHub, *, acceptance=True):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev", status="running", branch="wt/t_dev")
    if acceptance:
        add_run(db, "t_dev", metadata=json.dumps(
            {"acceptance_tests": [{"command": "pytest -q", "result": "10 passed"}]}),
            status="done")
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "coord.db", kanban_db=db,
                        publish_min_interval=0.0)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev", owner="sdlc-developer", branch="wt/t_dev")
    kb = board(db)
    pub = Publisher(store, client_with(fake.handler), kb, settings)
    return settings, store, kb, pub, fake


def test_render_comment_has_marker_and_version():
    body = render_publish_comment(issue=192, task={"id": "t_dev", "status": "running",
                                                    "assignee": "dev"},
                                  link={"board": "me", "branch": "wt/t_dev", "pr_number": None,
                                        "changed_paths": ["a.py"], "owner": "dev"},
                                  rev=3, blocker=None, acceptance=[])
    assert "<!-- gks:v1 issue=192 channel=publish rev=3 -->" in body
    assert "`a.py`" in body


def test_publish_creates_then_updates_single_comment(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, fake = _setup(tmp_path, fake)
    first = pub.publish_task("t_dev")
    assert first["status"] == "created"
    # mutate the card so the content changes
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    second = pub.publish_task("t_dev")
    assert second["status"] == "updated"
    assert second["comment_id"] == first["comment_id"]
    assert len(fake.comments[192]) == 1
    assert store.delivery_journal(10)[0]["status"] == "delivered"
    store.close(); kb.close()


def test_publish_unchanged_is_noop(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    pub.publish_task("t_dev")
    again = pub.publish_task("t_dev")
    assert again["status"] == "unchanged"
    assert len(fake.comments[192]) == 1
    store.close(); kb.close()


def test_publish_rate_limited(tmp_path):
    fake = FakeGitHub()
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev", status="running")
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "coord.db",
                        kanban_db=db, publish_min_interval=10_000.0)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev", branch="wt/t_dev")
    kb = board(db)
    pub = Publisher(store, client_with(fake.handler), kb, settings, now=lambda: 1000.0)
    assert pub.publish_task("t_dev")["status"] == "created"
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'"); kb.conn.commit()
    blocked = pub.publish_task("t_dev")
    assert blocked["status"] == "rate_limited"
    store.close(); kb.close()


def test_close_blocked_without_merge(tmp_path):
    fake = FakeGitHub(merged=False)
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    out = pub.close_if_confirmed(192)
    assert out["closed"] is False and out["reason"] == "pr_not_merged"
    store.close(); kb.close()


def test_close_blocked_without_ci(tmp_path):
    fake = FakeGitHub(merged=True, ci="failure")
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    out = pub.close_if_confirmed(192)
    assert out["closed"] is False and out["reason"] == "ci_failure"
    store.close(); kb.close()


def test_close_blocked_without_acceptance(tmp_path):
    fake = FakeGitHub(merged=True, ci="success")
    settings, store, kb, pub, _ = _setup(tmp_path, fake, acceptance=False)
    links.update(store, REPO, 192, pr_number=195)
    out = pub.close_if_confirmed(192)
    assert out["closed"] is False and out["reason"] == "no_acceptance_evidence"
    store.close(); kb.close()


def test_close_blocked_when_task_not_done(tmp_path):
    fake = FakeGitHub(merged=True, ci="success")
    settings, store, kb, pub, _ = _setup(tmp_path, fake)  # task status=running
    links.update(store, REPO, 192, pr_number=195)
    out = pub.close_if_confirmed(192)
    assert out["closed"] is False and out["reason"] == "task_not_done"
    store.close(); kb.close()


def test_close_succeeds_when_all_confirmed(tmp_path):
    fake = FakeGitHub(merged=True, ci="success")
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'"); kb.conn.commit()
    links.update(store, REPO, 192, pr_number=195)
    out = pub.close_if_confirmed(192)
    assert out["closed"] is True and out["ci"] == "success"
    assert any(method == "PATCH" and path.endswith("/issues/192") for method, path in fake.calls)
    store.close(); kb.close()


def test_publish_pending_scans_task_events(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    kb.record_event("t_dev", "status_changed", {"from": "todo", "to": "running", "author": "kernel"})
    out = pub.publish_pending()
    assert "t_dev" in out["scanned"]["tasks"]
    assert out["results"][0]["status"] in ("created", "updated")
    store.close(); kb.close()


def test_feedback_loop_event_is_skipped(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    kb.record_event("t_dev", "comment.added",
                    {"author": "github-kanban-sync", "body": "<!-- gks:v1 -->"})
    out = pub.publish_pending()
    assert out["scanned"]["tasks"] == []
    store.close(); kb.close()
