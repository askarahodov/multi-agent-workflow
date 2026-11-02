"""Hermetic autostart demonstration for ``tools/github_kanban_sync`` (Issue #192).

Proves that events move GitHub <-> Kanban **without any manual step**: a real
:class:`~tools.github_kanban_sync.scheduler.Scheduler` loop is started, and while
it is *waiting* between cycles an external change is injected into both sides
(a new GitHub Issue revision and a Kanban card event). Neither a ``sync`` call nor
any operator action is performed — the running daemon picks both changes up on its
next cycle and delivers them.

Everything is isolated: a fake GitHub transport (``httpx.MockTransport``) and a
throwaway ``kanban.db`` / ``coordination-sync.db`` under a temp dir. The real board
and the real GitHub repo are never touched.

Run from the repo root::

    GKS_REPO_ROOT=$PWD python3 tools/github_kanban_sync/daemon_probe.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("GKS_REPO_ROOT", "."))

import httpx  # noqa: E402

from tools.github_kanban_sync import links, observability  # noqa: E402
from tools.github_kanban_sync.config import Settings  # noqa: E402
from tools.github_kanban_sync.github import GitHubClient  # noqa: E402
from tools.github_kanban_sync.kanban import KanbanBoard  # noqa: E402
from tools.github_kanban_sync.scheduler import Scheduler, SchedulerConfig  # noqa: E402
from tools.github_kanban_sync.store import Store  # noqa: E402
from tools.tests._gks_helpers import add_task, make_kanban_db  # noqa: E402

REPO = "askarahodov/multi-agent-workflow"
ISSUE = 192
TASK = "t_dev"


def main() -> int:
    transcript: list[str] = []

    def emit(line: str = "") -> None:
        transcript.append(line)
        print(line, flush=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        db = make_kanban_db(tmp)
        add_task(db, TASK, title="autostart demo")
        settings = Settings(repo=REPO, board="me",
                            coord_db=tmp / "coordination-sync.db", kanban_db=db)

        # -- fake GitHub with a *mutable* feed ------------------------------
        feed = {"issues": [{"number": ISSUE, "state": "open", "title": "Autostart",
                            "updated_at": "2026-10-30T10:00:00Z",
                            "html_url": f"https://github.com/{REPO}/issues/{ISSUE}"}],
                "comments": [], "pulls": []}
        posted: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/comments"):
                if request.method == "POST":
                    body = json.loads(request.content.decode())
                    posted.append(body)
                    return httpx.Response(201, json={"id": 500})
                return httpx.Response(200, json=feed["comments"])
            if path.endswith("/pulls"):
                return httpx.Response(200, json=feed["pulls"])
            if path.endswith("/issues"):
                return httpx.Response(200, json=feed["issues"])
            return httpx.Response(200, json={})

        http = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
        gh = GitHubClient("fake-token", repo=REPO, http_client=http, sleep=lambda _s: None)

        store = Store(settings.coord_db)
        board = KanbanBoard(db)
        links.bind(store, REPO, ISSUE, "me", TASK, owner="sdlc-developer", branch="wt/t_dev")

        # -- external events injected *while the daemon waits* --------------
        injected = {"done": False}

        def sleep_hook(seconds: float) -> None:
            if not injected["done"]:
                injected["done"] = True
                # (a) GitHub side: the Issue is edited by a human/CI elsewhere
                feed["issues"][0]["updated_at"] = "2026-10-30T10:05:00Z"
                # (b) Kanban side: a card event that must be published back
                board.record_event(TASK, "status_changed",
                                   {"status": "done", "author": "sdlc-developer"})
                emit("[inject] external change: GitHub issue updated + Kanban card event")
            time.sleep(seconds)

        log = lambda line: emit(line)  # noqa: E731
        scheduler = Scheduler(settings, store=store, board=board, gh=gh,
                              config=SchedulerConfig(interval=0.05, backoff_cap=1.0),
                              sleep=sleep_hook, log=log)

        emit("=== autostart demonstration (no manual sync call) ===")
        emit(f"board comments before: {len(board.ingest_comments(TASK))}")
        outcome = scheduler.run(max_iterations=3)
        emit(f"scheduler outcome: {json.dumps(outcome, default=str, sort_keys=True)}")

        ingest = board.ingest_comments(TASK)
        emit(f"board ingest comments after: {len(ingest)}")
        for c in ingest:
            emit(f"  board comment id={c['id']} marker={c['body'].splitlines()[0]}")
        emit(f"github publish comments after: {len(posted)}")
        for body in posted:
            emit(f"  github comment starts: {body['body'].splitlines()[0]}")

        status = observability.status(store)
        emit("=== observability ===")
        emit(json.dumps({"health": status["health"],
                         "scheduler": status["scheduler"]}, indent=2, sort_keys=True, default=str))

        ok = (len(ingest) >= 2 and len(posted) >= 1)
        emit(f"RESULT: {'PASS' if ok else 'FAIL'} "
             "(2 automatic GitHub->Kanban deliveries + 1 automatic Kanban->GitHub publish)")

        store.close()
        board.close()
        gh.close()
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
