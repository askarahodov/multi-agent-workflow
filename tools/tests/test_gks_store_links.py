"""Tests for the ledger + ID-contract (Issue #192 §1)."""

from __future__ import annotations

import pytest

from tools.github_kanban_sync import links
from tools.github_kanban_sync.store import Store


def test_source_event_id_is_canonical():
    assert (links.source_event_id("r/x", "issue_comment", 192, 5)
            == "r/x:issue_comment:192:5")


def test_record_event_is_idempotent():
    store = Store(":memory:")
    assert store.record_event("k1", "issue", {"a": 1}) is True
    assert store.record_event("k1", "issue", {"a": 1}) is False
    assert store.counts()["events"] == 1
    store.close()


def test_bind_is_idempotent_and_unique():
    store = Store(":memory:")
    links.bind(store, "r/x", 192, "me", "t_aaaa", owner="dev", branch="wt/t_aaaa")
    links.bind(store, "r/x", 192, "me", "t_aaaa", owner="dev2")
    assert links.get_by_issue(store, "r/x", 192)["owner"] == "dev2"
    assert len(links.all_links(store)) == 1
    store.close()


def test_bind_conflict_requires_force():
    store = Store(":memory:")
    links.bind(store, "r/x", 192, "me", "t_aaaa")
    with pytest.raises(links.LinkConflict):
        links.bind(store, "r/x", 192, "me", "t_bbbb")
    with pytest.raises(links.LinkConflict):
        links.bind(store, "r/x", 200, "me", "t_aaaa")
    store.close()


def test_force_repoint_moves_both_sides():
    store = Store(":memory:")
    links.bind(store, "r/x", 192, "me", "t_aaaa")
    links.bind(store, "r/x", 192, "me", "t_bbbb", force=True)
    assert links.get_by_issue(store, "r/x", 192)["task_id"] == "t_bbbb"
    assert links.get_by_task(store, "me", "t_aaaa") is None
    assert links.get_by_task(store, "me", "t_bbbb")["issue_number"] == 192
    store.close()


def test_changed_paths_roundtrip_and_update():
    store = Store(":memory:")
    links.bind(store, "r/x", 1, "me", "t_1", changed_paths=["b/", "a.py", "a.py"])
    link = links.get_by_issue(store, "r/x", 1)
    assert link["changed_paths"] == ["a.py", "b/"]
    links.update(store, "r/x", 1, status="running", pr_number=190)
    link = links.get_by_issue(store, "r/x", 1)
    assert link["status"] == "running" and link["pr_number"] == 190
    store.close()


def test_unbind():
    store = Store(":memory:")
    links.bind(store, "r/x", 5, "me", "t_5")
    assert links.unbind(store, "r/x", 5) is True
    assert links.get_by_issue(store, "r/x", 5) is None
    store.close()


def test_cursor_and_pending_and_delivery_journal():
    store = Store(":memory:")
    store.set_cursor("issues", etag="W/1", cursor="2026-01-01T00:00:00Z")
    got = store.get_cursor("issues")
    assert got["etag"] == "W/1" and got["cursor"] == "2026-01-01T00:00:00Z"

    store.record_event("k1", "issue", {})
    assert len(store.pending_events()) == 1
    store.mark_delivered("k1")
    assert store.pending_events() == []

    store.record_delivery("k1", "kanban", "delivered", target="t_1")
    store.record_delivery("k2", "kanban", "error", detail="boom")
    journal = store.delivery_journal()
    assert len(journal) == 2 and store.counts()["delivery_errors"] == 1
    store.close()


def test_rate_limit_touch():
    store = Store(":memory:")
    assert store.allow("scope", 5.0, now=1000.0) is True
    store.touch("scope", now=1000.0)
    assert store.allow("scope", 5.0, now=1003.0) is False
    assert store.allow("scope", 5.0, now=1006.0) is True
    store.close()


def test_reservations_roundtrip():
    store = Store(":memory:")
    store.reserve("frontend/", issue_number=182, reason="migration")
    res = store.reservations()
    assert res[0]["scope"] == "frontend/" and res[0]["issue_number"] == 182
    store.close()
