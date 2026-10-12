"""SSRF-guard tests for the network tool (ADR-012 §3.4 / ADR-015 §3.7)."""

from __future__ import annotations

import pytest

from tools.registry.network import is_blocked_ip, url_is_safe

# Literal IPs that must always be blocked.
BLOCKED_HOSTS = [
    "127.0.0.1",
    "10.0.0.5",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata endpoint
    "0.0.0.0",
    "::1",
    "fe80::1",
    "fc00::1",
]

SAFE_HOSTS = ["8.8.8.8", "1.1.1.1", "172.217.0.0"]


@pytest.mark.parametrize("host", BLOCKED_HOSTS)
def test_blocked_ips_are_denied(host):
    assert is_blocked_ip(host) is True


@pytest.mark.parametrize("host", SAFE_HOSTS)
def test_public_ips_allowed(host):
    assert is_blocked_ip(host) is False


def test_scheme_restriction():
    safe, reason = url_is_safe("ftp://example.com/x")
    assert safe is False
    safe, reason = url_is_safe("file:///etc/passwd")
    assert safe is False


def test_ip_literal_looks_ip():
    assert url_is_safe("http://127.0.0.1/")[0] is False
    assert url_is_safe("http://192.168.1.1/admin")[0] is False
    assert url_is_safe("http://8.8.8.8/")[0] is True


def test_hostname_resolving_to_private_is_blocked(monkeypatch):
    import socket

    def fake_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.9", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    safe, reason = url_is_safe("http://evil.example.com/path")
    assert safe is False
    assert "192.168" in (reason or "")


def test_malformed_url_rejected():
    assert url_is_safe("::not-a-url[]")[0] is False


def test_http_request_to_private_ip_denied(ctx):
    import asyncio

    from tools.registry import build_default_registry

    registry = build_default_registry()
    result = asyncio.run(
        registry.execute(
            "http_request",
            {"url": "http://127.0.0.1:9999/", "method": "GET"},
            ctx,
            policy_permissions={"network": ["*"]},
        )
    )
    assert result.status.value == "denied"
    assert "SSRF" in (result.error or "")


def test_http_request_allowed_domain_enforced(ctx):
    import asyncio

    from tools.registry import build_default_registry

    registry = build_default_registry()
    # allowed_domains on ctx = example.com / api.example.com; other domains blocked.
    result = asyncio.run(
        registry.execute(
            "http_request",
            {"url": "http://not-allowed.example.org/x", "method": "GET"},
            ctx,
            policy_permissions={"network": ["https://example.com/**"]},
        )
    )
    # Either the SSRF guard (DNS resolves public) proceeds then the egress
    # allow-list denies, or resolution blocks it. Either way we must not get a
    # successful data transfer against a disallowed domain.
    assert result.status.value in ("denied", "error")