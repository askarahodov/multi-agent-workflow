"""GitHub -> Kanban ingestion (Issue #192 §2).

Turns observed GitHub changes into local, deduplicated deliveries:

* Issues — ``created`` / ``edited`` / ``closed`` / ``reopened`` / new ``comment``.
* Pull requests — ``opened`` / ``updated`` / ``merged`` (plus their CI state).
* CI — combined status and check-runs for a commit.

Every observation is reduced to a ``source_event_id`` (``links.source_event_id``)
and inserted into the ledger; a duplicate is a no-op, so a poll and a webhook,
or two consecutive polls, never double-deliver.

Delivery target is the **linked** card. An Issue without a link is recorded as an
``unlinked`` finding for :mod:`observability` / ``reconcile`` — the ingest never
invents a card, so no competing queue is created (Issue #192 §1, anti-duplication).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Optional, Sequence

from . import links as links_mod
from .config import Settings
from .store import Store

HANDOFF_RE = re.compile(r"\b([A-Z0-9]{3,}_HANDOFF|[A-Z0-9]+_\d+_HANDOFF)\b")
_SYNC_MARKER_RE = re.compile(r"<!--\s*gks:v1\b")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _is_pull(issue: dict[str, Any]) -> bool:
    return "pull_request" in issue


# Raw GitHub CI vocabulary -> the sync's collapsed state. Shared by the poll
# (``Ingestor.ci_state``) and the webhook so both compute the *same* state token
# and therefore the same ``source_event_id`` for one commit.
CI_FAILURE_STATES = frozenset(
    {"failure", "error", "timed_out", "cancelled", "action_required"}
)
CI_PENDING_STATES = frozenset({"pending", "in_progress", "queued"})


def classify_ci_state(states: "Sequence[Optional[str]]") -> str:
    """Collapse raw statuses/conclusions into success/failure/pending/unknown."""
    raw = [s for s in states if s]
    if not raw:
        return "unknown"
    if any(s in CI_FAILURE_STATES for s in raw):
        return "failure"
    if any(s in CI_PENDING_STATES for s in raw):
        return "pending"
    return "success"


def classify_issue_action(issue: dict[str, Any], prior_state: Optional[str]) -> str:
    state = (issue.get("state") or "").lower()
    if prior_state is None:
        return "created"
    if state == "closed" and prior_state != "closed":
        return "closed"
    if state == "open" and prior_state == "closed":
        return "reopened"
    return "edited"


def is_sync_authored(body: str) -> bool:
    """True for comments/payloads written by the sync itself (feedback-loop guard)."""
    return bool(_SYNC_MARKER_RE.search(body or ""))


class Ingestor:
    def __init__(
        self,
        store: Store,
        gh,
        board,
        settings: Settings,
        *,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.store = store
        self.gh = gh
        self.board = board
        self.settings = settings
        self._log = log or (lambda _msg: None)

    # -- issue feed --------------------------------------------------------
    def ingest_issues(self, *, since: Optional[str] = None, full: bool = False) -> dict[str, Any]:
        cursor = self.store.get_cursor("issues")
        etag = None if full else cursor.get("etag")
        params_since = None if full else (since or cursor.get("cursor"))
        resp = self.gh.list_issues(since=params_since, etag=etag)
        if resp.not_modified:
            return {"feed": "issues", "new_events": 0, "not_modified": True}
        issues = [i for i in (resp.data or []) if not _is_pull(i)]
        new = 0
        latest_updated = params_since
        for issue in issues:
            new += self._ingest_issue(issue, full=full)
            latest_updated = max(latest_updated or "", issue.get("updated_at") or "")
        self.store.set_cursor("issues", etag=resp.headers.get("etag"), cursor=latest_updated)
        return {"feed": "issues", "new_events": new, "not_modified": False,
                "cursor": latest_updated}

    def _prior_issue_state(self, number: int) -> Optional[str]:
        link = links_mod.get_by_issue(self.store, self.settings.repo, number)
        return (link or {}).get("status")

    def _ingest_issue(self, issue: dict[str, Any], *, full: bool) -> int:
        number = issue["number"]
        prior = self._prior_issue_state(number) if not full else "closed" if issue.get("state") == "open" else "open"
        action = classify_issue_action(issue, prior)
        state = (issue.get("state") or "").lower()
        updated_at = issue.get("updated_at")
        # The dedup key depends on the *state + revision*, not the derived action,
        # so an unchanged Issue re-observed on the next poll is a duplicate, and a
        # webhook for the same change reduces to the identical key.
        eid = links_mod.issue_event_id(self.settings.repo, number, state, updated_at)
        new = 1 if self.store.record_event(
            eid, "issue",
            {"action": action, "number": number, "title": issue.get("title"),
             "state": issue.get("state"), "url": issue.get("html_url"),
             "updated_at": updated_at or _now_iso()},
            correlation_id=f"issue:{number}",
        ) else 0
        # keep the link's mirrored status fresh even if the event is a duplicate
        link = links_mod.get_by_issue(self.store, self.settings.repo, number)
        if link:
            links_mod.update(self.store, self.settings.repo, number,
                             status=(issue.get("state") or "").lower())
        if new:
            self.deliver(eid)
        return new

    # -- comment feed ------------------------------------------------------
    def ingest_issue_comments(self, number: int, *, full: bool = False) -> dict[str, Any]:
        feed = f"comments:{number}"
        cursor = self.store.get_cursor(feed)
        since = None if full else cursor.get("cursor")
        resp = self.gh.list_issue_comments(number, since=since)
        new = 0
        latest = since
        for comment in resp.data or []:
            body = comment.get("body") or ""
            if is_sync_authored(body):  # feedback-loop guard: ignore our own comments
                continue
            cid = comment.get("id")
            eid = links_mod.source_event_id(self.settings.repo, "issue_comment", number, cid)
            handoff = bool(HANDOFF_RE.search(body))
            if self.store.record_event(
                eid, "handoff" if handoff else "issue_comment",
                {"issue": number, "comment_id": cid, "author": (comment.get("user") or {}).get("login"),
                 "body": body[:2000], "url": comment.get("html_url"), "handoff": handoff},
                correlation_id=f"issue:{number}",
            ):
                new += 1
                self.deliver(eid)
            latest = max(latest or "", comment.get("created_at") or "")
        self.store.set_cursor(feed, cursor=latest)
        return {"feed": feed, "new_events": new, "cursor": latest}

    # -- pull-request feed -------------------------------------------------
    def ingest_pulls(self, *, full: bool = False) -> dict[str, Any]:
        cursor = self.store.get_cursor("pulls")
        etag = None if full else cursor.get("etag")
        resp = self.gh.list_pulls(state="all", etag=etag)
        if resp.not_modified:
            return {"feed": "pulls", "new_events": 0, "not_modified": True}
        new = 0
        for pr in resp.data or []:
            new += self._ingest_pull(pr)
        self.store.set_cursor("pulls", etag=resp.headers.get("etag"), cursor=_now_iso())
        return {"feed": "pulls", "new_events": new, "not_modified": False}

    def _ingest_pull(self, pr: dict[str, Any]) -> int:
        number = pr["number"]
        merged = bool(pr.get("merged_at"))
        action = "merged" if merged else ("closed" if pr.get("state") == "closed" else "updated")
        # Key on ``updated_at`` only (never the derived action) so poll and
        # webhook converge on one id for the same PR change.
        eid = links_mod.pr_event_id(self.settings.repo, number, pr.get("updated_at"))
        body = pr.get("body") or ""
        issue_numbers = _referenced_issues(body, pr.get("title") or "")
        # Opt-in read-only independent QA delivery, never a product dependency.
        # The Hermes dispatcher remains responsible for claiming the READY card.
        qa_task = os.environ.get("GKS_MIGRATION_QA_TASK_ID")
        head = (pr.get("head") or {}).get("sha") or ""
        if (qa_task and not merged and pr.get("state") == "open"
                and self.settings.migration_issue in issue_numbers):
            from .review_dispatch import request_migration_review
            owner_link = links_mod.get_by_issue(
                self.store, self.settings.repo, self.settings.migration_issue
            )
            request_migration_review(
                self.board, qa_task_id=qa_task,
                issue=self.settings.migration_issue, pr=number, head_sha=head,
                owner_task_id=(owner_link or {}).get("task_id"),
            )
        # Deliver before recording the deduplicated PR event: a missing QA
        # route must not mark the observation consumed and prevent a retry.
        if not self.store.record_event(
            eid, "pr",
            {"action": action, "number": number, "title": pr.get("title"),
             "state": pr.get("state"), "merged": merged,
             "head": (pr.get("head") or {}).get("sha"), "base": (pr.get("base") or {}).get("sha"),
             "branch": (pr.get("head") or {}).get("ref"), "url": pr.get("html_url"),
             "issues": issue_numbers},
            repo_sha=(pr.get("merge_commit_sha") if merged else (pr.get("head") or {}).get("sha")),
            correlation_id=f"pr:{number}",
        ):
            return 0
        # mirror PR facts onto every linked issue
        for inum in issue_numbers:
            link = links_mod.get_by_issue(self.store, self.settings.repo, inum)
            if link:
                links_mod.update(
                    self.store, self.settings.repo, inum,
                    pr_number=number, branch=(pr.get("head") or {}).get("ref"),
                    base_sha=(pr.get("base") or {}).get("sha"),
                    head_sha=(pr.get("merge_commit_sha") if merged else (pr.get("head") or {}).get("sha")),
                )
        self.deliver(eid, issue_hint=issue_numbers[0] if issue_numbers else None)
        return 1

    # -- CI feed -----------------------------------------------------------
    def ingest_ci(self, sha: str) -> dict[str, Any]:
        state = self.ci_state(sha)
        eid = links_mod.ci_event_id(self.settings.repo, sha, state)
        new = 1 if self.store.record_event(
            eid, "ci", {"sha": sha, "state": state}, repo_sha=sha,
            correlation_id=f"ci:{sha[:9]}",
        ) else 0
        if new:
            self.deliver(eid)
        return {"feed": f"ci:{sha}", "new_events": new, "state": state}

    def ci_state(self, sha: str) -> str:
        """Collapse combined-status + check-runs into one of success/failure/pending/unknown."""
        try:
            combined = self.gh.combined_status(sha).data or {}
            runs = self.gh.check_runs(sha).data or {}
        except Exception:  # noqa: BLE001 - CI feed must never crash the sweep
            return "unknown"
        states = [c.get("state") for c in combined.get("statuses", [])]
        conclusions = [r.get("conclusion") for r in runs.get("check_runs", [])]
        return classify_ci_state(states + conclusions)

    # -- delivery ----------------------------------------------------------
    def deliver(self, source_event_id: str, *, issue_hint: Optional[int] = None,
                board_comment: bool = True) -> str:
        """Deliver a recorded event to the owning card; record a receipt.

        Returns ``delivered`` | ``unlinked`` | ``duplicate`` | ``error``.
        """
        rows = self.store._query(
            "SELECT * FROM coord_event WHERE source_event_id=?", (source_event_id,)
        )
        if not rows:
            return "error"
        event = dict(rows[0])
        payload = _loads(event.get("payload"))
        number = issue_hint if issue_hint is not None else _issue_of(event["kind"], payload)
        if number is None:
            self.store.mark_delivered(source_event_id)
            return "delivered"
        link = links_mod.get_by_issue(self.store, self.settings.repo, number)
        if link is None:
            self.store.record_delivery(source_event_id, "kanban", "unlinked", target=None,
                                       detail=f"issue #{number} unlinked",
                                       correlation_id=event.get("correlation_id"))
            self.store.mark_delivered(source_event_id)  # handled: just no local target
            return "unlinked"
        task_id = link["task_id"]
        try:
            if board_comment:
                body = render_kanban_comment(event["kind"], payload, event["correlation_id"],
                                             source_event_id=source_event_id)
                # Board-level idempotency: the ingest marker carries the full
                # ``source_event_id``, so an event already delivered to this card
                # (e.g. after a journal reset) is recognised and NOT re-appended.
                marker = body.splitlines()[0] if body else ""
                if self.board.has_comment_marker(task_id, marker):
                    self.store.record_delivery(
                        source_event_id, "kanban", "duplicate", target=task_id,
                        correlation_id=event.get("correlation_id"),
                        detail=f"issue #{number} -> {task_id} (already on board)",
                    )
                    self.store.mark_delivered(source_event_id)
                    return "duplicate"
                self.board.add_comment(task_id, body)
            self.store.record_delivery(
                source_event_id, "kanban", "delivered", target=task_id,
                correlation_id=event.get("correlation_id"),
                detail=f"issue #{number} -> {task_id}",
            )
            self.store.mark_delivered(source_event_id)
            return "delivered"
        except Exception as exc:  # noqa: BLE001 - fail visible, retry next sweep
            self.store.bump_attempt(source_event_id, str(exc))
            self.store.record_delivery(source_event_id, "kanban", "error", target=task_id,
                                       detail=str(exc), correlation_id=event.get("correlation_id"))
            return "error"


def render_kanban_comment(kind: str, payload: dict[str, Any], correlation_id: Optional[str],
                          *, source_event_id: Optional[str] = None) -> str:
    parts = [f"gks:v1 id={correlation_id or kind}"]
    if source_event_id:
        parts.append(f"event={source_event_id}")
    parts.append("channel=ingest")
    marker = f"<!-- {' '.join(parts)} -->"
    if kind == "handoff":
        head = f"**GitHub → Kanban · handoff** (Issue #{payload.get('issue')})"
    elif kind == "issue_comment":
        head = f"**GitHub → Kanban · comment** (Issue #{payload.get('issue')})"
    elif kind == "pr":
        head = f"**GitHub → Kanban · PR** #{payload.get('number')} `{payload.get('action')}`"
    elif kind == "ci":
        head = f"**GitHub → Kanban · CI** `{payload.get('state')}` @ `{str(payload.get('sha'))[:9]}`"
    elif kind == "issue":
        head = (f"**GitHub → Kanban · issue** (Issue #{payload.get('number')}) "
                f"`{payload.get('action')}`")
    else:
        head = f"**GitHub → Kanban · {kind}**"
    detail = payload.get("body") or payload.get("title") or payload.get("url") or ""
    return f"{marker}\n{head}\n\n> {detail}\n"


def _referenced_issues(*texts: str) -> list[int]:
    found: set[int] = set()
    for text in texts:
        for m in re.finditer(r"#(\d+)", text or ""):
            found.add(int(m.group(1)))
    return sorted(found)


def _issue_of(kind: str, payload: dict[str, Any]) -> Optional[int]:
    if kind in ("issue", "issue_comment", "handoff"):
        return payload.get("number") or payload.get("issue")
    if kind == "pr":
        issues = payload.get("issues") or []
        return int(issues[0]) if issues else None
    return None


def _loads(value: Any) -> dict[str, Any]:
    import json

    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
