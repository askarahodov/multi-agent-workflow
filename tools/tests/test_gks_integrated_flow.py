"""Integrated two-way GitHub ↔ real SQLite Kanban acceptance (Issue #192).

This is a hermetic transport simulation (httpx MockTransport), NOT a claim
of a live GitHub ↔ local Hermes host deployment. It exercises the actual
polling scheduler, paginated GitHub client, SQLite board, publish feedback-loop
guard, durable restart and fail-closed PR merge/CI/acceptance gate together.
"""
from __future__ import annotations

import json

from tools.github_kanban_sync import links
from tools.github_kanban_sync.config import Settings
from tools.github_kanban_sync.kanban import KanbanBoard
from tools.github_kanban_sync.publish import Publisher
from tools.github_kanban_sync.scheduler import Scheduler, SchedulerConfig
from tools.github_kanban_sync.store import Store
from tools.tests._gks_helpers import (
    add_run, add_task, client_with, json_response, make_kanban_db,
)

REPO = "askarahodov/multi-agent-workflow"
MERGE_SHA = "c" * 40


class MockGitHub:
    def __init__(self):
        self.published = []
        self.published_193 = []
        self.writes = []
        self.closed = False
        self.check_status = "in_progress"
        self.check_conclusion = None
        self.issue_references = "Closes #192"
        self.requests = []

    def handler(self, request):
        path = request.url.path
        page = int(request.url.params.get("page", "1"))
        self.requests.append((request.method, path, page))
        if request.method == "GET" and path.endswith("/issues"):
            # Subsequent incremental polls will NOT re-emit the older Issue.
            # The late-binding backfill must use the durable ledger.
            if request.url.params.get("since"):
                return json_response([])
            if page == 1:
                return json_response(
                    [{"number": 192, "state": "open", "title": "single owning card",
                      "updated_at": "2026-11-03T10:00:00Z"}],
                    headers={"link": (
                        f'<https://api.github.com/repos/{REPO}/issues'
                        '?per_page=100&page=2>; rel="next"'
                    )},
                )
            return json_response([
                {"number": 193, "state": "open", "title": "unlinked",
                 "updated_at": "2026-11-03T10:00:01Z"}
            ])
        if request.method == "GET" and path.endswith("/pulls"):
            return json_response([{
                "number": 99, "state": "closed", "merged_at": "2026-11-03T10:02:00Z",
                "updated_at": "2026-11-03T10:02:00Z", "title": self.issue_references,
                "body": self.issue_references, "head": {"sha": "b" * 40, "ref": "fix/192"},
                "base": {"sha": "a" * 40}, "merge_commit_sha": MERGE_SHA,
            }])
        if request.method == "GET" and path.endswith("/pulls/99"):
            return json_response({"number": 99, "merged": True,
                                  "merge_commit_sha": MERGE_SHA, "head": {"sha": "b" * 40}})
        if request.method == "GET" and path.endswith("/issues/193/comments"):
            return json_response(self.published_193)
        if request.method == "GET" and path.endswith("/issues/192/comments"):
            if page == 1:
                return json_response([{
                    "id": 1, "body": "Initial GitHub comment",
                    "created_at": "2026-11-03T10:00:00Z",
                    "user": {"login": "project-owner"}
                }], headers={"link": (
                    f'<https://api.github.com/repos/{REPO}/issues/192/comments'
                    '?per_page=100&page=2>; rel="next"'
                )})
            return json_response([{
                "id": 2, "body": "MIGRATION_182_HANDOFF to linked owner",
                "created_at": "2026-11-03T10:00:01Z",
                "user": {"login": "project-owner"}
            }] + self.published)
        if request.method == "POST" and path.endswith("/issues/193/comments"):
            body = json.loads(request.content)["body"]
            record = {"id": 2001 + len(self.published_193), "body": body,
                      "created_at": "2026-11-03T10:06:00Z"}
            self.published_193.append(record)
            self.writes.append(("POST", path))
            return json_response(record, status=201)
        if request.method == "POST" and path.endswith("/issues/192/comments"):
            body = json.loads(request.content)["body"]
            record = {"id": 1001 + len(self.published), "body": body,
                      "created_at": "2026-11-03T10:06:00Z"}
            self.published.append(record)
            self.writes.append(("POST", path))
            return json_response(record, status=201)
        if request.method == "PATCH" and "/issues/comments/" in path:
            cid = int(path.rsplit("/", 1)[1])
            for entry in self.published + self.published_193:
                if entry["id"] == cid:
                    entry["body"] = json.loads(request.content)["body"]
            self.writes.append(("PATCH", path))
            return json_response({"id": cid})
        if request.method == "PATCH" and path.endswith("/issues/192"):
            self.closed = json.loads(request.content).get("state") == "closed"
            self.writes.append(("PATCH", path))
            return json_response({"number": 192, "state": "closed"})
        if request.method == "GET" and path.endswith("/status"):
            return json_response({"statuses": [
                {"context": "gitflow policy validation", "state": "success"}
            ]})
        if request.method == "GET" and path.endswith("/check-runs"):
            return json_response({"total_count": 1, "check_runs": [{
                "name": "quality gate", "status": self.check_status,
                "conclusion": self.check_conclusion,
            }]})
        return json_response({})


