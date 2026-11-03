"""Tests for Kanban -> GitHub publish + the close gate (Issue #192 §3)."""

from __future__ import annotations

import json

import httpx
import pytest

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
    def __init__(self, *, merged=True, ci="success", checks=None):
        self.comments: dict[int, list[dict]] = {}
        self.checks = checks
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
            checks = self.checks
            if checks is None:
                checks = [{
                    "name": "quality gate",
                    "status": "in_progress" if self.ci == "pending" else "completed",
                    "conclusion": None if self.ci == "pending" else self.ci,
                }]
            return json_response({"total_count": len(checks), "check_runs": checks})
        if method == "PATCH" and path.endswith("/issues/192"):
            return json_response({"number": 192, "state": "closed"})
        return json_response({}, status=404)


def _setup(tmp_path, fake: FakeGitHub, *, acceptance=True,
           required_checks=("quality gate",), close_approved_issues=(192,)):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev", status="running", branch="wt/t_dev")
    if acceptance:
        add_run(db, "t_dev", metadata=json.dumps(
            {"acceptance_tests": [{"command": "pytest -q", "result": "10 passed"}]}),
            status="done")
    settings = Settings(repo=REPO, board="me", coord_db=tmp_path / "coord.db", kanban_db=db,
                        publish_min_interval=0.0, required_checks=required_checks,
                        close_approved_issues=close_approved_issues)
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


def test_publish_recovers_rev_after_ledger_reset(tmp_path):
    """A reset journal must not rewind the published revision to 1."""
    fake = FakeGitHub()
    fake.comments[192] = [{"id": 555,
                           "body": "<!-- gks:v1 issue=192 channel=publish rev=3 -->\n## x"}]
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    out = pub.publish_task("t_dev")          # ledger has no stored rev/comment_id
    assert out["status"] == "updated" and out["comment_id"] == 555 and out["rev"] == 4
    assert len(fake.comments[192]) == 1
    assert "rev=4" in fake.comments[192][0]["body"]
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


def test_close_is_disabled_without_required_check_configuration(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake, required_checks=())
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    result = pub.close_if_confirmed(192)
    assert result == {"issue": 192, "closed": False, "reason": "ci_unconfigured"}
    assert not any(method == "PATCH" and path.endswith("/issues/192") for method, path in fake.calls)
    store.close(); kb.close()


def test_close_rejects_missing_required_check_despite_unrelated_green_ci(tmp_path):
    fake = FakeGitHub(checks=[
        {"name": "an unrelated job", "status": "completed", "conclusion": "success"}
    ])
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    result = pub.close_if_confirmed(192)
    assert result["closed"] is False and result["reason"] == "ci_unknown"
    assert not any(method == "PATCH" and path.endswith("/issues/192") for method, path in fake.calls)
    store.close(); kb.close()


def test_close_rejects_in_progress_required_check(tmp_path):
    fake = FakeGitHub(checks=[
        {"name": "quality gate", "status": "in_progress", "conclusion": None}
    ])
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    result = pub.close_if_confirmed(192)
    assert result["closed"] is False and result["reason"] == "ci_pending"
    store.close(); kb.close()


def test_close_rejects_skipped_required_check(tmp_path):
    fake = FakeGitHub(checks=[
        {"name": "quality gate", "status": "completed", "conclusion": "skipped"}
    ])
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    result = pub.close_if_confirmed(192)
    assert result["closed"] is False and result["reason"] == "ci_failure"
    store.close(); kb.close()


def test_close_checks_exact_configured_context_names(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(
        tmp_path, fake, required_checks=("quality gate", "Native LLM-tool-Contract Gate (offline)")
    )
    links.update(store, REPO, 192, pr_number=195)
    result = pub.close_if_confirmed(192)
    assert result["closed"] is False and result["reason"] == "ci_unknown"
    store.close(); kb.close()


def test_cli_close_returns_failure_when_required_ci_unconfigured(tmp_path, monkeypatch, capsys):
    import argparse
    from tools.github_kanban_sync import cli

    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake, required_checks=())
    links.update(store, REPO, 192, pr_number=195)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, **kw: settings))
    monkeypatch.setattr(cli, "_context", lambda _settings: (store, kb, pub.gh))
    args = argparse.Namespace(repo=REPO, board="me", db=None, kanban_db=None, issue=192)
    assert cli.cmd_close(args) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "ci_unconfigured"


