"""The ID contract: ``repo + issue_number`` <-> ``board + task_id`` (Issue #192 §1).

One GitHub Issue maps to at most one Kanban card, and one card maps to at most
one Issue. The mapping is:

* **unique** — enforced by the ``issue_link`` primary/unique keys;
* **idempotent** — re-binding the same pair is a field update, never a duplicate;
* **manually bindable** — ``bind`` attaches an *existing* card to an existing
  Issue without cloning it (``force`` is required to move an existing link).

No function here creates a Kanban task or a GitHub Issue. Creation is a separate,
explicit action (``ingest --create-tasks`` for a previously unseen Issue).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from .store import Store

LINK_FIELDS = (
    "pr_number", "branch", "base_sha", "head_sha", "owner",
    "changed_paths", "status", "source_event_id",
)


class LinkConflict(RuntimeError):
    """Raised when a binding would move an already-established link."""


def source_event_id(repo: str, kind: str, object_id: Any, revision: Any) -> str:
    """Canonical dedup key for an observed GitHub change.

    ``<repo>:<kind>:<object_id>:<revision>`` — e.g.
    ``askarahodov/multi-agent-workflow:issue_comment:192:6519063860``.
    """
    return f"{repo}:{kind}:{object_id}:{revision}"


# -- canonical per-kind keys (single source of truth for poll AND webhook) -----
#
# The poll and the webhook must reduce the *same* GitHub change to the *same*
# ``source_event_id`` or the ledger would double-insert and the change would be
# delivered twice. These helpers are that one definition; both transports call
# them, so the keys converge by construction (never build a transport-prefixed
# revision — that is exactly the bug that made issue/pr/ci diverge).

def issue_event_id(repo: str, number: Any, state: Any, updated_at: Any) -> str:
    """Key for an Issue change: identity is ``state`` + ``updated_at``."""
    return source_event_id(repo, "issue", number, f"{(state or '').lower()}:{updated_at or ''}")


def pr_event_id(repo: str, number: Any, updated_at: Any) -> str:
    """Key for a Pull-request change: identity is ``updated_at`` (no action)."""
    return source_event_id(repo, "pr", number, updated_at or "")


def ci_event_id(repo: str, sha: str, state: str) -> str:
    """Key for a CI change: identity is the 9-char ``sha`` prefix + ``state``."""
    return source_event_id(repo, "ci", (sha or "")[:9], state)


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    d["changed_paths"] = json.loads(d.get("changed_paths") or "[]")
    return d


def get_by_issue(store: Store, repo: str, issue_number: int) -> Optional[dict[str, Any]]:
    rows = store._query(
        "SELECT * FROM issue_link WHERE repo=? AND issue_number=?", (repo, int(issue_number))
    )
    return _row_to_dict(rows[0]) if rows else None


def get_by_task(store: Store, board: str, task_id: str) -> Optional[dict[str, Any]]:
    rows = store._query(
        "SELECT * FROM issue_link WHERE board=? AND task_id=?", (board, task_id)
    )
    return _row_to_dict(rows[0]) if rows else None


def all_links(store: Store) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in store._query("SELECT * FROM issue_link ORDER BY issue_number")]


def bind(
    store: Store,
    repo: str,
    issue_number: int,
    board: str,
    task_id: str,
    *,
    force: bool = False,
    changed_paths: Optional[Iterable[str]] = None,
    **fields: Any,
) -> dict[str, Any]:
    """Bind (or re-bind) an Issue to a card. Idempotent for the same pair.

    Raises :class:`LinkConflict` when the Issue or the card is already linked to
    a *different* counterpart and ``force`` is not set — this is what stops the
    sync from silently re-pointing an active card or cloning it.
    """
    existing_issue = get_by_issue(store, repo, issue_number)
    if existing_issue and existing_issue["task_id"] != task_id and not force:
        raise LinkConflict(
            f"Issue #{issue_number} already linked to {existing_issue['task_id']}; "
            "pass force=True to re-point"
        )
    existing_task = get_by_task(store, board, task_id)
    if existing_task and int(existing_task["issue_number"]) != int(issue_number) and not force:
        raise LinkConflict(
            f"task {task_id} already linked to Issue #{existing_task['issue_number']}; "
            "pass force=True to re-point"
        )
    if existing_task and int(existing_task["issue_number"]) != int(issue_number) and force:
        # Drop the stale row so the UNIQUE(board, task_id) key does not clash.
        store._exec(
            "DELETE FROM issue_link WHERE board=? AND task_id=?", (board, task_id)
        )

    changed = sorted(set(changed_paths if changed_paths is not None
                         else (existing_issue or {}).get("changed_paths") or []))
    payload: dict[str, Any] = {
        "pr_number": fields.get("pr_number", (existing_issue or {}).get("pr_number")),
        "branch": fields.get("branch", (existing_issue or {}).get("branch")),
        "base_sha": fields.get("base_sha", (existing_issue or {}).get("base_sha")),
        "head_sha": fields.get("head_sha", (existing_issue or {}).get("head_sha")),
        "owner": fields.get("owner", (existing_issue or {}).get("owner")),
        "status": fields.get("status", (existing_issue or {}).get("status")),
        "source_event_id": fields.get("source_event_id",
                                      (existing_issue or {}).get("source_event_id")),
    }
    now = _iso_now()
    store._exec(
        "INSERT OR REPLACE INTO issue_link(repo, issue_number, board, task_id, pr_number,"
        " branch, base_sha, head_sha, owner, changed_paths, status, source_event_id,"
        " updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            repo, int(issue_number), board, task_id, payload["pr_number"], payload["branch"],
            payload["base_sha"], payload["head_sha"], payload["owner"], json.dumps(changed),
            payload["status"], payload["source_event_id"], now,
            (existing_issue or {}).get("created_at") or now,
        ),
    )
    return get_by_issue(store, repo, issue_number)  # type: ignore[return-value]


def update(
    store: Store,
    repo: str,
    issue_number: int,
    **fields: Any,
) -> Optional[dict[str, Any]]:
    """Patch individual fields of an existing link (no-op when unlinked)."""
    link = get_by_issue(store, repo, issue_number)
    if link is None:
        return None
    kwargs = {k: fields[k] for k in LINK_FIELDS if k in fields}
    if "changed_paths" in kwargs:
        kwargs["changed_paths"] = sorted(set(kwargs["changed_paths"]))
    return bind(store, repo, issue_number, link["board"], link["task_id"], force=True, **kwargs)


def unbind(store: Store, repo: str, issue_number: int) -> bool:
    cur = store._exec(
        "DELETE FROM issue_link WHERE repo=? AND issue_number=?", (repo, int(issue_number))
    )
    return cur.rowcount > 0


def _iso_now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
