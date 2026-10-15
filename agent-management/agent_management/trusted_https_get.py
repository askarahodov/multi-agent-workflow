"""Trusted HTTPS GET boundary: explicit hosts, pinned DNS IP and TLS hostname.

Not registered as an LLM tool until #20 policy/journal integration is complete.
Only trusted callers supply host allowlist and network policy.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from .errors import ToolPolicyDenied
from .tool_policy import ToolPolicyEngine

_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")
_PATH = re.compile(r"/[A-Za-z0-9._~/-]*\\Z")


@dataclass(frozen=True)
class HttpsResult:
    ok: bool
    content: str
    error_code: str | None = None


class TrustedHttpsGet:
    """No ambient proxy, redirect, unsafe address or model-controlled header."""

    def __init__(
        self, permissions: Mapping, *, allowed_hosts: frozenset[str],
        max_response_bytes: int = 65536, timeout_seconds: float = 5.0,
    ) -> None:
        if (
            not isinstance(allowed_hosts, frozenset) or not allowed_hosts
            or any(not isinstance(host, str) or not _HOST.fullmatch(host)
                   or host.lower() != host or ".." in host
                   for host in allowed_hosts)
        ):
            raise ValueError("Trusted HTTPS host allowlist invalid")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 65536:
            raise ValueError("Invalid HTTPS response bound")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 15:
            raise ValueError("Invalid HTTPS timeout")
        if isinstance(timeout_seconds, float):
            import math
            if not math.isfinite(timeout_seconds):
                raise ValueError("Invalid HTTPS timeout")
        self.permissions = dict(permissions)
        self.allowed_hosts = allowed_hosts
        self.max_response_bytes = max_response_bytes
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _global_ip(host: str) -> str:
        try:
            answers = socket.getaddrinfo(
                host, 443, family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP,
            )
            if not answers:
                raise ToolPolicyDenied("HTTPS DNS resolution unavailable")
            candidates: list[str] = []
            for family, kind, proto, _canonical, sockaddr in answers:
                if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
                    raise ToolPolicyDenied("Unsupported HTTPS DNS address")
                address = ipaddress.ip_address(sockaddr[0])
                if not address.is_global or getattr(address, "ipv4_mapped", None) is not None:
                    raise ToolPolicyDenied("Private or reserved HTTPS destination denied")
                candidates.append(str(address))
            return candidates[0]
        except (socket.gaierror, ValueError, IndexError, TypeError) as exc:
            raise ToolPolicyDenied("Invalid HTTPS DNS response") from exc

    def get(self, url: str) -> HttpsResult:
        if not isinstance(url, str) or len(url) > 2048:
            raise ToolPolicyDenied("Invalid HTTPS URL")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ToolPolicyDenied("Invalid HTTPS URL") from exc
        target = parsed.path or "/"
        if (
            not _PATH.fullmatch(target)
            or "//" in target
            or any(segment in (".", "..") for segment in target.split("/"))
        ):
            raise ToolPolicyDenied("Ambiguous HTTPS request path denied")
        if (
            parsed.scheme != "https" or host not in self.allowed_hosts
            or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or parsed.query
            or any(ord(char) < 33 or ord(char) == 127 for char in url)
                    ):
            raise ToolPolicyDenied("HTTPS destination not allowlisted")
        assert host is not None
        # Policy decision precedes DNS and all external I/O.
        ToolPolicyEngine.enforce(self.permissions, "network", url)
        pinned_ip = self._global_ip(host)
        connection = http.client.HTTPSConnection(
            host, 443, timeout=self.timeout_seconds,
            context=ssl.create_default_context(),
        )
        # HTTPSConnection still uses the original HOST for SNI and certificate
        # validation, but TCP connects ONLY to the validated numeric IP.
        connection._create_connection = (
            lambda _addr, timeout=self.timeout_seconds, source_address=None:
            socket.create_connection((pinned_ip, 443), timeout, source_address)
        )
        try:
            connection.request("GET", target, headers={
                "Accept": "text/plain, application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
                "User-Agent": "MAW-Trusted-HTTPS/1",
            })
            response = connection.getresponse()
            if response.status != 200:
                return HttpsResult(False, "", "HTTP_REJECTED")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                return HttpsResult(False, "", "HTTP_ENCODING_DENIED")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
            if content_type not in ("text/plain", "application/json"):
                return HttpsResult(False, "", "HTTP_TYPE_DENIED")
            length = response.getheader("Content-Length")
            if length is not None:
                if not length.isdecimal() or len(length) > 10 or int(length) > self.max_response_bytes:
                    return HttpsResult(False, "", "HTTP_SIZE_DENIED")
            data = response.read(self.max_response_bytes + 1)
            if len(data) > self.max_response_bytes:
                return HttpsResult(False, "", "HTTP_SIZE_DENIED")
            try:
                return HttpsResult(True, data.decode("utf-8", errors="strict"))
            except UnicodeError:
                return HttpsResult(False, "", "HTTP_ENCODING_DENIED")
        except (OSError, http.client.HTTPException, ssl.SSLError):
            return HttpsResult(False, "", "HTTP_FAILED")
        finally:
            connection.close()
