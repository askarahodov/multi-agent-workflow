"""Scoped authorization tests for ticket issuance (no live route changes)."""
import pytest
import sqlite3

from shared import auth_middleware as auth_policy
from shared.auth_middleware import AuthContext, Role
from orchestration_server.stream_tickets import StreamTicketStore
from orchestration_server.stream_ticket_issuer import StreamTicketIssuer
from orchestration_server.stream_ticket_auth import _subject, redeem_stream_ticket


def auth(subject: str, roles: set[Role]) -> AuthContext:
    return AuthContext(api_key="test-credential", subject=subject, roles=roles)


async def test_issues_only_after_run_access_check(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    checks = []

    async def can_read(context, run_id):
        checks.append((context.subject, run_id))
        return context.subject == "reader" and run_id == "owned-run"

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    ticket = await issuer.issue(
        auth=auth("reader", {Role.READ}), run_id="owned-run", transport="sse"
    )
    assert checks == [("reader", "owned-run")]
    assert store.redeem(ticket, principal="reader", run_id="owned-run", transport="sse")
    assert not store.redeem(ticket, principal="reader", run_id="owned-run", transport="sse")


async def test_rejects_no_read_role_before_run_lookup(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    checked = []

    async def can_read(context, run_id):
        checked.append(run_id)
        return True

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    with pytest.raises(PermissionError):
        await issuer.issue(auth=auth("reader", set()), run_id="run", transport="sse")
    assert checked == []


async def test_rejects_inaccessible_run_without_issuing(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")

    async def deny(context, run_id):
        return False

    issuer = StreamTicketIssuer(store, can_read_run=deny)
    with pytest.raises(PermissionError, match="not accessible"):
        await issuer.issue(auth=auth("reader", {Role.READ}), run_id="other-run", transport="websocket")
    with sqlite3.connect(tmp_path / "tickets.db") as conn:
        assert conn.execute("SELECT count(*) FROM stream_tickets").fetchone()[0] == 0


async def test_invalid_transport_does_not_call_access_check(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    checks = []

    async def can_read(context, run_id):
        checks.append(run_id)
        return True

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    with pytest.raises(ValueError):
        await issuer.issue(auth=auth("reader", {Role.READ}), run_id="run", transport="invalid")
    assert checks == []


async def test_redemption_rechecks_current_access(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")
    allowed = [True]

    async def can_read(context, run_id):
        return allowed[0] and context.subject == "reader" and run_id == "r"

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    context = auth("reader", {Role.READ})
    ticket = await issuer.issue(auth=context, run_id="r", transport="sse")
    allowed[0] = False
    assert not await issuer.redeem(ticket, auth=context, run_id="r", transport="sse")
    allowed[0] = True
    assert await issuer.redeem(ticket, auth=context, run_id="r", transport="sse")
    assert not await issuer.redeem(ticket, auth=context, run_id="r", transport="sse")


async def test_redemption_requires_matching_principal_protocol_and_role(tmp_path):
    store = StreamTicketStore(tmp_path / "tickets.db")

    async def can_read(context, run_id):
        return True

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    ticket = await issuer.issue(
        auth=auth("alice", {Role.READ}), run_id="r", transport="websocket"
    )
    assert not await issuer.redeem(
        ticket, auth=auth("bob", {Role.READ}), run_id="r", transport="websocket"
    )
    assert not await issuer.redeem(
        ticket, auth=auth("alice", {Role.READ}), run_id="r", transport="sse"
    )
    assert not await issuer.redeem(
        ticket, auth=auth("alice", set()), run_id="r", transport="websocket"
    )
    assert await issuer.redeem(
        ticket, auth=auth("alice", {Role.READ}), run_id="r", transport="websocket"
    )


async def test_ticket_issuance_does_not_block_event_loop(tmp_path):
    import asyncio
    import threading

    store = StreamTicketStore(tmp_path / "tickets.db")
    entered = threading.Event()
    release = threading.Event()
    original = store.issue

    def slow_issue(**kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return original(**kwargs)

    store.issue = slow_issue

    async def can_read(context, run_id):
        return True

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    pending = asyncio.create_task(
        issuer.issue(auth=auth("reader", {Role.READ}), run_id="r", transport="sse")
    )
    try:
        entered_in_time = await asyncio.to_thread(entered.wait, 2)
        assert entered_in_time
        # A synchronous issue() call would block this callback until released.
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.25)
    finally:
        release.set()
    assert await pending


async def test_ticket_redemption_does_not_block_event_loop(tmp_path):
    import asyncio
    import threading

    store = StreamTicketStore(tmp_path / "tickets.db")
    auth_context = auth("reader", {Role.READ})
    ticket = store.issue(principal="reader", run_id="r", transport="sse")
    entered = threading.Event()
    release = threading.Event()
    original = store.redeem

    def slow_redeem(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return original(*args, **kwargs)

    store.redeem = slow_redeem

    async def can_read(context, run_id):
        return True

    issuer = StreamTicketIssuer(store, can_read_run=can_read)
    pending = asyncio.create_task(
        issuer.redeem(ticket, auth=auth_context, run_id="r", transport="sse")
    )
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.25)
    finally:
        release.set()
    assert await pending


async def test_rotated_out_read_key_cannot_redeem_before_reconnect(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_policy, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_policy, "READ_API_KEYS", {"old-reader"})
    monkeypatch.setattr(auth_policy, "WRITE_API_KEYS", set())
    monkeypatch.setattr(auth_policy, "ADMIN_API_KEYS", set())
    store = StreamTicketStore(tmp_path / "tickets.db")
    ticket = store.issue(
        principal=_subject("old-reader"), run_id="run", transport="websocket"
    )

    async def can_read_run(context, run_id):
        return context.subject == _subject("old-reader") and run_id == "run"

    # After a worker reloads key sets, old tickets no longer authorize.
    monkeypatch.setattr(auth_policy, "READ_API_KEYS", {"new-reader"})
    assert not await redeem_stream_ticket(
        store, ticket, run_id="run", transport="websocket",
        can_read_run=can_read_run,
    )
    monkeypatch.setattr(auth_policy, "READ_API_KEYS", {"old-reader"})
    assert await redeem_stream_ticket(
        store, ticket, run_id="run", transport="websocket",
        can_read_run=can_read_run,
    )
    assert not await redeem_stream_ticket(
        store, ticket, run_id="run", transport="websocket",
        can_read_run=can_read_run,
    )
