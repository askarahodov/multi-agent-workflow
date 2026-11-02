"""Regression tests for the isolated, durable stream-ticket primitive."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from orchestration_server.stream_tickets import StreamTicketStore


def test_scopes_replay_and_no_plaintext_storage(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db", now=lambda: 1000.0)
    ticket = store.issue(principal="alice", run_id="run-a", transport="sse")
    assert not store.redeem(ticket, principal="bob", run_id="run-a", transport="sse")
    assert not store.redeem(ticket, principal="alice", run_id="run-b", transport="sse")
    assert not store.redeem(ticket, principal="alice", run_id="run-a", transport="websocket")
    assert store.redeem(ticket, principal="alice", run_id="run-a", transport="sse")
    assert not store.redeem(ticket, principal="alice", run_id="run-a", transport="sse")
    with sqlite3.connect(tmp_path / "tickets.db") as db:
        stored = db.execute("SELECT digest FROM stream_tickets").fetchone()[0]
    assert stored != ticket
    assert len(stored) == 64


def test_expiration_is_strict_and_ttl_is_bounded(tmp_path):
    current = [20.0]
    store = StreamTicketStore(tmp_path / "tickets.db", now=lambda: current[0])
    ticket = store.issue(principal="a", run_id="r", transport="websocket", ttl_seconds=2)
    current[0] = 22.0
    assert not store.redeem(ticket, principal="a", run_id="r", transport="websocket")
    with pytest.raises(ValueError):
        store.issue(principal="a", run_id="r", transport="sse", ttl_seconds=31)
    with pytest.raises(ValueError):
        store.issue(principal="", run_id="r", transport="sse")


def test_concurrent_redemption_only_one_wins_across_connections(tmp_path):
    path = tmp_path / "tickets.db"
    store = StreamTicketStore(path)
    ticket = store.issue(principal="a", run_id="r", transport="websocket")
    def attempt(_):
        independent_store = StreamTicketStore(path)
        return independent_store.redeem(
            ticket, principal="a", run_id="r", transport="websocket"
        )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(16)))
    assert results.count(True) == 1
    assert results.count(False) == 15


def test_store_failure_does_not_grant_access(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    ticket = store.issue(principal="a", run_id="r", transport="sse")
    (tmp_path / "tickets.db").unlink()
    # No in-process fallback to previously issued capabilities.
    with pytest.raises(sqlite3.OperationalError):
        store.redeem(ticket, principal="a", run_id="r", transport="sse")
