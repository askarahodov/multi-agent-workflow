"""Kanban -> GitHub publishing (Issue #192 §3).

Publishes a linked card's state (status / assignee / blocker / branch / PR /
acceptance evidence) to **its own** Issue — never a new one — as a single
*versioned* comment that is updated in place:

* one marker comment per Issue (``<!-- gks:v1 issue=<n> channel=publish rev=<r> -->``)
  is found and ``PATCH``-ed, so re-publishing never duplicates;
* a content hash short-circuits no-op updates entirely;
* a per-Issue minimum interval rate-limits writes.

An Issue is moved to ``closed`` **only** when merge + required CI + acceptance
evidence are all confirmed (``close_if_confirmed``). A card reaching ``done`` on
its own never closes the Issue — that is the whole point of the gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Optional

from . import links as links_mod
from .config import Settings
from .store import Store

_PUBLISH_MARKER = "<!-- gks:v1 issue={issue} channel=publish"
_PUBLISH_REV_RE = re.compile(r"channel=publish rev=(\d+)")
CLOSING_STATES = {"done", "archived"}


def _parse_marker_rev(body: str) -> Optional[int]:
    """Return the ``rev`` embedded in a published marker comment, if present."""
    match = _PUBLISH_REV_RE.search(body or "")
    return int(match.group(1)) if match else None


# Task-event kinds that carry externally meaningful state.
PUBLISHABLE_KINDS = {
    "status_changed", "blocked", "unblocked", "claimed", "completed", "created",
    "promoted", "review_requested", "changes_requested", "spawned", "released",
    "comment.added", "github.sync",
}


def render_publish_comment(
    *, issue: int, task: dict[str, Any], link: dict[str, Any], rev: int,
    blocker: Optional[str], acceptance: list[Any],
) -> str:
    changed = ", ".join(f"`{p}`" for p in (link.get("changed_paths") or [])[:20]) or "—"
    lines = [
        f"<!-- gks:v1 issue={issue} channel=publish rev={rev} -->",
        "## Kanban → GitHub · статус синхронизирован",
        "",
        f"- **task**: `{task.get('id')}` (board `{link.get('board')}`)",
        f"- **status**: `{task.get('status')}`",
        f"- **assignee**: `{task.get('assignee') or '—'}`",
        f"- **branch**: `{link.get('branch') or '—'}`",
        f"- **PR**: {('#' + str(link.get('pr_number'))) if link.get('pr_number') else '—'}",
        f"- **blocker**: {blocker or '—'}",
        f"- **changed_paths**: {changed}",
        f"- **updated_at**: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
    ]
    if acceptance:
        lines += ["", "**acceptance evidence**:"]
        for item in acceptance[:20]:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('command', '?')}` → {item.get('result', '?')}")
            else:
                lines.append(f"- {item}")
    lines += ["", f"_synced from Kanban by_ `{link.get('owner') or 'github-kanban-sync'}`"]
    return "\n".join(lines)


class Publisher:
    def __init__(self, store: Store, gh, board, settings: Settings, *,
                 now=time.time, min_interval: Optional[float] = None):
        self.store = store
        self.gh = gh
        self.board = board
        self.settings = settings
        self._now = now
        self.min_interval = settings.publish_min_interval if min_interval is None else min_interval

    # -- change discovery --------------------------------------------------
    def collect_changes(self) -> dict[str, Any]:
        cursor = self.store.get_cursor("kanban_events")
        last_id = int(cursor.get("cursor") or 0)
        events = self.board.events_since(last_id)
        max_id = last_id
        touched: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            max_id = max(max_id, int(event["id"]))
            if not self._should_publish(event):
                continue
            touched.setdefault(event["task_id"], []).append(event)
        self.store.set_cursor("kanban_events", cursor=str(max_id))
        return {"last_event_id": max_id, "tasks": sorted(touched), "events": sum(len(v) for v in touched.values())}

    def _should_publish(self, event: dict[str, Any]) -> bool:
        if event.get("kind") not in PUBLISHABLE_KINDS:
            return False
        payload = event.get("payload") or {}
        if isinstance(payload, str):
            payload = {}
        # feedback-loop guard: never re-publish our own ingested board comments.
        if payload.get("author") == self.settings.author:
            return False
        if "gks:v1" in str(payload.get("body", "")):
            return False
        return True

    # -- publishing --------------------------------------------------------
    def publish_task(self, task_id: str, *, force: bool = False) -> dict[str, Any]:
        link = links_mod.get_by_task(self.store, self.settings.board, task_id)
        if link is None:
            return {"task_id": task_id, "status": "unlinked"}
        task = self.board.task(task_id)
        if task is None:
            return {"task_id": task_id, "status": "no_task"}
        issue = int(link["issue_number"])

        run = self.board.latest_run(task_id) or {}
        acceptance = (run.get("metadata") or {}).get("acceptance_tests") or []
        blocker = task.get("block_kind")

        state_feed = f"publish:{issue}"
        state = self._load_state(state_feed)
        marker = _PUBLISH_MARKER.format(issue=issue)
        comment_id = state.get("comment_id")
        rev = int(state.get("rev") or 0)
        # After a journal reset the stored revision is gone. Recover it from the
        # live marker comment so a reset never rewinds the published revision.
        if comment_id is None:
            existing = self._find_publish_comment(issue, marker)
            if existing is not None:
                comment_id = int(existing["id"])
                if rev == 0:
                    rev = _parse_marker_rev(existing.get("body") or "") or 0
        rendered = render_publish_comment(
            issue=issue, task=task, link=link, rev=rev + 1, blocker=blocker,
            acceptance=acceptance,
        )
        # The hash covers the *stable* content only: the volatile revision line and
        # the render timestamp are excluded, so a no-op publish is recognised.
        content = "\n".join(
            line for line in rendered.splitlines()
            if not line.startswith("- **updated_at**") and not line.startswith("<!-- gks:v1")
        )
        digest = hashlib.sha256(content.encode()).hexdigest()
        if not force and digest == state.get("hash"):
            return {"task_id": task_id, "status": "unchanged", "issue": issue}
        if not force and not self.store.allow(state_feed, self.min_interval, now=self._now()):
            return {"task_id": task_id, "status": "rate_limited", "issue": issue}

        rev = rev + 1
        body = render_publish_comment(issue=issue, task=task, link=link, rev=rev,
                                      blocker=blocker, acceptance=acceptance)
        if comment_id:
            self.gh.update_issue_comment(int(comment_id), body)
            action = "updated"
        else:
            created = self.gh.post_issue_comment(issue, body)
            comment_id = created.get("id")
            action = "created"
        self.store.touch(state_feed, now=self._now())
        self._save_state(state_feed, rev=rev, hash=digest, comment_id=comment_id)
        self.store.record_delivery(
            f"publish:{task_id}:{rev}", "github", "delivered", target=f"issue#{issue}",
            detail=action, correlation_id=f"issue:{issue}",
        )
        return {"task_id": task_id, "status": action, "issue": issue, "rev": rev,
                "comment_id": comment_id}

    def publish_pending(self, *, force: bool = False) -> dict[str, Any]:
        changes = self.collect_changes()
        results = [self.publish_task(task_id, force=force) for task_id in changes["tasks"]]
        return {"scanned": changes, "results": results}

    def _find_publish_comment(self, issue: int, marker: str) -> Optional[dict[str, Any]]:
        for comment in self.gh.list_all_issue_comments(issue):
            if marker in (comment.get("body") or ""):
                return comment
        return None

    def _load_state(self, feed: str) -> dict[str, Any]:
        raw = self.store.get_cursor(feed).get("cursor")
        if not raw:
            return {"rev": 0, "hash": None, "comment_id": None}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {"rev": 0, "hash": None, "comment_id": None}

    def _save_state(self, feed: str, *, rev: int, hash: str, comment_id: Any) -> None:
        self.store.set_cursor(feed, cursor=json.dumps(
            {"rev": rev, "hash": hash, "comment_id": comment_id}))

    # -- closing gate ------------------------------------------------------
    def close_if_confirmed(self, issue: int) -> dict[str, Any]:
        """Close the Issue only on confirmed merge + CI + acceptance evidence."""
        link = links_mod.get_by_issue(self.store, self.settings.repo, issue)
        if link is None:
            return {"issue": issue, "closed": False, "reason": "unlinked"}
        pr_number = link.get("pr_number")
        if not pr_number:
            return {"issue": issue, "closed": False, "reason": "no_linked_pr"}
        try:
            pr = self.gh.get_pull(int(pr_number)).data or {}
        except Exception as exc:  # noqa: BLE001
            return {"issue": issue, "closed": False, "reason": f"pr_unreadable:{exc}"}
        if not pr.get("merged"):
            return {"issue": issue, "closed": False, "reason": "pr_not_merged"}
        merge_sha = pr.get("merge_commit_sha") or (pr.get("head") or {}).get("sha")
        ci = self._ci_state(merge_sha) if merge_sha else "unknown"
        if ci != "success":
            return {"issue": issue, "closed": False, "reason": f"ci_{ci}"}
        task = self.board.task(link["task_id"])
        run = self.board.latest_run(link["task_id"]) or {}
        acceptance = (run.get("metadata") or {}).get("acceptance_tests") or []
        if not acceptance:
            return {"issue": issue, "closed": False, "reason": "no_acceptance_evidence"}
        if not task or not task.get("status") in CLOSING_STATES:
            return {"issue": issue, "closed": False, "reason": "task_not_done"}
        self.gh.patch_issue(issue, state="closed")
        self.store.record_delivery(
            f"close:{issue}", "github", "delivered", target=f"issue#{issue}",
            detail=f"closed after merge {str(merge_sha)[:9]} ci={ci}", correlation_id=f"issue:{issue}",
        )
        return {"issue": issue, "closed": True, "merge_sha": merge_sha, "ci": ci}

    def _ci_state(self, sha: str) -> str:
        try:
            combined = self.gh.combined_status(sha).data or {}
            runs = self.gh.check_runs(sha).data or {}
        except Exception:  # noqa: BLE001
            return "unknown"
        states = [c.get("state") for c in combined.get("statuses", [])]
        conclusions = [r.get("conclusion") for r in runs.get("check_runs", [])]
        all_states = [s for s in states + conclusions if s]
        if not all_states:
            return "unknown"
        if any(s in ("failure", "error", "timed_out", "cancelled", "action_required")
               for s in all_states):
            return "failure"
        if any(s in ("pending", "in_progress", "queued") for s in all_states):
            return "pending"
        return "success"