def make_live_stack(tmp_path, fake):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_owner", status="running", branch="fix/192")
    settings = Settings(
        repo=REPO, board="me", coord_db=tmp_path / "sync.db", kanban_db=db,
        publish_min_interval=0.0, required_checks=("quality gate",),
    )
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_owner", owner="sdlc-developer")
    kb = KanbanBoard(db)
    gh = client_with(fake.handler)
    return settings, store, kb, gh


def test_daemon_full_bidirectional_cycle_restart_and_close_gate(tmp_path):
    fake = MockGitHub()
    settings, store, kb, gh = make_live_stack(tmp_path, fake)

    try:
        scheduler = Scheduler(settings, store=store, board=kb, gh=gh,
                              config=SchedulerConfig(interval=1.0), log=lambda _: None)
        first = scheduler.run_once()
        assert first["issues"]["new_events"] == 2
        assert first["linked"]["comments"]["192"]["new_events"] == 2
        assert first["linked"]["ci"][MERGE_SHA]["state"] == "pending"
        assert first["linked"]["ci"][MERGE_SHA]["delivery"]["192"] == "delivered"
        assert first["linked"]["invalid_shas"] == []
        assert links.get_by_issue(store, REPO, 192)["head_sha"] == MERGE_SHA

        comments = kb.ingest_comments("t_owner")
        assert len(comments) == 5  # Issue, PR, two comments, CI
        assert any("MIGRATION_182_HANDOFF" in c["body"] for c in comments)
        assert store.delivery_journal(30)
        assert len(fake.published) == 1  # initial status of linked existing card
        assert len(store.pending_events()) == 0

        # A meaningful local Kanban mutation publishes to the same Issue.
        kb.conn.execute(
            "UPDATE tasks SET status='blocked', block_kind='missing_review' "
            "WHERE id='t_owner'"
        )
        kb.conn.commit()
        kb.record_event("t_owner", "blocked",
                        {"status": "blocked", "author": "sdlc-developer"})
        second = scheduler.run_once()
        assert second["published"] == 1
        assert len(fake.published) == 1
        assert "missing_review" in fake.published[0]["body"]
        assert "status**: `blocked`" in fake.published[0]["body"]
        assert "branch**: `fix/192`" in fake.published[0]["body"]
        assert fake.closed is False  # no auto-close from Kanban status

        close = Publisher(store, gh, kb, settings).close_if_confirmed(192)
        assert close["reason"] == "ci_pending" and close["closed"] is False
        assert not any(method == "PATCH" and path.endswith("/issues/192")
                       for method, path in fake.writes)

        # Restart the real SQLite connections; duplicate poll observations
        # must not create more board comments or sync-authored Issue comments.
        store.close()
        kb.close()
        store = Store(settings.coord_db)
        kb = KanbanBoard(settings.kanban_db)
        scheduler = Scheduler(settings, store=store, board=kb, gh=gh,
                              config=SchedulerConfig(interval=1.0), log=lambda _: None)
        again = scheduler.run_once()
        assert again["linked"]["comments"]["192"]["new_events"] == 0
        assert len(kb.ingest_comments("t_owner")) == 5
        assert len(fake.published) == 1
        assert len(store.pending_events()) == 0

        # Green CI alone cannot close unfinished work.
        fake.check_status = "completed"
        fake.check_conclusion = "success"
        close = Publisher(store, gh, kb, settings).close_if_confirmed(192)
        assert close["closed"] is False and close["reason"] == "no_acceptance_evidence"

        add_run(settings.kanban_db, "t_owner", metadata=json.dumps({
            "acceptance_tests": [{"command": "pytest -q", "result": "passed"}]
        }))
        close = Publisher(store, gh, kb, settings).close_if_confirmed(192)
        assert close["closed"] is False and close["reason"] == "task_not_done"

        kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_owner'")
        kb.conn.commit()
        close = Publisher(store, gh, kb, settings).close_if_confirmed(192)
        assert close["closed"] is True and fake.closed is True
    finally:
        store.close()
        kb.close()
        gh.close()


