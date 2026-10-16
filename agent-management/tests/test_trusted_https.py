"""Exact URL/IP allowlist and DNS rebinding denial, without real network."""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.trusted_https import HTTPOutcome, TrustedHTTPSExecutor

URL = "https://public.example/status"
PUBLIC = "8.8.8.8"


@pytest.fixture
def executor():
    return TrustedHTTPSExecutor(
        {"network": [URL]}, allowed_targets={URL: (PUBLIC,)},
        max_response_bytes=16,
    )


@pytest.mark.parametrize("url", [
    "http://public.example/status",
    "https://public.example/private",
    "https://public.example/status?next=1",
    "https://127.0.0.1/status",
    "https://169.254.169.254/latest/meta-data/",
    "https://public.example.evil/status",
    "file:///etc/passwd",
    "https://public.example:8443/status",
])
def test_unapproved_request_does_not_touch_dns(executor, url):
    with patch.object(socket, "getaddrinfo") as dns:
        with pytest.raises(ToolPolicyDenied):
            executor.get(url)
        dns.assert_not_called()


@pytest.mark.parametrize("answers", [
    ["127.0.0.1"], ["169.254.169.254"],
    ["10.0.0.1"], ["192.168.0.1"],
    ["::1"], ["8.8.8.8", "127.0.0.1"],
    ["9.9.9.9"], [],
])
def test_dns_rebinding_and_unapproved_addresses_cannot_connect(executor, answers):
    def dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in answers]
    with patch.object(socket, "getaddrinfo", side_effect=dns), patch(
        "agent_management.trusted_https._PinnedHTTPSConnection",
    ) as connect:
        with pytest.raises(ToolPolicyDenied, match="DNS address mismatch"):
            executor.get(URL)
        connect.assert_not_called()


def test_policy_denial_precedes_dns(executor):
    executor.permissions["network"] = []
    with patch.object(socket, "getaddrinfo") as dns:
        with pytest.raises(ToolPolicyDenied):
            executor.get(URL)
        dns.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 500])
def test_non_success_status_does_not_follow_redirect(executor, status):
    with patch.object(socket, "getaddrinfo", return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 443)),
    ]), patch("agent_management.trusted_https._PinnedHTTPSConnection") as cls:
        connection = cls.return_value
        connection.getresponse.return_value.status = status
        with pytest.raises(ToolPolicyDenied, match="upstream status"):
            executor.get(URL)
        connection.request.assert_called_once()
        connection.close.assert_called_once()


def test_bound_response_read_and_pinned_ip(executor):
    with patch.object(socket, "getaddrinfo", return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 443)),
    ]), patch("agent_management.trusted_https._PinnedHTTPSConnection") as cls:
        connection = cls.return_value
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b"ok"
        outcome = executor.get(URL)
        assert outcome == HTTPOutcome(200, b"ok")
        cls.assert_called_once_with("public.example", PUBLIC, timeout=5.0)
        connection.getresponse.return_value.read.assert_called_once_with(17)


def test_oversized_response_fails_closed(executor):
    with patch.object(socket, "getaddrinfo", return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 443)),
    ]), patch("agent_management.trusted_https._PinnedHTTPSConnection") as cls:
        cls.return_value.getresponse.return_value.status = 200
        cls.return_value.getresponse.return_value.read.return_value = b"x" * 17
        with pytest.raises(ToolPolicyDenied, match="size exceeded"):
            executor.get(URL)


@pytest.mark.parametrize("invalid", [
    "http://example.org/a", "https://127.0.0.1/a",
    "https://example.org/a?secret=1", "https://example.org:8080/a",
    "https://user:pass@example.org/a",
])
def test_reject_malformed_trusted_target_config(invalid):
    with pytest.raises(ValueError):
        TrustedHTTPSExecutor({"network": ["*"]}, allowed_targets={invalid: (PUBLIC,)})


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"])
def test_disallow_private_target_ip_even_from_trusted_config(address):
    with pytest.raises(ValueError):
        TrustedHTTPSExecutor({"network": ["*"]}, allowed_targets={URL: (address,)})


def test_bounded_worker_is_killed_on_total_deadline(executor):
    import signal
    import subprocess
    with patch("agent_management.trusted_https.subprocess.Popen") as popen, patch(
        "agent_management.trusted_https.os.killpg"
    ) as terminate:
        child = popen.return_value
        child.pid = 24680
        child.poll.return_value = None
        child.communicate.side_effect = subprocess.TimeoutExpired("worker", 1)
        with pytest.raises(ToolPolicyDenied, match="total deadline"):
            executor.get_bounded(URL)
        terminate.assert_called_once_with(24680, signal.SIGKILL)
        child.wait.assert_called_once()


def test_bounded_worker_denies_unknown_url_before_spawning(executor):
    with patch("agent_management.trusted_https.subprocess.Popen") as popen:
        with pytest.raises(ToolPolicyDenied):
            executor.get_bounded("https://public.example/other")
        popen.assert_not_called()
