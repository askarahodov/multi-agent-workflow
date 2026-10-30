"""Reproducible E2E / idempotency probe for ``tools/github_kanban_sync`` (Issue #192).

Run from the repo root; read-only unless ``GKS_E2E_WRITE=1``.

This probe is the evidence driver for the board-level idempotency rework. The
GitHub→Kanban ingest marker now embeds the full ``source_event_id`` and
``Ingestor.deliver`` refuses to append a comment that is already on the card, so
an event survives a journal reset without re-duplicating.

Phases (all against the REAL board with a PERSISTENT ledger):

1. ingest Issue #192's comments with the persistent ledger  → deliveries
2. ingest again with the SAME ledger                        → 0 new (ledger level)
3. ingest with a FRESH ledger (simulated journal reset)     → 0 new board comments
   (board level guard; delivery status ``duplicate``)
4. publish the card back to the linked Issue (write mode only)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("GKS_REPO_ROOT", "."))

from tools.github_kanban_sync import links, observability
from tools.github_kanban_sync.config import Settings, resolve_token
from tools.github_kanban_sync.github import GitHubClient
from tools.github_kanban_sync.ingest import Ingestor
from tools.github_kanban_sync.kanban import KanbanBoard
from tools.github_kanban_sync.publish import Publisher
from tools.github_kanban_sync.store import Store

REPO = "askarahodov/multi-agent-workflow"
ISSUE = 192
TASK = "t_02d18f3e"
WRITE = os.environ.get("GKS_E2E_WRITE") == "1"


def show(label, obj):
    print(f"\n===== {label} =====")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def board_ingest(board: KanbanBoard, task_id: str) -> dict:
    comments = board.ingest_comments(task_id)
    return {
        "count": len(comments),
        "ids": [c["id"] for c in comments],
        "markers": [c["body"].splitlines()[0] for c in comments],
    }


def main() -> int:
    token = resolve_token()
    print(f"token resolved: {bool(token)}  write_mode: {WRITE}")
    settings = Settings(repo=REPO, board="me")  # coord_db defaults to the PERSISTENT ledger
    print(f"persistent ledger: {settings.coord_db} (existed={settings.coord_db.exists()})")
    store = Store(settings.coord_db)
    gh = GitHubClient(token, repo=REPO)
    board = KanbanBoard(settings.kanban_db)

    show("live rate_limit", gh.rate_limit().data.get("resources", {}).get("core"))
    links.bind(store, REPO, ISSUE, "me", TASK, owner="sdlc-developer",
               branch="wt/t_02d18f3e", status="running")
    show("link", links.get_by_issue(store, REPO, ISSUE))

    ing = Ingestor(store, gh, board, settings)

    show("board ingest comments (before)", board_ingest(board, TASK))
    show("phase 1 — ingest comments #192 (persistent ledger)",
         ing.ingest_issue_comments(ISSUE, full=True))
    show("board ingest comments (after phase 1)", board_ingest(board, TASK))

    show("phase 2 — re-ingest, SAME ledger (expect new_events 0)",
         ing.ingest_issue_comments(ISSUE))
    show("board ingest comments (after phase 2, expect unchanged)", board_ingest(board, TASK))

    # Phase 3: simulate a full journal reset (new, empty ledger; runbook §9) while
    # pointing at the SAME real board. The board-level guard must absorb it.
    with tempfile.TemporaryDirectory() as td:
        fresh = Store(Path(td) / "coord.db")
        links.bind(fresh, REPO, ISSUE, "me", TASK)
        ing_fresh = Ingestor(fresh, gh, board, settings)
        show("phase 3 — ingest with FRESH ledger after journal reset",
             ing_fresh.ingest_issue_comments(ISSUE))
        show("phase 3 — delivery journal (expect status duplicate)",
             fresh.delivery_journal(5))
        show("board ingest comments (after phase 3, expect UNCHANGED)", board_ingest(board, TASK))
        fresh.close()

    if WRITE:
        pub = Publisher(store, gh, board, settings)
        show("phase 4 — publish card back to linked Issue #192", pub.publish_task(TASK))
        after = gh.get_issue(ISSUE).data
        show("issue #192 total comments after publish (expect 3, 1 publish)",
             {"comments": after["comments"]})

    show("health", observability.health(store, max_lag=10**9))
    store.close()
    board.close()
    gh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
