"""Opt-in stream-ticket HTTP router factory.

This router is intentionally NOT registered by build_app. Deployment must first
provide a shared durable store, a real per-run authorization callback, audited
logs, and a security-approved migration gate.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from shared.auth_middleware import AuthContext, require_read

from .stream_ticket_issuer import StreamTicketIssuer


class StreamTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transport: Literal["sse", "websocket"]


class StreamTicketResponse(BaseModel):
    ticket: str
    expires_in: int


def create_stream_ticket_router(issuer: StreamTicketIssuer) -> APIRouter:
    """Construct a router; no caller may expose it without explicit opt-in."""
    router = APIRouter()

    @router.post(
        "/workflows/runs/{run_id}/stream-tickets",
        response_model=StreamTicketResponse,
        responses={401: {"description": "Unauthenticated"},
                   403: {"description": "No read permission or run access"},
                   503: {"description": "Ticket store unavailable"}},
    )
    async def issue_stream_ticket(
        run_id: str,
        request: StreamTicketRequest,
        response: Response,
        auth: AuthContext = Depends(require_read),
    ) -> StreamTicketResponse:
        try:
            token = await issuer.issue(auth=auth, run_id=run_id, transport=request.transport)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Stream access denied") from None
        # Unexpected store errors intentionally fail closed, without returning
        # internal exception messages or attempting long-lived URL-key fallback.
        except Exception:
            raise HTTPException(status_code=503, detail="Stream tickets unavailable") from None
        response.headers["Cache-Control"] = "no-store"
        return StreamTicketResponse(ticket=token, expires_in=30)

    return router
