"""Shared test helpers for the GitHub <-> Kanban sync suite."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

import httpx

from tools.github_kanban_sync.github import GitHubClient
from tools.github_kanban_sync.kanban import KanbanBoard

_KANBAN_SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT,
    status TEXT NOT NULL, priority INTEGER DEFAULT 0, created_by TEXT,
    created_at INTEGER NOT NULL, started_at INTEGER, completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch', workspace_path TEXT,
    branch_name TEXT, block_kind TEXT, result TEXT
);
CREATE TABLE task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    author TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, run_id INTEGER,
    kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, profile TEXT,
    step_key TEXT, status TEXT NOT NULL, started_at INTEGER NOT NULL,
    ended_at INTEGER, outcome TEXT, summary TEXT, metadata TEXT, error TEXT
);
"""


def make_kanban_db(tmp_path: Path) -> Path:
    db = tmp_path / "kanban.db"
    con = sqlite3.connect(db)
    con.executescript(_KANBAN_SCHEMA)
    con.commit()
    con.close()
    return db


def add_task(db: Path, task_id: str, *, title: str = "t", assignee: str = "sdlc-developer",
             status: str = "running", branch: str | None = None, block_kind: str | None = None,
             created_at: int = 1_700_000_000) -> None:
    con = sqlite3.connect(db)
    con.execute(
        "INSERT OR REPLACE INTO tasks(id,title,assignee,status,branch_name,block_kind,created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (task_id, title, assignee, status, branch, block_kind, created_at),
    )
    con.commit()
    con.close()


def add_run(db: Path, task_id: str, *, metadata: str | None = None,
            status: str = "done") -> None:
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO task_runs(task_id,status,started_at,metadata) VALUES (?,?,?,?)",
        (task_id, status, 1_700_000_000, metadata),
    )
    con.commit()
    con.close()


def board(db: Path, author: str = "github-kanban-sync") -> KanbanBoard:
    return KanbanBoard(db, author=author)


def client_with(handler: Callable[[httpx.Request], httpx.Response],
                token: str = "test-token") -> GitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://api.github.com", transport=transport,
                        headers={"Authorization": f"Bearer {token}"})
    return GitHubClient(token, repo="askarahodov/multi-agent-workflow", http_client=http,
                        sleep=lambda _s: None)


def json_response(payload: Any, status: int = 200, headers: dict[str, str] | None = None):
    return httpx.Response(status, json=payload, headers=headers or {})
