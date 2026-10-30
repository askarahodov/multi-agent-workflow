"""Shared authentication/authorization middleware for FastAPI applications.

Provides API key based authentication with role-based access control.
Designed to be integrated into agent-management, orchestration-server, and runtime-hardening.
"""

from __future__ import annotations

import logging
import re
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Logging redaction – strips API keys and Authorization values from uvicorn
# log records so they never persist in plain text on disk.
#
# IMPORTANT: uvicorn renders access lines through its own ``AccessFormatter``,
# which builds the request line from ``record.args`` (the 5-tuple emitted by
# httptools: client, method, full_path, http_version, status) — it never calls
# ``record.getMessage()``.  Redacting only ``record.msg`` therefore leaves the
# leaked credential in the log.  Both paths are rewritten here, and the
# regression test renders through the real ``uvicorn.logging.AccessFormatter``.
# ---------------------------------------------------------------------------

_API_KEY_RE = re.compile(r"(?i)api_key=[^&\s\"']+")
_AUTHZ_RE = re.compile(r"(?i)authorization:\s*[^\r\n,;\"']+")


def _redact_text(value: str) -> str:
    """Redact credentials inside a single string."""
    value = _API_KEY_RE.sub("api_key=***", value)
    return _AUTHZ_RE.sub("Authorization: ***", value)


def _redact_arg(value: Any) -> Any:
    return _redact_text(value) if isinstance(value, str) else value


def _looks_like_access_record(record: logging.LogRecord) -> bool:
    """True for uvicorn's access records: (client, method, path, ver, status)."""
    args = record.args
    return isinstance(args, tuple) and len(args) == 5 and isinstance(args[-1], int)


class _ApiKeyFilter(logging.Filter):
    """Redact ``api_key=<...>`` / ``Authorization: <...>`` from log records.

    Covers both rendering paths: plain ``logging`` (``record.msg``) and
    uvicorn's ``AccessFormatter`` (``record.args``).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: ARG002
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact_arg(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: _redact_arg(v) for k, v in args.items()}

        # uvicorn access records render from ``record.args``, which is now
        # redacted; their args must stay intact for AccessFormatter.
        if _looks_like_access_record(record):
            return True

        # Plain-logging path: a credential may only become visible once the
        # format string and its arguments are joined, so redact the assembled
        # message and collapse it into ``record.msg``.
        try:
            formatted = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        redacted = _redact_text(formatted)
        if redacted != formatted:
            record.msg = redacted
            record.args = None
        return True


# Module-level instance so we can add it to uvicorn loggers once imported.
api_key_filter = _ApiKeyFilter()

# Configuration via environment variables
API_KEY_HEADER_NAME = os.getenv("API_KEY_HEADER", "X-API-Key")
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
ADMIN_API_KEYS = set(
    k.strip() for k in os.getenv("ADMIN_API_KEYS", "").split(",") if k.strip()
)
READ_API_KEYS = set(
    k.strip() for k in os.getenv("READ_API_KEYS", "").split(",") if k.strip()
)
WRITE_API_KEYS = set(
    k.strip() for k in os.getenv("WRITE_API_KEYS", "").split(",") if k.strip()
)


class Role(str, Enum):
    """Authorization roles for API access."""

    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


def resolve_api_key_roles(api_key: str) -> set[Role]:
    """Resolve the roles granted to an API key.

    Module-level so the HTTP middleware and the WebSocket handshake check share
    the exact same key sets and role semantics (single source of truth).
    """
    roles: set[Role] = set()
    if api_key in ADMIN_API_KEYS:
        roles.add(Role.ADMIN)
        roles.add(Role.WRITE)
        roles.add(Role.READ)
    if api_key in WRITE_API_KEYS:
        roles.add(Role.WRITE)
        roles.add(Role.READ)
    if api_key in READ_API_KEYS:
        roles.add(Role.READ)
    return roles


@dataclass(frozen=True)
class AuthContext:
    """Resolved authentication context for a request."""

    api_key: str
    roles: Set[Role]
    subject: str  # Identifier for the authenticated principal


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates API keys and injects auth context.

    If AUTH_ENABLED=false (development), all requests pass through with a
    default development context.
    """

    def __init__(self, app: FastAPI, *, exempt_paths: Optional[Set[str]] = None) -> None:
        super().__init__(app)
        self.exempt_paths = exempt_paths or {
            "/health",
            "/healthz/live",
            "/healthz/ready",
            "/healthz/startup",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not AUTH_ENABLED:
            # Development mode: inject a default context with all roles
            request.state.auth = AuthContext(
                api_key="dev",
                roles={Role.ADMIN, Role.WRITE, Role.READ},
                subject="development",
            )
            return await call_next(request)

        # Skip auth for exempt paths (health checks, metrics, docs). These stay
        # exempt from the 401 gate, but still receive a read-only auth context so
        # that endpoints carrying Depends(require_read) (e.g. /health, /metrics,
        # /healthz/*) resolve their dependency without requiring a key.
        if request.url.path in self.exempt_paths:
            request.state.auth = AuthContext(
                api_key="exempt",
                roles={Role.READ},
                subject="exempt-path",
            )
            return await call_next(request)

        api_key = self._extract_api_key(request)

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "type": "urn:auth:error:unauthorized",
                    "title": "Unauthorized",
                    "status": 401,
                    "detail": f"Missing API key in '{API_KEY_HEADER_NAME}' header or Authorization: ***",
                },
                headers={"WWW-Authenticate": f'APIKey realm="api"'},
            )

        roles = self._resolve_roles(api_key)
        if not roles:
            return JSONResponse(
                status_code=401,
                content={
                    "type": "urn:auth:error:invalid-key",
                    "title": "Invalid API key",
                    "status": 401,
                    "detail": "The provided API key is not recognized",
                },
                headers={"WWW-Authenticate": f'APIKey realm="api"'},
            )

        request.state.auth = AuthContext(
            api_key=api_key,
            roles=roles,
            subject=self._key_to_subject(api_key),
        )
        return await call_next(request)

    @staticmethod
    def _extract_api_key(request: Request) -> Optional[str]:
        """Extract the presented API key from a request.

        The header is authoritative. A browser ``EventSource`` (the SSE
        transport) cannot attach request headers, so a **GET** request may also
        present the key as an ``api_key`` query parameter — mirroring the
        WebSocket handshake helper. The query fallback is restricted to GET so
        a credential is never accepted in the URL of a mutating request.
        """
        api_key = request.headers.get(API_KEY_HEADER_NAME)
        if not api_key:
            # Try Authorization: Bearer *** as fallback
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                api_key = auth_header[7:]
        if not api_key and request.method == "GET":
            api_key = request.query_params.get("api_key")
        return api_key

    def _resolve_roles(self, api_key: str) -> Set[Role]:
        """Determine roles for an API key."""
        return resolve_api_key_roles(api_key)

    def _key_to_subject(self, api_key: str) -> str:
        """Convert API key to a stable subject identifier.

        Use a hash prefix for logging/identification without exposing the key.
        """
        import hashlib

        return f"key-{hashlib.sha256(api_key.encode()).hexdigest()[:12]}"


