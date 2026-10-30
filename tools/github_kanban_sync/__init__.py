"""GitHub <-> local Hermes Kanban two-way synchronisation (Issue #192).

This is **developer tooling**, not a runtime dependency of the AI Multi Agent
Workflow product (ref #11). Nothing here is imported by ``orchestration-server``,
``agent-management`` or the shipped Docker images.

The layer keeps a single, idempotent mapping between a GitHub Issue
(``repo + issue_number``) and its local Kanban card (``board + task_id``) and
moves state in both directions:

* **GitHub -> Kanban** (``ingest``): Issues (create/edit/close/reopen/comment),
  Pull Requests (open/update/merge/CI). Every observed change is reduced to a
  ``source_event_id`` and delivered to the owning card with a recorded delivery
  receipt.
* **Kanban -> GitHub** (``publish``): card status / assignee / blocker / branch /
  PR / acceptance evidence is published as a *versioned, deduplicated* comment on
  the **linked** Issue. New Issues are never created. An Issue is closed only
  once merge + required CI + acceptance evidence are confirmed.

Transport is an incremental, ETag/cursor-based poll by default (no public
ingress required); a signature-verified webhook receiver is provided as an
optional accelerator. Both converge on the same ``source_event_id`` key.
"""

from __future__ import annotations

__all__ = [
    "config",
    "store",
    "links",
    "github",
    "kanban",
    "ingest",
    "publish",
    "conflict",
    "webhook",
    "observability",
]

__version__ = "0.1.0"
