"""Ticket validation for browser SSE and WebSocket handshakes.

The current product uses global API-key roles rather than per-run ownership.
Revoked keys stop authorizing new handshakes once that worker's in-memory key
sets are updated. Environment-based key rotation needs coordinated worker
restart/reload; ticket-based streams also require periodic reauthorization.
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


async def active_stream_authorized(
    principal: str,
    run_id: str,
    can_read_run: Callable[[AuthContext, str], Awaitable[bool]],
) -> bool:
    """Check the current role and run read permission for a bound principal."""
    context = resolve_ticket_subject(principal)
    return context is not None and await can_read_run(context, run_id)


async def redeem_stream_ticket_principal(
    store: StreamTicketStore,
    ticket: str,
    *,
    run_id: str,
    transport: Transport,
    can_read_run: Callable[[AuthContext, str], Awaitable[bool]],
) -> str | None:
    """Return bound principal only after successful atomic one-time redemption."""
    principal = await asyncio.to_thread(
        store.principal_for_ticket, ticket, run_id=run_id, transport=transport
    )
    if principal is None or not await active_stream_authorized(
        principal, run_id, can_read_run
    ):
        return None
    consumed = await asyncio.to_thread(
        store.redeem, ticket, principal=principal, run_id=run_id, transport=transport
    )
    return principal if consumed else None


async def redeem_stream_ticket(
    store: StreamTicketStore,
    ticket: str,
    *,
    run_id: str,
    transport: Transport,
    can_read_run: Callable[[AuthContext, str], Awaitable[bool]],
) -> bool:
    """Backwards compatible yes/no redemption for existing service clients."""
    return (await redeem_stream_ticket_principal(
        store, ticket, run_id=run_id, transport=transport,
        can_read_run=can_read_run,
    )) is not None
