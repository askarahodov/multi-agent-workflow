"""Offline SSRF/DNS/TLS policy tests for staged trusted HTTPS GET."""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.trusted_https_get import TrustedHttpsGet


HOST = "api.example.com"
URL = "https://api.example.com/docs"


@pytest.fixture
def getter():
    return TrustedHttpsGet(
        {"network": ["https://api.example.com/**"]},
        allowed_hosts=frozenset({HOST}),
        max_response_bytes=32,
    )


def answer(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]


@pytest.mark.parametrize("url", [
    "http://api.example.com/docs",
    "https://api.example.com:444/docs",
    "https://api.example.com.evil.test/docs",
    "https://127.0.0.1/docs",
    "https://user:password@api.example.com/docs",
    "https://api.example.com/docs?payload=secret",
    "https://api.example.com/docs#fragment",
    "https://api.example.com/hello\r\nInjected:1",
    "https://api.example.com:abc/docs",
])
def test_bad_destinations_rejected_before_dns(getter, url):
    with patch("socket.getaddrinfo") as resolve:
        with pytest.raises(ToolPolicyDenied):
            getter.get(url)
        resolve.assert_not_called()


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.3", "192.168.1.20", "169.254.169.254",
    "172.16.0.1", "0.0.0.0", "8.8.8.8",
])
def test_private_metadata_or_untrusted_dns(getter, ip):
    # 8.8.8.8 is public and therefore expected to be allowed by the IP
    # classification layer; no actual connection is performed.
    with patch("socket.getaddrinfo", return_value=answer(ip)):
        if ip == "8.8.8.8":
            assert getter._global_ip(HOST) == ip
        else:
            with pytest.raises(ToolPolicyDenied):
                getter._global_ip(HOST)


def test_mixed_public_private_dns_fails_closed(getter):
    with patch("socket.getaddrinfo", return_value=answer("8.8.8.8") + answer("127.0.0.1")):
        with pytest.raises(ToolPolicyDenied):
            getter._global_ip(HOST)


def test_policy_denies_before_resolver():
    getter = TrustedHttpsGet(
        {"network": []}, allowed_hosts=frozenset({HOST}),
    )
    with patch("socket.getaddrinfo") as resolve:
        with pytest.raises(ToolPolicyDenied):
            getter.get(URL)
        resolve.assert_not_called()


class Response:
    def __init__(self, status=200, body=b"ok", content_type="text/plain"):
        self.status = status
        self.body = body
        self.content_type = content_type

    def getheader(self, name, default=None):
        return {"Content-Type": self.content_type}.get(name, default)

    def read(self, amount):
        return self.body[:amount]


class Connection:
    def __init__(self, *args, **kwargs):
        self.host, self.port = args[:2]
        self.requested = None
        self.closed = False
        self.response = Response()

    def request(self, method, target, headers):
        self.requested = (method, target, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def test_https_pins_tcp_address_but_preserves_tls_hostname(getter):
    fake = Connection(HOST, 443)
    with patch("socket.getaddrinfo", return_value=answer("8.8.8.8")), patch(
        "http.client.HTTPSConnection", return_value=fake,
    ):
        result = getter.get(URL)
    assert result.ok and result.content == "ok"
    assert fake.host == HOST and fake.port == 443
    assert fake.requested[0:2] == ("GET", "/docs")
    assert fake.requested[2]["Accept-Encoding"] == "identity"
    assert callable(fake._create_connection)
    assert fake.closed


@pytest.mark.parametrize("status,body,content_type,error", [
    (302, b"", "text/plain", "HTTP_REJECTED"),
    (500, b"", "text/plain", "HTTP_REJECTED"),
    (200, b"content", "text/html", "HTTP_TYPE_DENIED"),
    (200, b"0123456789" * 10, "text/plain", "HTTP_SIZE_DENIED"),
    (200, bytes([255]), "text/plain", "HTTP_ENCODING_DENIED"),
])
def test_http_bad_responses_fail_closed(getter, status, body, content_type, error):
    fake = Connection(HOST, 443)
    fake.response = Response(status=status, body=body, content_type=content_type)
    with patch("socket.getaddrinfo", return_value=answer("8.8.8.8")), patch(
        "http.client.HTTPSConnection", return_value=fake,
    ):
        result = getter.get(URL)
    assert not result.ok and result.error_code == error
    assert not result.content and fake.closed


@pytest.mark.parametrize("hosts,limit,timeout", [
    (frozenset(), 8, 5),
    (frozenset({"api.example.com"}), 0, 5),
    (frozenset({"api.example.com"}), True, 5),
    (frozenset({"api.example.com"}), 8, float("nan")),
    (frozenset({"api.example.com"}), 8, 10**400),
])
def test_invalid_trusted_settings_rejected(hosts, limit, timeout):
    with pytest.raises(ValueError):
        TrustedHttpsGet(
            {"network": [URL]}, allowed_hosts=hosts,
            max_response_bytes=limit, timeout_seconds=timeout,
        )
