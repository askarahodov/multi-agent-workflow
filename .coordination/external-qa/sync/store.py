"""Durable state: processed QA responses, key/value, request sequence."""
import sqlite3
import time

from . import config as C

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_responses(
  response_id TEXT PRIMARY KEY,
  content_sha TEXT,
  processed_at TEXT,
  request_id TEXT
);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS req_seq(req_date TEXT PRIMARY KEY, last_seq INTEGER);
"""


def connect():
    C.SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    C.LOG_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(C.STATE_DB), timeout=30)
    con.executescript(_SCHEMA)
    con.commit()
    return con


def get_kv(con, key, default=None):
    row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_kv(con, key, value):
    con.execute(
        "INSERT INTO kv(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    con.commit()


def response_state(con, rid):
    """Return (content_sha, request_id) or None."""
    return con.execute(
        "SELECT content_sha, request_id FROM processed_responses WHERE response_id=?", (rid,)
    ).fetchone()


def mark_response(con, rid, sha, request_id):
    con.execute(
        "INSERT INTO processed_responses(response_id,content_sha,processed_at,request_id) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(response_id) DO UPDATE SET "
        "content_sha=excluded.content_sha, processed_at=excluded.processed_at, "
        "request_id=excluded.request_id",
        (rid, sha, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), request_id),
    )
    con.commit()


def next_seq(con, date_str):
    row = con.execute("SELECT last_seq FROM req_seq WHERE req_date=?", (date_str,)).fetchone()
    n = (row[0] if row else 0) + 1
    con.execute(
        "INSERT INTO req_seq(req_date,last_seq) VALUES(?,?) "
        "ON CONFLICT(req_date) DO UPDATE SET last_seq=excluded.last_seq",
        (date_str, n),
    )
    con.commit()
    return n
