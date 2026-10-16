"""Pin allowed HTTPS targets to verified IPs; do not follow redirects."""
from __future__ import annotations

import http.client
import base64
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
import ipaddress
import math
import socket
import ssl
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from .errors import ToolPolicyDenied
from .tool_policy import ToolPolicyEngine


@dataclass(frozen=True)
class HTTPOutcome:
    status: int
    content: bytes


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, *, timeout: float):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._approved_ip = ip

    def connect(self) -> None:
        # No second DNS lookup: TLS verifies the original host via SNI.
        raw = socket.create_connection((self._approved_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class TrustedHTTPSExecutor:
    """Exact URL+IP allowlist. Non-global DNS answers always fail closed.

    This synchronous, GET-only library is not yet a model-facing HTTP tool.
    It must run outside the async event loop in an isolated worker process.
    """

    def __init__(
        self, permissions: Mapping[str, list[str]], *,
        allowed_targets: Mapping[str, tuple[str, ...]],
        timeout_seconds: float = 5.0, max_response_bytes: int = 65_536,
    ) -> None:
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 1_048_576:
            raise ValueError("Invalid response size bound")
        if (type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 30
                or (type(timeout_seconds) is float and not math.isfinite(timeout_seconds))):
            raise ValueError("Invalid HTTPS timeout")
        allowed: dict[str, frozenset[str]] = {}
        for url, addresses in allowed_targets.items():
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443)
                    or parsed.username or parsed.password or parsed.fragment
                    or parsed.query or not parsed.path.startswith("/")
                    or not addresses):
                raise ValueError("Trusted HTTPS target must be exact HTTPS origin and path")
            try:
                literal_host = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                literal_host = None
            if literal_host is not None and not literal_host.is_global:
                raise ValueError("Private literal HTTPS hosts are forbidden")
            ips = frozenset(str(ipaddress.ip_address(value)) for value in addresses)
            if not all(ipaddress.ip_address(ip).is_global for ip in ips):
                raise ValueError("HTTPS allowlist may only contain global IPs")
            allowed[url] = ips
        self.permissions = dict(permissions)
        self.allowed = allowed
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def get_bounded(self, url: str) -> HTTPOutcome:
        """Run the pinned request in a killable isolated Python child.

        Process boundary gives a hard total deadline across DNS resolution,
        TLS handshake, HTTP headers and slow response reads. The child has no
        ambient provider credentials or model-controlled command arguments.
        """
        if os.name != "posix":
            raise ToolPolicyDenied("POSIX HTTPS worker required")
        if type(url) is not str or url not in self.allowed:
            raise ToolPolicyDenied("HTTPS target not allowlisted")
        ToolPolicyEngine.enforce(self.permissions, "network", url)
        request = json.dumps({
            "url": url, "permissions": self.permissions,
            "allowed_targets": {k: sorted(v) for k, v in self.allowed.items()},
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
        }, separators=(",", ":")).encode()
        child = None
        try:
            child = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve().with_name("trusted_https_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd="/", shell=False,
                start_new_session=True,
                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                     "LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1"},
            )
            try:
                output, _ = child.communicate(request, timeout=self.timeout_seconds + 2.0)
            except subprocess.TimeoutExpired:
                raise ToolPolicyDenied("HTTPS total deadline exceeded") from None
            if child.returncode != 0 or len(output) > 2 * self.max_response_bytes + 4096:
                raise ToolPolicyDenied("HTTPS worker rejected request")
            try:
                result = json.loads(output)
                if result.get("ok") is not True or type(result.get("status")) is not int:
                    raise ValueError("HTTP denied")
                payload = base64.b64decode(result["body"], validate=True)
                if len(payload) > self.max_response_bytes:
                    raise ValueError("Oversized")
                return HTTPOutcome(result["status"], payload)
            except (ValueError, KeyError, TypeError):
                raise ToolPolicyDenied("HTTPS worker denied request") from None
        except OSError:
            raise ToolPolicyDenied("HTTPS worker unavailable") from None
        finally:
            if child is not None:
                if child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait()

    def get(self, url: str) -> HTTPOutcome:
        if type(url) is not str or url not in self.allowed:
            raise ToolPolicyDenied("HTTPS target not allowlisted")
        ToolPolicyEngine.enforce(self.permissions, "network", url)
        host = urlsplit(url).hostname
        assert host is not None
        try:
            answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            resolved = frozenset(str(ipaddress.ip_address(record[4][0])) for record in answers)
        except (OSError, ValueError) as exc:
            raise ToolPolicyDenied("HTTPS DNS validation unavailable") from None
        if not resolved or not resolved.issubset(self.allowed[url]):
            raise ToolPolicyDenied("HTTPS DNS address mismatch")
        # Use a stable sorted address only after validating ALL answers.
        selected = sorted(resolved)[0]
        connection = _PinnedHTTPSConnection(host, selected, timeout=self.timeout_seconds)
        try:
            path = urlsplit(url).path
            connection.request("GET", path, headers={"Accept": "application/octet-stream"})
            response = connection.getresponse()
            if not 200 <= response.status <= 299:
                # 3xx is intentionally not followed, even to the same host.
                raise ToolPolicyDenied("HTTPS upstream status denied")
            body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                raise ToolPolicyDenied("HTTPS response size exceeded")
            return HTTPOutcome(response.status, body)
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ToolPolicyDenied("HTTPS request unavailable") from None
        finally:
            connection.close()