def test_cli_close_returns_success_only_after_actual_closure(tmp_path, monkeypatch, capsys):
    import argparse
    from tools.github_kanban_sync import cli

    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, **kw: settings))
    monkeypatch.setattr(cli, "_context", lambda _settings: (store, kb, pub.gh))
    args = argparse.Namespace(repo=REPO, board="me", db=None, kanban_db=None, issue=192)
    assert cli.cmd_close(args) == 0
    assert json.loads(capsys.readouterr().out)["closed"] is True


def test_publish_pending_keeps_cursor_on_rate_limit_and_replays(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    try:
        pub.min_interval = 1000.0
        pub._now = lambda: 1000.0
        assert pub.publish_task("t_dev")["status"] == "created"
        kb.conn.execute("UPDATE tasks SET status='blocked' WHERE id='t_dev'")
        kb.conn.commit()
        kb.record_event("t_dev", "blocked", {"author": "owner"})
        first = pub.publish_pending()
        assert first["results"][0]["status"] == "rate_limited"
        assert first["cursor_advanced"] is False
        assert store.get_cursor("kanban_events")["cursor"] is None
        pub._now = lambda: 2500.0
        second = pub.publish_pending()
        assert second["results"][0]["status"] == "updated"
        assert second["cursor_advanced"] is True
        assert len(fake.comments[192]) == 1
        assert pub.publish_pending()["scanned"]["tasks"] == []
    finally:
        store.close()
        kb.close()


def test_publish_pending_keeps_cursor_after_github_permission_error(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    reject = [True]

    def handler(request):
        if reject[0] and request.method == "POST" and request.url.path.endswith("/comments"):
            return json_response({"message": "permission denied"}, status=401)
        return fake.handler(request)

    pub.gh = client_with(handler)
    try:
        kb.record_event("t_dev", "status_changed", {"author": "owner"})
        from tools.github_kanban_sync.github import AuthError
        with pytest.raises(AuthError):
            pub.publish_pending()
        assert store.get_cursor("kanban_events")["cursor"] is None
        reject[0] = False
        out = pub.publish_pending()
        assert out["results"][0]["status"] == "created"
        assert out["cursor_advanced"] is True
        assert len(fake.comments[192]) == 1
    finally:
        pub.gh.close()
        store.close()
        kb.close()


def test_publish_pending_bootstraps_already_bound_card_without_events(tmp_path):
    fake = FakeGitHub()
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    try:
        first = pub.publish_pending()
        assert first["scanned"]["tasks"] == []
        assert first["bootstrapped"] == ["t_dev"]
        assert first["results"][0]["status"] == "created"
        assert len(fake.comments[192]) == 1
        again = pub.publish_pending()
        assert again["results"] == []
        assert len(fake.comments[192]) == 1
    finally:
        store.close()
        kb.close()


def test_close_requires_explicit_per_issue_operator_approval(tmp_path):
    fake = FakeGitHub(merged=True, ci="success")
    settings, store, kb, pub, _ = _setup(tmp_path, fake, close_approved_issues=())
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    result = pub.close_if_confirmed(192)
    assert result == {"issue": 192, "closed": False, "reason": "closure_not_approved"}
    assert not any(m == "PATCH" and p.endswith("/issues/192") for m, p in fake.calls)
    store.close(); kb.close()


@pytest.mark.parametrize(("raw", "expected"), [
    ("11,8", (11, 8)), (" 11 , 8 ", (11, 8)),
    ("11,11", (11,)), ("", ()), (" ", ()),
])
def test_explicit_closure_opt_in_from_env(monkeypatch, raw, expected):
    from tools.github_kanban_sync.config import _approved_close_issues
    assert _approved_close_issues(raw) == expected
    monkeypatch.setenv("GKS_CLOSE_APPROVED_ISSUES", raw)
    assert Settings.from_env().close_approved_issues == expected


@pytest.mark.parametrize("raw", [
    "0", "-11", "11,,8", "11,", ",11", "11.0", "1e1",
    "abc", "０11", "01", "+11",
])
def test_invalid_close_approval_list_is_rejected(monkeypatch, raw):
    from tools.github_kanban_sync.config import _approved_close_issues
    with pytest.raises(ValueError, match="GKS_CLOSE_APPROVED_ISSUES"):
        _approved_close_issues(raw)
    monkeypatch.setenv("GKS_CLOSE_APPROVED_ISSUES", raw)
    with pytest.raises(ValueError, match="GKS_CLOSE_APPROVED_ISSUES"):
        Settings.from_env()


def test_other_issue_approval_cannot_close_this_issue(tmp_path):
    """A non-empty approval set must NOT act as a global closure bypass."""
    fake = FakeGitHub(merged=True, ci="success")
    # Only P0 Issue #11 is approved; scoped Issue #192 is not.
    settings, store, kb, pub, _ = _setup(
        tmp_path, fake, close_approved_issues=(11,),
    )
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    result = pub.close_if_confirmed(192)
    assert result == {"issue": 192, "closed": False, "reason": "closure_not_approved"}
    assert not any(method == "PATCH" and p.endswith("/issues/192") for method, p in fake.calls)
    store.close(); kb.close()

@pytest.mark.parametrize("evidence", [
    [{"command": "pytest -q", "result": "failed"}],
    [{"command": "pytest -q", "result": "1 passed, 1 failed"}],
    [{"command": "pytest -q", "result": "pending"}],
    [{"command": "pytest -q", "result": "skipped"}],
    [{"command": "pytest -q", "result": "0 passed"}],
    [{"command": "pytest -q", "result": "10 passed, 2 failed"}],
    [{"command": "pytest -q", "result": True}],
    [{"result": "passed"}],
    [{"command": "", "result": "passed"}],
    ["passed"],
    {"command": "pytest -q", "result": "passed"},
    [{"command": "pytest -q", "result": "10 passed"},
     {"command": "security-check", "result": "failed"}],
])
def test_close_rejects_false_or_incomplete_acceptance_receipts(tmp_path, evidence):
    fake = FakeGitHub(merged=True, ci="success")
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    kb.conn.execute(
        "UPDATE task_runs SET metadata=? WHERE task_id='t_dev'",
        (json.dumps({"acceptance_tests": evidence}),),
    )
    kb.conn.commit()
    result = pub.close_if_confirmed(192)
    assert result["closed"] is False
    assert result["reason"] == "invalid_acceptance_evidence"
    assert not any(m == "PATCH" and p.endswith("/issues/192") for m, p in fake.calls)
    store.close(); kb.close()


def test_close_accepts_multiple_explicit_pass_receipts(tmp_path):
    fake = FakeGitHub(merged=True, ci="success")
    settings, store, kb, pub, _ = _setup(tmp_path, fake)
    links.update(store, REPO, 192, pr_number=195)
    kb.conn.execute("UPDATE tasks SET status='done' WHERE id='t_dev'")
    kb.conn.commit()
    kb.conn.execute(
        "UPDATE task_runs SET metadata=? WHERE task_id='t_dev'",
        (json.dumps({"acceptance_tests": [
            {"command": "pytest -q", "result": "12 passed in 0.23s"},
            {"command": "security-check", "result": "PASS"},
        ]}),),
    )
    kb.conn.commit()
    result = pub.close_if_confirmed(192)
    assert result["closed"] is True
    assert any(m == "PATCH" and p.endswith("/issues/192") for m, p in fake.calls)
    store.close(); kb.close()
