"""Authorization boundary for issuing one-time stream capabilities.

Not connected to API routes or enabled by default. The caller supplies the
existing authenticated context and run lookup; no URL/query credentials are
accepted by this service.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from shared.auth_middleware import AuthContext, Role

from .stream_tickets import StreamTicketStore, Transport


class StreamTicketIssuer:
    """Issue only after explicit READ permission and run visibility checks.

    A future HTTP handler must authenticate via headers and pass the exact
    context from the authentication middleware. Per-run access rules must be
    enforced by can_read_run; validating existence alone is not sufficient in
    a multi-tenant deployment.
    """

    def __init__(
        self,
        store: StreamTicketStore,
        *,
        can_read_run: Callable[[AuthContext, str], Awaitable[bool]],
    ) -> None:
        self._store = store
        self._can_read_run = can_read_run

    async def issue(
        self, *, auth: AuthContext, run_id: str, transport: Transport
    ) -> str:
        if not auth.subject or Role.READ not in auth.roles:
            raise PermissionError("read authorization required")
        if not run_id or transport not in ("sse", "websocket"):
            raise ValueError("invalid stream ticket request")
        if not await self._can_read_run(auth, run_id):
            # Prevent leaking whether a run exists to an unauthorized principal.
            raise PermissionError("run is not accessible")
        return self._store.issue(
            principal=auth.subject, run_id=run_id, transport=transport
        )
