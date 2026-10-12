"""Network tool (PRD §13 / ADR-012 §3.4 / ADR-015 §3.7).

``http_request`` performs limited outbound HTTP. The SSRF guard is the heart of
this module: private / link-local / loopback / metadata IPs are blocked, only a
narrow set of HTTP methods is allowed, redirects are followed only when the
target re-passes the guard, and responses are capped.

Defence notes:
* We resolve the hostname and validate **every** resolved IP (a `--  AAAA`
  record pointing at `127.0.0.1` must be rejected too).
* We re-check the target on every redirect hop.
* Redirects to a different scheme are refused.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolExecutionError,
    ToolPolicyDeniedError,
    ToolSpec,
)

ALLOWED_METHODS = ("GET", "POST", "HEAD")
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_S = 20.0

#: IP ranges that must never be contacted from the agent runtime.
_BLOCKED_NETWORKS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",  # link-local (incl. cloud metadata 169.254.169.254)
    "0.0.0.0/8",
    "100.64.0.0/10",
    "fc00::/7",  # unique-local IPv6
    "fe80::/10",  # link-local IPv6
    "::1/128",  # IPv6 loopback
]

_BLOCKED_PREFIXES = ("192.0.0.0/24", "198.18.0.0/15", "240.0.0.0/4")


def _build_blocked() -> list:
    nets = [_network(x) for x in _BLOCKED_NETWORKS]
    for p in _BLOCKED_PREFIXES:
        nets.append(_network(p))
    return nets


def _network(spec: str):
    try:
        return ipaddress.ip_network(spec, strict=False)
    except ValueError:
        return None


def is_blocked_ip(ip: str) -> bool:
    """True when an IP literal is in a blocked (private/link-local) range."""
    addr = ipaddress.ip_address(ip)
    for net in _blocked_networks():
        if net is not None and addr in net:
            return True
    return addr.is_global is False


_blocked_networks_cache: list | None = None


def _blocked_networks() -> list:
    global _blocked_networks_cache
    if _blocked_networks_cache is None:
        _blocked_networks_cache = [n for n in _build_blocked() if n is not None]
    return _blocked_networks_cache


def url_is_safe(url: str) -> tuple[bool, str | None]:
    """Return ``(safe, reason)``. ``safe`` is False when the URL should be blocked."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "malformed URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme {parsed.scheme!r} not allowed"
    host = parsed.hostname
    if not host:
        return False, "URL has no host"
    try:
        port = parsed.port
    except ValueError:
        return False, "malformed port"

    # Host is already an IP literal?
    if _looks_like_ip(host):
        return _check_ip(host, port)

    # Resolve (all addresses) and reject if any is blocked.
    try:
        infos = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return True, None  # unresolvable host → let the HTTP layer produce a clean error

    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        return True, None
    blocked = [ip for ip in addresses if is_blocked_ip(ip)]
    if blocked:
        return False, f"resolved to blocked address(es): {blocked[:3]}"
    return True, None


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _check_ip(ip: str, port: int | None) -> tuple[bool, str | None]:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False, f"invalid IP literal {ip!r}"
    if addr.is_global is False:
        return False, f"{ip} is not a public address"
    for net in _blocked_networks():
        if addr in net:
            return False, f"{ip} is in blocked network {net}"
    return True, None


async def _http_request(params: dict, context: ExecutionContext) -> dict:
    url = params.get("url", "")
    method = (params.get("method") or "GET").upper()
    if method not in ALLOWED_METHODS:
        raise ToolExecutionError(f"method {method!r} not allowed (allowed: {sorted(ALLOWED_METHODS)})")

    safe, reason = url_is_safe(url)
    if not safe:
        raise ToolPolicyDeniedError(f"SSRF guard: {reason}")

    allowed_domains = context.allowed_domains
    if allowed_domains:
        from .policies import _any_domain_matches

        if not _any_domain_matches(list(allowed_domains), url):
            raise ToolPolicyDeniedError(f"egress allow-list: {url!r} not permitted")

    body = params.get("body")
    headers = {"User-Agent": "multi-agent-workflow/0.1", "Accept": "*/*"}
    timeout = params.get("timeout_s") or DEFAULT_TIMEOUT_S

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            headers=headers,
        ) as client:
            redirects = 0
            target = url
            while True:
                safe, reason = url_is_safe(target)
                if not safe:
                    raise ToolPolicyDeniedError(f"SSRF guard on redirect: {reason}")
                try:
                    resp = await client.request(method, target, json=body if method in ("POST",) and isinstance(body, dict) else None, content=body if isinstance(body, str) else None)
                except httpx.HTTPError as exc:
                    raise ToolExecutionError(f"request failed: {exc}") from exc
                if resp.is_redirect and resp.headers.get("location"):
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        raise ToolExecutionError("too many redirects")
                    target = resp.headers["location"]
                    continue
                content = resp.content[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
                return {
                    "url": target,
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": content,
                }
    except (httpx.HTTPError, OSError) as exc:
        raise ToolExecutionError(f"request failed: {exc}") from exc


def register_network(registry) -> None:
    registry.register(
        ToolSpec(
            name="http_request",
            category=ToolCategory.NETWORK,
            description="Limited outbound HTTP/HTTPS (GET/POST/HEAD) with SSRF and egress allow-list guards.",
            params_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"enum": ["GET", "POST", "HEAD"]},
                    "body": {},
                    "timeout_s": {"type": "number", "minimum": 1, "maximum": 60},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "status_code": {"type": "integer"},
                    "headers": {"type": "object"},
                    "body": {"type": "string"},
                },
                "required": ["url", "status_code", "body"],
            },
            required_policy=["network"],
            default_timeout_ms=30000,
        ),
        handler=_http_request,
    )