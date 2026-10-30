"""Tests for observability + the CLI surface (Issue #192 §6/§7)."""

from __future__ import annotations

import json

from tools.github_kanban_sync import cli, links, observability
from tools.github_kanban_sync.store import Store
from tools.tests._gks_helpers import add_task, make_kanban_db


def _seed(tmp_path):
    store = Store(tmp_path / "coord.db")
    links.bind(store, "askarahodov/multi-agent-workflow", 192, "me", "t_dev",
               owner="sdlc-developer", branch="wt/t_dev")
    store.record_event("e1", "issue", {"number": 192})
    store.record_delivery("e1", "kanban", "delivered", target="t_dev")
    store.record_snapshot({"origin_main": "abc", "ci_state": "success", "open_prs": 0})
    return store


def test_health_reports_lag_and_pending(tmp_path):
    store = _seed(tmp_path)
    report = observability.health(store, max_lag=10_000_000)
    assert report["healthy"] is True and report["errors"] == 0
    assert report["counts"]["links"] == 1
    store.close()


def test_health_unhealthy_on_errors(tmp_path):
    store = _seed(tmp_path)
    store.record_delivery("e2", "kanban", "error", detail="boom")
    assert observability.health(store)["healthy"] is False
    store.close()


def test_status_and_trail(tmp_path):
    store = _seed(tmp_path)
    st = observability.status(store)
    assert st["links"] == 1 and st["links_detail"][0]["issue"] == 192
    trail = observability.delivery_trail(store, "e1")
    assert trail["event"]["source_event_id"] == "e1"
    assert trail["deliveries"][0]["status"] == "delivered"
    store.close()


def test_cli_bind_status_and_health(tmp_path, capsys):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    coord = tmp_path / "coord.db"
    rc = cli.main(["bind", "--db", str(coord), "--repo", "r/x", "--board", "me",
                   "--issue", "192", "--task", "t_dev", "--owner", "dev"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_id"] == "t_dev"

    rc = cli.main(["status", "--db", str(coord), "--kanban-db", str(db)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["links"] == 1

    rc = cli.main(["health", "--db", str(coord)])
    assert rc == 0 and json.loads(capsys.readouterr().out)["healthy"] is True


def test_cli_bind_conflict_exit_code(tmp_path, capsys):
    coord = tmp_path / "coord.db"
    cli.main(["bind", "--db", str(coord), "--repo", "r/x", "--issue", "1", "--task", "t_a"])
    rc = cli.main(["bind", "--db", str(coord), "--repo", "r/x", "--issue", "1", "--task", "t_b"])
    assert rc == 23
    assert "already linked" in capsys.readouterr().err


def test_cli_conflict_blocks_on_overlap(tmp_path, capsys):
    coord = tmp_path / "coord.db"
    store = Store(coord)
    store.upsert_claim("t_other", changed_paths=["README.md"])
    store.close()
    rc = cli.main(["conflict", "--db", str(coord), "--changed", "README.md"])
    assert rc == 20
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_cli_reserve_and_conflict(tmp_path, capsys):
    coord = tmp_path / "coord.db"
    cli.main(["reserve", "--db", str(coord), "--scope", "frontend/", "--issue", "182"])
    capsys.readouterr()  # flush the reserve output
    rc = cli.main(["conflict", "--db", str(coord), "--changed", "frontend/x.ts"])
    assert rc == 20
    report = json.loads(capsys.readouterr().out)
    assert report["conflicts"][0]["type"] == "reservation"


def test_cli_reconcile_no_github(tmp_path, capsys):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_linked")
    add_task(db, "t_free")
    coord = tmp_path / "coord.db"
    cli.main(["bind", "--db", str(coord), "--repo", "r/x", "--board", "me",
              "--issue", "1", "--task", "t_linked"])
    capsys.readouterr()  # flush the bind output
    rc = cli.main(["reconcile", "--db", str(coord), "--kanban-db", str(db), "--no-github"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["linked"] == ["t_linked"] and "t_free" in out["unlinked_cards"]


def test_cli_dedupe_removes_ingest_duplicates(tmp_path, capsys):
    from tools.tests._gks_helpers import board

    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    kb = board(db)
    marker = "<!-- gks:v1 id=issue:1 event=r:issue_comment:1:1 channel=ingest -->"
    kb.add_comment("t_dev", f"{marker}\nA\n")
    kb.add_comment("t_dev", f"{marker}\nA\n")
    kb.close()

    rc = cli.main(["dedupe", "--task", "t_dev", "--kanban-db", str(db)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["duplicates_removed"] == 1
    assert out["kept"]
