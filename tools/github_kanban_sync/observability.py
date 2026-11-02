"""Observability for the sync (Issue #192 §6).

Surfaces exactly what an operator needs to answer "is the sync healthy?":
``last sync``, ``lag``, ``pending events``, ``retries``, ``errors``, the delivery
journal, and the correlation id that ties a GitHub event to its local delivery.
All reads are pure and side-effect free so the health probe is safe to run at any
time, and ``dry-run`` reuses the same collectors.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from .store import Store

SCHEDULER_STATE_KEY = "scheduler:state"


def scheduler_state(store: Store) -> Optional[dict[str, Any]]:
    """Last persisted scheduler/daemon state (``None`` when it never ran)."""
    raw = store.get_meta(SCHEDULER_STATE_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _age_seconds(iso: Optional[str], now: float) -> Optional[float]:
    if not iso:
        return None
    try:
        parsed = time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (ValueError, TypeError):
        return None
    return round(now - parsed, 3)


def health(store: Store, *, now: Optional[float] = None, max_lag: float = 600.0) -> dict[str, Any]:
    now = now if now is not None else time.time()
    counts = store.counts()
    snapshot = store.last_snapshot()
    last_sync = snapshot.get("taken_at") if snapshot else None
    lag = _age_seconds(last_sync, now)
    pending = counts["pending"]
    errors = counts["delivery_errors"]
    scheduler = scheduler_state(store)
    healthy = (lag is None or lag <= max_lag) and errors == 0
    return {
        "healthy": healthy,
        "last_sync": last_sync,
        "lag_seconds": lag,
        "max_lag_seconds": max_lag,
        "pending_events": pending,
        "errors": errors,
        "scheduler_status": (scheduler or {}).get("status"),
        "consecutive_failures": (scheduler or {}).get("consecutive_failures", 0),
        "counts": counts,
    }


def status(store: Store, board=None, *, limit: int = 20) -> dict[str, Any]:
    links = store._query("SELECT * FROM issue_link ORDER BY issue_number")
    cursors = store._query("SELECT * FROM cursor ORDER BY feed")
    return {
        "links": len(links),
        "links_detail": [
            {"issue": r["issue_number"], "task": r["task_id"], "branch": r["branch"],
             "pr": r["pr_number"], "status": r["status"], "owner": r["owner"],
             "updated_at": r["updated_at"]}
            for r in links
        ],
        "cursors": [dict(r) for r in cursors],
        "pending_events": [
            {"source_event_id": e["source_event_id"], "kind": e["kind"],
             "correlation_id": e["correlation_id"], "attempts": e["attempts"],
             "last_error": e["last_error"]}
            for e in store.pending_events(limit)
        ],
        "delivery_journal": store.delivery_journal(limit),
        "scheduler": scheduler_state(store),
        "health": health(store),
    }


def delivery_trail(store: Store, source_event_id: str) -> dict[str, Any]:
    events = store._query("SELECT * FROM coord_event WHERE source_event_id=?", (source_event_id,))
    deliveries = store._query(
        "SELECT * FROM delivery WHERE source_event_id=? ORDER BY id", (source_event_id,)
    )
    return {
        "event": dict(events[0]) if events else None,
        "deliveries": [dict(d) for d in deliveries],
    }
