"""Keyset (cursor) pagination helpers.

Implements ADR-101 cursor-based pagination: list endpoints accept ``after`` (an
opaque cursor string) and ``limit``, and respond with ``{items, next_cursor}``.
``next_cursor`` is ``null`` when the returned page is the last one.

The cursor is a compact ``"<created_at_ms>:<row_id>"`` token referencing the
last row of the previous page. Pages are ordered by ``(created_at DESC, id DESC)``
so the order is deterministic and stable even for equal timestamps. Because a
cursor encodes the exact row to resume after (rather than an offset), new rows
inserted concurrently do not shift the pagination window.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Tuple

from sqlalchemy import Select, and_, or_
from sqlalchemy import func  # noqa: F401  (kept for timing helpers)

CursorKeyFn = Callable[[Any], Tuple[datetime, str]]


def _to_epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def encode_cursor(created_at: Optional[datetime], row_id: str) -> str:
    """Build an opaque `next_cursor` from a page's last row."""
    return f"{_to_epoch_ms(created_at) if created_at is not None else 0}:{row_id}"


def decode_cursor(after: Optional[str]) -> Optional[Tuple[datetime, str]]:
    """Parse an ``after`` cursor into ``(created_at, row_id)`` or ``None``."""
    if not after:
        return None
    try:
        ms_str, row_id = after.split(":", 1)
        created_at = datetime.fromtimestamp(int(ms_str) / 1000, tz=timezone.utc)
    except (ValueError, IndexError):
        return None
    return created_at, row_id


def apply_keyset_predicate(
    stmt: Select,
    created_at_col: Any,
    row_id_col: Any,
    after: Optional[str],
) -> Select:
    """Constrain a query to rows strictly after the cursor position."""
    decoded = decode_cursor(after)
    if decoded is None:
        return stmt
    cursor_at, cursor_id = decoded
    return stmt.where(
        or_(
            created_at_col < cursor_at,
            and_(created_at_col == cursor_at, row_id_col < cursor_id),
        )
    )


def fetch_one_more(stmt: Select, limit: int) -> Select:
    """Fetch ``limit + 1`` rows so the caller can detect a subsequent page."""
    return stmt.limit(limit + 1)


def split_page(
    rows: List[Any],
    limit: int,
    key_of: CursorKeyFn,
) -> Tuple[List[Any], Optional[str]]:
    """Split ``limit + 1`` fetched rows into ``(page, next_cursor)``.

    ``rows`` are ordered ``(created_at DESC, id DESC)`` and ``key_of(row)``
    returns the row's ``(created_at, id)`` pair.
    """
    has_more = len(rows) > limit
    page = rows[:limit]
    if has_more and page:
        created_at, row_id = key_of(page[-1])
        return page, encode_cursor(created_at, row_id)
    return page, None