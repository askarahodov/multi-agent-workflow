"""Shared security middleware for FastAPI applications.

Provides:
- HSTS (HTTP Strict Transport Security) header middleware
- TLS redirect middleware (optional, for production HTTPS enforcement)
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse


class HSTSMiddleware(BaseHTTPMiddleware):
    """Add HSTS header to all responses when TLS is enabled.

    The HSTS header tells browsers to only use HTTPS for this domain.
    Only added when running with TLS (cert+key configured).
    """

    def __init__(
        self,
        app: FastAPI,
        *,
        tls_enabled: bool,
        max_age: int = 31536000,  # 1 year
        include_subdomains: bool = True,
        preload: bool = False,
    ):
        super().__init__(app)
        self.tls_enabled = tls_enabled
        self.max_age = max_age
        self.include_subdomains = include_subdomains
        self.preload = preload

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if self.tls_enabled:
            hsts_value = f"max-age={self.max_age}"
            if self.include_subdomains:
                hsts_value += "; includeSubDomains"
            if self.preload:
                hsts_value += "; preload"
            response.headers["Strict-Transport-Security"] = hsts_value
        return response


class TLSRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect HTTP to HTTPS when TLS is enabled (production only).

    This middleware checks the X-Forwarded-Proto header (set by reverse proxy)
    or the request URL scheme and redirects HTTP to HTTPS.
    """

    def __init__(self, app: FastAPI, *, tls_enabled: bool, trust_proxy: bool = True):
        super().__init__(app)
        self.tls_enabled = tls_enabled
        self.trust_proxy = trust_proxy

    def _is_https(self, request: Request) -> bool:
        """Check if request is already HTTPS."""
        # Check X-Forwarded-Proto header (from reverse proxy)
        if self.trust_proxy:
            forwarded_proto = request.headers.get("x-forwarded-proto")
            if forwarded_proto:
                return forwarded_proto == "https"
        # Check URL scheme directly
        return request.url.scheme == "https"

    async def dispatch(self, request: Request, call_next):
        if self.tls_enabled and not self._is_https(request):
            # Redirect to HTTPS
            https_url = request.url.replace(scheme="https")
            return RedirectResponse(url=str(https_url), status_code=301)
        return await call_next(request)


def add_security_middleware(
    app: FastAPI,
    *,
    tls_enabled: bool,
    hsts_max_age: int = 31536000,
    hsts_include_subdomains: bool = True,
    hsts_preload: bool = False,
    tls_redirect: bool = True,
    trust_proxy: bool = True,
) -> None:
    """Add security middleware to a FastAPI app.

    Args:
        app: The FastAPI application
        tls_enabled: Whether TLS is configured (cert+key present)
        hsts_max_age: HSTS max-age in seconds (default 1 year)
        hsts_include_subdomains: Include subdomains in HSTS policy
        hsts_preload: Enable HSTS preload
        tls_redirect: Enable HTTP->HTTPS redirect middleware
        trust_proxy: Trust X-Forwarded-Proto header from reverse proxy
    """
    if not tls_enabled:
        return

    # Add HSTS middleware (runs first, closest to response)
    @app.middleware("http")
    async def hsts_middleware(request: Request, call_next):
        response = await call_next(request)
        hsts_value = f"max-age={hsts_max_age}"
        if hsts_include_subdomains:
            hsts_value += "; includeSubDomains"
        if hsts_preload:
            hsts_value += "; preload"
        response.headers["Strict-Transport-Security"] = hsts_value
        return response

    # Add TLS redirect middleware (runs early in request chain)
    if tls_redirect:
        @app.middleware("http")
        async def tls_redirect_middleware(request: Request, call_next):
            # Check X-Forwarded-Proto header (from reverse proxy)
            is_https = False
            if trust_proxy:
                forwarded_proto = request.headers.get("x-forwarded-proto")
                if forwarded_proto:
                    is_https = forwarded_proto == "https"
            if not is_https:
                is_https = request.url.scheme == "https"

            if not is_https:
                https_url = request.url.replace(scheme="https")
                return RedirectResponse(url=str(https_url), status_code=301)
            return await call_next(request)