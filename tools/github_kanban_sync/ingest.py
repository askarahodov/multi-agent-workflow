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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence

from . import links as links_mod
from .ci_evidence import classify_ci_state, observed_ci_state
from .github import GitHubError
from .config import Settings
from .store import Store

HANDOFF_RE = re.compile(r"\b([A-Z0-9]{3,}_HANDOFF|[A-Z0-9]+_\d+_HANDOFF)\b")
_SYNC_MARKER_RE = re.compile(r"<!--\s*gks:v1\b")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _conservative_issue_cursor(
    first_page: tuple[dict[str, Any], ...] | None, prior: Optional[str],
) -> Optional[str]:
    """On multi-page sorted Issue feeds, advance only through page one.

    Page N can shift while page N-1 is read (edits, deletes, new records).
    Items omitted at page boundaries must remain eligible for a later poll.
    A one-second overlap retains records tied on GitHub's timestamp precision.
    """
    if not first_page:
        return prior
    try:
        parsed = [
            datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
            for item in first_page
        ]
        if not all(ts.tzinfo is not None for ts in parsed):
            return prior
        times = [ts.astimezone(timezone.utc) for ts in parsed]
        safe = max(times) - timedelta(seconds=1)
        if prior:
            prior_dt = datetime.fromisoformat(
                prior.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            safe = max(safe, prior_dt)
        return safe.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
        # Invalid pagination evidence cannot move the durable cursor forward.
        return prior


def _is_pull(issue: dict[str, Any]) -> bool:
    return "pull_request" in issue


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
        cache_key = "gks:paginated-etag:v2:issues"
        migrated = self.store.get_meta(cache_key) == "v2"
        # Older sync versions could persist a first-page ETag and cursor even
        # after skipping later pages. Rebuild once from the complete feed.
        etag = cursor.get("etag") if migrated and not full else None
        params_since = (since or cursor.get("cursor")) if migrated and not full else None
        resp = self.gh.list_issues(since=params_since, etag=etag)
        if resp.not_modified:
            return {"feed": "issues", "new_events": 0, "not_modified": True}
        issues = [i for i in (resp.data or []) if not _is_pull(i)]
        new = 0
        latest_updated = params_since
        for issue in issues:
            new += self._ingest_issue(issue, full=full)
            latest_updated = max(latest_updated or "", issue.get("updated_at") or "")
        if resp.page_count > 1:
            # Only page one's updated_at boundary is safe while later pages
            # may have been reordered; all later records still get delivered.
            latest_updated = _conservative_issue_cursor(resp.first_page, params_since)
        self.store.set_cursor(
            "issues", etag=resp.headers.get("etag"), cursor=latest_updated,
            clear_etag=not bool(resp.headers.get("etag")),
            clear_cursor=latest_updated is None and (not migrated or full),
        )
        self.store.set_meta(cache_key, "v2")
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
        else:
            # A link may be bound after this observation was seen. Backfill
            # without inventing a second event/card.
            self._deliver_to_linked_once(eid, number)
        return new

    # -- comment feed ------------------------------------------------------
    def ingest_issue_comments(self, number: int, *, full: bool = False) -> dict[str, Any]:
        feed = f"comments:{number}"
        cursor = self.store.get_cursor(feed)
        cache_key = f"gks:paginated-etag:v2:{feed}"
        migrated = self.store.get_meta(cache_key) == "v2"
        # One-time full replay also repairs comments skipped by legacy paging.
        since = cursor.get("cursor") if migrated and not full else None
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
            else:
                self._deliver_to_linked_once(eid, number)
            latest = max(latest or "", comment.get("created_at") or "")
        if resp.page_count > 1:
            # Comments are ordered by creation while since filters updates.
            # No safe timestamp high-water mark exists under concurrent edits
            # or deletions, so replay with dedup instead of skipping a handoff.
            latest = since
        self.store.set_cursor(
            feed, cursor=latest,
            clear_cursor=latest is None and (not migrated or full),
        )
        self.store.set_meta(cache_key, "v2")
        return {"feed": feed, "new_events": new, "cursor": latest}

    # -- pull-request feed -------------------------------------------------
    def ingest_pulls(self, *, full: bool = False) -> dict[str, Any]:
        cursor = self.store.get_cursor("pulls")
        cache_key = "gks:paginated-etag:v2:pulls"
        migrated = self.store.get_meta(cache_key) == "v2"
        etag = cursor.get("etag") if migrated and not full else None
        resp = self.gh.list_pulls(state="all", etag=etag)
        if resp.not_modified:
            return {"feed": "pulls", "new_events": 0, "not_modified": True}
        new = 0
        # GitHub often returns newest PR first. Apply associations in
        # ascending GitHub PR-number order so historical records never win.
        for pr in sorted(resp.data or [], key=lambda row: int(row["number"])):
            new += self._ingest_pull(pr)
        self.store.set_cursor(
            "pulls", etag=resp.headers.get("etag"), cursor=_now_iso(),
            clear_etag=not bool(resp.headers.get("etag")),
        )
        self.store.set_meta(cache_key, "v2")
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
        is_new = self.store.record_event(
            eid, "pr",
            {"action": action, "number": number, "title": pr.get("title"),
             "state": pr.get("state"), "merged": merged,
             "head": (pr.get("head") or {}).get("sha"), "base": (pr.get("base") or {}).get("sha"),
             "branch": (pr.get("head") or {}).get("ref"), "url": pr.get("html_url"),
             "issues": issue_numbers},
            repo_sha=(pr.get("merge_commit_sha") if merged else (pr.get("head") or {}).get("sha")),
            correlation_id=f"pr:{number}",
        )
        # Keep active PR association monotonic by GitHub's increasing PR
        # number. A replayed historical PR must never replace a newer
        # replacement and thereby misdirect CI or premature close checks.
        for inum in issue_numbers:
            link = links_mod.get_by_issue(self.store, self.settings.repo, inum)
            if link and (
                link.get("pr_number") is None
                or int(number) >= int(link["pr_number"])
            ):
                links_mod.update(
                    self.store, self.settings.repo, inum,
                    pr_number=number, branch=(pr.get("head") or {}).get("ref"),
                    base_sha=(pr.get("base") or {}).get("sha"),
                    head_sha=(pr.get("merge_commit_sha") if merged else (pr.get("head") or {}).get("sha")),
                    source_event_id=eid,
                )
        # An earlier webhook might have stored the same source_event_id
        # without parsing issue references. Persist targets BEFORE delivery.
        self.store.add_event_issue_targets(eid, issue_numbers)
        if issue_numbers:
            self._deliver_targets(eid, issue_numbers)
        elif is_new:
            self.deliver(eid)
        return int(is_new)

    # -- CI feed -----------------------------------------------------------
    def ingest_ci(
        self, sha: str, *, issue_numbers: Optional[Sequence[int]] = None,
    ) -> dict[str, Any]:
        """Record CI once per SHA+state and fan out to ALL linked cards.

        Re-observation repairs a previously missed delivery (including a
        webhook-created event or late manual Issue/card binding) without
        duplicating board comments.
        """
        state = self.ci_state(sha)
        eid = links_mod.ci_event_id(self.settings.repo, sha, state)
        new = int(self.store.record_event(
            eid, "ci", {"sha": sha, "state": state}, repo_sha=sha,
            correlation_id=f"ci:{sha[:9]}",
        ))
        targets = (
            issue_numbers if issue_numbers is not None
            else [
                int(link["issue_number"]) for link in links_mod.all_links(self.store)
                if link["repo"] == self.settings.repo
                and link["board"] == self.settings.board
                and link.get("head_sha") == sha
            ]
        )
        delivery = self._deliver_targets(eid, targets) if targets else {}
        if not targets and new:
            self.deliver(eid)
        return {"feed": f"ci:{sha}", "new_events": new,
                "state": state, "delivery": delivery}

    def ingest_linked_feeds(self, *, full: bool = False) -> dict[str, Any]:
        """Poll linked Issue comments and PR/merge CI in the normal sync loop.

        No second queue is created. We only poll known, manually linked
        Issues. A SHA is checked once, then delivered to each owning card.
        """
        links = [
            link for link in links_mod.all_links(self.store)
            if link["repo"] == self.settings.repo
            and link["board"] == self.settings.board
        ]
        comments = {}
        by_sha: dict[str, list[int]] = {}
        invalid_shas = []
        for link in links:
            issue = int(link["issue_number"])
            # A card can be bound long after the GitHub Issue was observed.
            # A since-filter or 304 may never return the older Issue again;
            # replay its canonical ledger event directly, without a new card.
            # correlation_id is deliberately human-readable (issue:<number>),
            # not globally unique. A shared ledger can contain multiple repos
            # with the same Issue number; require the canonical repo-scoped key.
            prefix = f"{self.settings.repo}:issue:{issue}:"
            prior = self.store._query(
                "SELECT source_event_id FROM coord_event "
                "WHERE kind='issue' AND correlation_id=? "
                "AND substr(source_event_id, 1, length(?))=? "
                "ORDER BY rowid DESC LIMIT 1",
                (f"issue:{issue}", prefix, prefix),
            )
            if prior:
                self._deliver_to_linked_once(prior[0]["source_event_id"], issue)
            comments[str(issue)] = self.ingest_issue_comments(issue, full=full)
            sha = link.get("head_sha")
            if sha:
                if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                    invalid_shas.append(issue)
                else:
                    by_sha.setdefault(sha, []).append(issue)
        ci = {
            sha: self.ingest_ci(sha, issue_numbers=issues)
            for sha, issues in sorted(by_sha.items())
        }
        return {
            "comments": comments, "ci": ci,
            "invalid_shas": invalid_shas,
            "new_events": (
                sum(int(result.get("new_events", 0)) for result in comments.values())
                + sum(int(result.get("new_events", 0)) for result in ci.values())
            ),
        }

    def retry_pending(self, *, limit: int = 200) -> dict[str, int]:
        """Retry durable failed deliveries independently of poll cursors."""
        pending = self.store.pending_events(limit=limit, repo=self.settings.repo)
        recovered = errors = 0
        for row in pending:
            eid = row["source_event_id"]
            kind = row["kind"]
            payload = _loads(row.get("payload"))
            if kind == "pr":
                targets = [
                    int(n) for n in payload.get("issues", [])
                    if links_mod.get_by_issue(self.store, self.settings.repo, int(n))
                ]
            elif kind == "ci":
                targets = [
                    int(link["issue_number"]) for link in links_mod.all_links(self.store)
                    if link["repo"] == self.settings.repo
                    and link["board"] == self.settings.board
                    and link.get("head_sha") == payload.get("sha")
                ]
            else:
                number = _issue_of(kind, payload)
                targets = [int(number)] if number is not None else []
            outcomes = (
                list(self._deliver_targets(eid, targets).values())
                if targets else [self.deliver(eid)]
            )
            if "error" in outcomes:
                errors += 1
            else:
                self.store.mark_delivered(eid)
                recovered += 1
        return {"attempted": len(pending), "recovered": recovered, "errors": errors}

    def _deliver_targets(
        self, eid: str, issues: Sequence[int],
    ) -> dict[str, str]:
        """Commit delivery state only after EVERY linked recipient finishes.

        Individual deliver() calls mark success for one card, so a later
        success must not erase an earlier failure. Aggregate and enforce a
        final durable pending/complete state regardless of recipient order.
        """
        results = {
            str(issue): self._deliver_to_linked_once(eid, issue)
            for issue in sorted(set(map(int, issues)))
            if links_mod.get_by_issue(self.store, self.settings.repo, issue)
        }
        if "error" in results.values():
            self.store.mark_pending(eid)
        else:
            self.store.mark_delivered(eid)
        return results

    def _deliver_to_linked_once(self, eid: str, issue: int) -> str:
        """Skip a board-level duplicate without appending a receipt per poll."""
        link = links_mod.get_by_issue(self.store, self.settings.repo, issue)
        if not link:
            return "unlinked"
        try:
            if self.board.has_comment_marker(
                link["task_id"], f"event={eid} channel=ingest"
            ):
                return "duplicate"
        except Exception:
            # Let deliver() register an error receipt and a retry instead.
            pass
        return self.deliver(eid, issue_hint=issue)

    def ci_state(self, sha: str) -> str:
        """Collapse combined-status + check-runs into one of success/failure/pending/unknown."""
        try:
            combined = self.gh.combined_status(sha).data or {}
            runs = self.gh.check_runs(sha).data or {}
        except GitHubError:
            # Propagate rate limit, 401/403 and transport failures to the
            # daemon's bounded backoff. They must not masquerade as a fresh
            # "unknown" CI observation with a successful scheduler snapshot.
            raise
        except Exception:  # noqa: BLE001 - malformed local provider response
            return "unknown"
        return observed_ci_state(combined, runs)

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