def test_unlinked_late_binding_replays_ledger_without_duplicate_task(tmp_path):
    fake = MockGitHub()
    settings, store, kb, gh = make_live_stack(tmp_path, fake)
    try:
        # Issue #193 is initially observed without a linked card.
        ing = Scheduler(settings, store=store, board=kb, gh=gh,
                        config=SchedulerConfig(interval=1), log=lambda _: None)
        ing.run_once()
        add_task(settings.kanban_db, "t_second", status="running")
        links.bind(store, REPO, 193, "me", "t_second", owner="second-worker")
        assert not kb.ingest_comments("t_second")
        ing.run_once()  # GitHub returns [] for since; replay comes from ledger
        assert len(kb.ingest_comments("t_second")) == 1
        assert any(req[1].endswith("/issues") for req in fake.requests)
        ing.run_once()
        assert len(kb.ingest_comments("t_second")) == 1
    finally:
        store.close()
        kb.close()
        gh.close()


def test_multi_issue_pr_and_ci_recover_after_partial_board_failure(tmp_path):
    fake = MockGitHub()
    fake.issue_references = "Closes #192 and #193"
    settings, store, kb, gh = make_live_stack(tmp_path, fake)
    add_task(settings.kanban_db, "t_second", status="running")
    links.bind(store, REPO, 193, "me", "t_second", owner="second-worker")

    original_add = kb.add_comment

    def fail_second_card_ci(task_id, body, **kwargs):
        if task_id == "t_second" and "· CI" in body:
            raise OSError("simulated local SQLite write outage")
        return original_add(task_id, body, **kwargs)

    kb.add_comment = fail_second_card_ci
    try:
        sched = Scheduler(settings, store=store, board=kb, gh=gh,
                          config=SchedulerConfig(interval=1), log=lambda _: None)
        first = sched.run_once()
        assert first["recovery"]["errors"] == 1
        assert len(store.pending_events()) >= 1
        assert any("delivery:" in err for err in first["errors"])
        assert any("· PR" in item["body"] for item in kb.ingest_comments("t_second"))
        assert not any("· CI" in item["body"] for item in kb.ingest_comments("t_second"))
        assert sum("· CI" in item["body"] for item in kb.ingest_comments("t_owner")) == 1

        # Restart on disk without the simulated outage. The successful first
        # delivery must not be duplicated and the failed second target heals.
        store.close()
        kb.close()
        store = Store(settings.coord_db)
        kb = KanbanBoard(settings.kanban_db)
        sched = Scheduler(settings, store=store, board=kb, gh=gh,
                          config=SchedulerConfig(interval=1), log=lambda _: None)
        again = sched.run_once()
        assert again["recovery"]["errors"] == 0
        assert store.pending_events() == []
        assert sum("· CI" in item["body"] for item in kb.ingest_comments("t_owner")) == 1
        assert sum("· CI" in item["body"] for item in kb.ingest_comments("t_second")) == 1
        assert any("· PR" in item["body"] for item in kb.ingest_comments("t_second"))
        assert sched.run_once()["linked"]["ci"][MERGE_SHA]["new_events"] == 0
        assert sum("· CI" in item["body"] for item in kb.ingest_comments("t_second")) == 1
    finally:
        store.close()
        kb.close()
        gh.close()


def test_github_ci_transport_failure_does_not_record_success_snapshot(tmp_path):
    import pytest
    from tools.github_kanban_sync.github import TransientError

    fake = MockGitHub()
    settings, store, kb, gh = make_live_stack(tmp_path, fake)
    gh.close()

    def intermittent_failure(request):
        if request.url.path.endswith("/status"):
            return json_response({"message": "offline"}, status=503)
        return fake.handler(request)

    gh = client_with(intermittent_failure)
    try:
        sched = Scheduler(settings, store=store, board=kb, gh=gh,
                          config=SchedulerConfig(interval=1), log=lambda _: None)
        with pytest.raises(TransientError):
            sched.run_once()
        assert store.last_snapshot() is None
    finally:
        store.close()
        kb.close()
        gh.close()
