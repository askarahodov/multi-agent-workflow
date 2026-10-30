"""Tests for the conflict detector (Issue #192 §4)."""

from __future__ import annotations

from tools.github_kanban_sync import conflict


def test_exact_overlap_is_critical():
    report = conflict.detect(
        main_changed=["frontend/a.ts", "README.md"],
        claims=[{"task_id": "t_1", "branch": "wt/t_1", "changed_paths": ["README.md"]}],
    )
    assert report["decision"] == "block"
    crit = report["critical"][0]
    assert crit["task_id"] == "t_1" and crit["files"] == ["README.md"]
    assert crit["severity"] == "critical"


def test_disjoint_is_allow():
    report = conflict.detect(
        main_changed=["frontend/a.ts"],
        claims=[{"task_id": "t_1", "changed_paths": ["backend/b.py"]}],
    )
    assert report["conflicts"] == [] and report["decision"] == "allow"


def test_same_sensitive_dir_is_warn_only():
    report = conflict.detect(
        main_changed=["shared/module/x.py"],
        claims=[{"task_id": "t_1", "changed_paths": ["shared/module/y.py"]}],
    )
    assert report["conflicts"][0]["severity"] == "warn"
    assert report["decision"] == "allow"


def test_reservation_conflict():
    report = conflict.detect(
        main_changed=["frontend/tsconfig.json"],
        claims=[],
        reservations=[{"scope": "frontend/", "issue_number": 182, "task_id": "t_mig"}],
    )
    assert report["decision"] == "block"
    assert report["conflicts"][0]["type"] == "reservation"


def test_stale_main_blocks():
    report = conflict.detect(
        main_changed=[],
        claims=[],
        snapshot_origin_main="aaa",
        live_origin_main="bbb",
    )
    assert report["stale_main"] is True and report["decision"] == "block"
    assert any(c["type"] == "stale_main" for c in report["conflicts"])


def test_self_task_excluded():
    report = conflict.detect(
        main_changed=["a.py"],
        claims=[{"task_id": "t_self", "changed_paths": ["a.py"]}],
        self_task_id="t_self",
    )
    assert report["conflicts"] == []


def test_norm_and_is_sensitive():
    assert conflict.norm("./a/b.py") == "a/b.py"
    assert conflict.norm("a\\b.py") == "a/b.py"
    assert conflict.is_sensitive(".github/workflows/ci.yml") is True
    assert conflict.is_sensitive("compose.native.yml") is True
    assert conflict.is_sensitive("tools/x.py") is False


def test_unmerged_branches():
    def is_ancestor(branch, main):
        return branch == "wt/t_merged"

    out = conflict.unmerged_branches(["wt/t_merged", "wt/t_open"], "main", is_ancestor)
    assert out == ["wt/t_open"]