# --- Dependency injection helpers ---


def get_auth_context(request: Request) -> AuthContext:
    """FastAPI dependency to access the resolved auth context."""
    if not hasattr(request.state, "auth"):
        # Should not happen if middleware is installed, but guard anyway
        if AUTH_ENABLED:
            raise HTTPException(status_code=500, detail="Auth context not initialized")
        return AuthContext(
            api_key="dev",
            roles={Role.ADMIN, Role.WRITE, Role.READ},
            subject="development",
        )
    return request.state.auth


def require_role(*required: Role) -> Callable[[AuthContext], AuthContext]:
    """Dependency factory that enforces minimum required role(s)."""

    def checker(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not any(r in auth.roles for r in required):
            raise HTTPException(
                status_code=403,
                detail={
                    "type": "urn:auth:error:forbidden",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": f"Requires one of: {[r.value for r in required]}",
                },
            )
        return auth

    return checker


# Convenience dependencies
require_admin = require_role(Role.ADMIN)
require_write = require_role(Role.ADMIN, Role.WRITE)
require_read = require_role(Role.ADMIN, Role.WRITE, Role.READ)


# Optional: APIKeyHeader for OpenAPI documentation
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


async def get_api_key(
    request: Request,
    api_key_header: Optional[str] = Security(api_key_header),
    auth_header: Optional[HTTPAuthorizationCredentials] = Security(http_bearer),
) -> str:
    """Extract API key from header or Authorization: Bearer *** OpenAPI docs)."""
    if api_key_header:
        return api_key_header
    if auth_header and auth_header.scheme.lower() == "bearer":
        return auth_header.credentials
    raise HTTPException(
        status_code=401,
        detail=f"Missing API key in '{API_KEY_HEADER_NAME}' header or Authorization: ***",
    )
