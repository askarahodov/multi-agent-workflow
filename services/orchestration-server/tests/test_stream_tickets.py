"""Regression tests for the isolated, durable stream-ticket primitive."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing
import os
import sqlite3

import pytest

from orchestration_server.stream_tickets import StreamTicketStore, StreamTicketRateLimited


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


def test_lost_store_never_recreates_a_world_readable_database(tmp_path):
    """Re-issuing and redeeming after loss must not resurrect the DB."""
    path = tmp_path / "tickets with spaces.db"
    store = StreamTicketStore(path)
    token = store.issue(principal="alice", run_id="run", transport="sse")
    path.unlink()
    # sqlite3.connect(path) normally recreates a missing file under the
    # process umask; every runtime operation must instead fail closed.
    operations = (
        lambda: store.issue(principal="alice", run_id="run", transport="sse"),
        lambda: store.redeem(token, principal="alice", run_id="run", transport="sse"),
        lambda: store.principal_for_ticket(token, run_id="run", transport="sse"),
        lambda: store.revoke(principal="alice", run_id="run"),
    )
    for operation in operations:
        with pytest.raises((FileNotFoundError, sqlite3.OperationalError)):
            operation()
        assert not path.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_runtime_permission_drift_is_rejected_without_repair(tmp_path):
    path = tmp_path / "tickets.db"
    store = StreamTicketStore(path)
    token = store.issue(principal="alice", run_id="run", transport="sse")
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        store.issue(principal="alice", run_id="run", transport="sse")
    with pytest.raises(PermissionError, match="owner-only"):
        store.redeem(token, principal="alice", run_id="run", transport="sse")
    assert path.stat().st_mode & 0o777 == 0o644
    # Once the operator restores private permissions, the original
    # unconsumed ticket is usable rather than silently invalidated.
    path.chmod(0o600)
    assert store.redeem(token, principal="alice", run_id="run", transport="sse")


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink substitution")
def test_runtime_symlink_substitution_is_rejected(tmp_path):
    path = tmp_path / "tickets.db"
    store = StreamTicketStore(path)
    token = store.issue(principal="alice", run_id="run", transport="sse")
    other = tmp_path / "other.db"
    StreamTicketStore(other)
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(ValueError, match="regular file"):
        store.redeem(token, principal="alice", run_id="run", transport="sse")


def test_revoke_run_does_not_affect_other_runs_or_principals(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    first = store.issue(principal="alice", run_id="r1", transport="sse")
    second = store.issue(principal="alice", run_id="r2", transport="sse")
    third = store.issue(principal="bob", run_id="r1", transport="sse")
    assert store.revoke(principal="alice", run_id="r1") == 1
    assert not store.redeem(first, principal="alice", run_id="r1", transport="sse")
    assert store.redeem(second, principal="alice", run_id="r2", transport="sse")
    assert store.redeem(third, principal="bob", run_id="r1", transport="sse")


def test_revoke_principal_invalidates_all_outstanding_tickets(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    first = store.issue(principal="alice", run_id="r1", transport="sse")
    second = store.issue(principal="alice", run_id="r2", transport="websocket")
    assert store.revoke(principal="alice") == 2
    assert store.revoke(principal="alice") == 0
    assert not store.redeem(first, principal="alice", run_id="r1", transport="sse")
    assert not store.redeem(second, principal="alice", run_id="r2", transport="websocket")


def test_invalid_ttl_types_are_rejected(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    for invalid_ttl in (True, 0, 31, 1.5, "10"):
        with pytest.raises(ValueError):
            store.issue(principal="alice", run_id="r", transport="sse", ttl_seconds=invalid_ttl)


def test_issuance_prunes_expired_consumed_and_unconsumed_rows(tmp_path):
    current = [100.0]
    store = StreamTicketStore(tmp_path / "tickets.db", now=lambda: current[0])
    consumed = store.issue(principal="alice", run_id="run", transport="sse")
    expired = store.issue(principal="alice", run_id="run", transport="websocket")
    assert store.redeem(consumed, principal="alice", run_id="run", transport="sse")
    current[0] = 131.0
    fresh = store.issue(principal="alice", run_id="run", transport="sse")
    with sqlite3.connect(tmp_path / "tickets.db") as db:
        assert db.execute("SELECT COUNT(*) FROM stream_tickets").fetchone()[0] == 1
    assert not store.redeem(expired, principal="alice", run_id="run", transport="websocket")
    assert store.redeem(fresh, principal="alice", run_id="run", transport="sse")


def test_issuance_budget_shared_and_reset_on_expiration(tmp_path):
    current = [100.0]
    db = tmp_path / "shared.db"
    first = StreamTicketStore(db, now=lambda: current[0])
    other_worker = StreamTicketStore(db, now=lambda: current[0])
    for index in range(60):
        store = first if index % 2 else other_worker
        store.issue(principal="alice", run_id="run", transport="sse")
    with pytest.raises(StreamTicketRateLimited):
        first.issue(principal="alice", run_id="run", transport="sse")
    # Budget is principal scoped, not global.
    other_worker.issue(principal="bob", run_id="run", transport="sse")
    current[0] = 161.0
    first.issue(principal="alice", run_id="run", transport="sse")


def _process_redeem(args: tuple[str, str]) -> bool:
    path, ticket = args
    return StreamTicketStore(path).redeem(
        ticket, principal="alice", run_id="run", transport="sse"
    )


def _process_issue(path: str) -> str:
    try:
        StreamTicketStore(path).issue(principal="alice", run_id="run", transport="sse")
    except StreamTicketRateLimited:
        return "rate-limited"
    return "issued"


def test_one_time_redemption_is_atomic_across_worker_processes(tmp_path):
    path = str(tmp_path / "tickets.db")
    token = StreamTicketStore(path).issue(
        principal="alice", run_id="run", transport="sse"
    )
    with ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        claims = list(pool.map(_process_redeem, [(path, token)] * 12))
    assert claims.count(True) == 1
    assert claims.count(False) == 11


def test_issuance_budget_is_atomic_across_worker_processes(tmp_path):
    path = str(tmp_path / "tickets.db")
    with ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        attempts = list(pool.map(_process_issue, [path] * 68))
    assert attempts.count("issued") == 60
    assert attempts.count("rate-limited") == 8


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_ticket_database_created_with_owner_only_permissions(tmp_path):
    path = tmp_path / "private.db"
    store = StreamTicketStore(path)
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(stream_tickets)")}
        assert "idx_stream_tickets_expires" in indexes
    store.issue(principal="alice", run_id="run", transport="sse")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_ticket_database_rejects_world_or_group_readable_existing_file(tmp_path):
    path = tmp_path / "exposed.db"
    path.touch(mode=0o600)
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        StreamTicketStore(path)
    assert path.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_ticket_database_rejects_symlink_path(tmp_path):
    destination = tmp_path / "real.db"
    StreamTicketStore(destination)
    alias = tmp_path / "alias.db"
    alias.symlink_to(destination)
    with pytest.raises(ValueError, match="regular file"):
        StreamTicketStore(alias)
