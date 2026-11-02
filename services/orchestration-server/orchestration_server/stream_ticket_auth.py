"""Ticket validation for browser SSE and WebSocket handshakes.

The current product uses global API-key roles rather than per-run ownership.
Revoked keys stop authorizing new connections because the subject is checked
against the current configured key sets at every redemption.
"""
from __future__ import annotations

import asyncio

import hashlib
from typing import Awaitable, Callable

from shared import auth_middleware as auth_policy
from shared.auth_middleware import AuthContext, Role

from .stream_tickets import StreamTicketStore, Transport


def _subject(api_key: str) -> str:
    return f"key-{hashlib.sha256(api_key.encode()).hexdigest()[:12]}"


def resolve_ticket_subject(principal: str) -> AuthContext | None:
    if not auth_policy.AUTH_ENABLED:
        if principal == "development":
            return AuthContext(api_key="dev", roles={Role.READ}, subject="development")
        return None
    for key in (
        auth_policy.READ_API_KEYS
        | auth_policy.WRITE_API_KEYS
        | auth_policy.ADMIN_API_KEYS
    ):
        if _subject(key) == principal:
            roles = auth_policy.resolve_api_key_roles(key)
            if Role.READ in roles:
                return AuthContext(api_key="", roles=roles, subject=principal)
    return None


async def redeem_stream_ticket(
    store: StreamTicketStore,
    ticket: str,
    *,
    run_id: str,
    transport: Transport,
    can_read_run: Callable[[AuthContext, str], Awaitable[bool]],
) -> bool:
    """Validate current authorization, then atomically consume the ticket."""
    principal = await asyncio.to_thread(
        store.principal_for_ticket, ticket, run_id=run_id, transport=transport
    )
    if principal is None:
        return False
    auth = resolve_ticket_subject(principal)
    if auth is None or not await can_read_run(auth, run_id):
        return False
    return await asyncio.to_thread(
        store.redeem, ticket, principal=principal, run_id=run_id, transport=transport
    )
