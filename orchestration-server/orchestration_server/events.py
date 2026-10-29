"""Run-scoped real-time event streaming over the durable saga journal.

Every orchestration state transition (``run.launched``, ``task.claimed``,
``attempt.completed``, ``task.completed``, ``run.completed``, ``task.blocked``,
...) is appended to the ``saga_events`` table in the same transaction as the
state change (see :class:`orchestration_server.engine.OrchestrationEngine`).
The web UI needs those transitions **as they happen** so it can update task
boards, agent logs and gate statuses without polling the REST API.

Two transports are built on the same tail of the journal:

* **Server-Sent Events** (``GET /api/v1/workflows/runs/{run_id}/events``) for
  browsers that only need server -> client push and want automatic reconnect;
* **WebSocket** (``WS /api/v1/workflows/runs/{run_id}/ws``) for clients that
  need a single long-lived bidirectional channel.

Both read the journal by its monotonically increasing integer primary key
(``events.after`` cursor). Delivery is therefore idempotent and resumable: a
client that reconnects with the id of the last event it saw never receives a
duplicate and never misses a later event that is still within the retained
journal.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import SagaEvent

DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_BATCH_LIMIT = 200
MIN_POLL_INTERVAL = 0.05
MAX_POLL_INTERVAL = 10.0

# A stream tuple: ("event", <serialized saga event>) or ("ping", None) when the
# generator wants the transport to emit a keep-alive frame.
StreamItem = tuple[str, Optional[dict]]


def _utc_iso(value: Optional[datetime]) -> Optional[str]:
    """Serialise a DB timestamp as an unambiguous UTC ISO-8601 string."""
    if value is None:
        return None
    if value.tzinfo is None:
        # SQLite drops tzinfo even for DateTime(timezone=True); the engine
        # treats stored values as UTC.
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def serialize_event(event: SagaEvent) -> dict:
    """Stable wire shape shared by the SSE and WebSocket transports."""
    return {
        "id": event.id,
        "run_id": event.run_id,
        "event": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "payload": event.payload or {},
        "created_at": _utc_iso(event.created_at),
    }


def format_sse(event: dict) -> str:
    """Render one event as a Server-Sent Events frame."""
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['id']}\nevent: {event['event']}\ndata: {data}\n\n"


async def fetch_events(
    session_factory: async_sessionmaker,
    run_id: str,
    after_id: int,
    limit: int = DEFAULT_BATCH_LIMIT,
) -> list[dict]:
    """Return the run's saga events with ``id > after_id`` in ascending order."""
    async with session_factory() as session:
        stmt = (
            select(SagaEvent)
            .where(SagaEvent.run_id == run_id, SagaEvent.id > after_id)
            .order_by(SagaEvent.id)
            .limit(limit)
        )
        rows = (await session.scalars(stmt)).all()
        return [serialize_event(row) for row in rows]


async def stream_events(
    session_factory: async_sessionmaker,
    run_id: str,
    *,
    after_id: int = 0,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_events: Optional[int] = None,
    idle_timeout: Optional[float] = None,
    heartbeat_every: int = 0,
) -> AsyncIterator[StreamItem]:
    """Yield run events as they appear, resumable from ``after_id``.

    ``max_events`` bounds the stream for finite consumers/tests; ``idle_timeout``
    closes a stream that has produced no event for that many seconds;
    ``heartbeat_every`` emits a ``("ping", None)`` item every N idle polls so
    idle connections survive intermediate proxies.
    """
    interval = min(max(poll_interval, MIN_POLL_INTERVAL), MAX_POLL_INTERVAL)
    last = after_id
    sent = 0
    idle_polls = 0
    while True:
        events = await fetch_events(session_factory, run_id, last)
        if not events:
            idle_polls += 1
            if heartbeat_every and idle_polls % heartbeat_every == 0:
                yield ("ping", None)
            if idle_timeout is not None and idle_polls * interval >= idle_timeout:
                return
            await asyncio.sleep(interval)
            continue
        idle_polls = 0
        for event in events:
            last = event["id"]
            sent += 1
            yield ("event", event)
            if max_events is not None and sent >= max_events:
                return
