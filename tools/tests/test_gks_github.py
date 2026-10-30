"""Tests for the GitHub client: ETag, rate limiting, backoff, redaction."""

from __future__ import annotations

import httpx
import pytest

from tools.github_kanban_sync.github import (
    AuthError,
    GitHubClient,
    RateLimited,
    TransientError,
    redact,
)
from tools.tests._gks_helpers import client_with


def test_etag_short_circuit_returns_304():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["if_none_match"] = request.headers.get("if-none-match")
        return httpx.Response(304, headers={"etag": "W/abc"})

    client = client_with(handler)
    resp = client.request("GET", "/repos/x/y/issues/192", etag="W/abc")
    assert resp.not_modified is True
    assert seen["if_none_match"] == "W/abc"


def test_rate_limited_when_remaining_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0",
                                            "x-ratelimit-reset": "1793351765"})

    client = client_with(handler)
    with pytest.raises(RateLimited) as exc:
        client.get_issue(1)
    assert exc.value.reset == 1793351765


def test_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json={"number": 192})

    client = client_with(handler)
    assert client.get_issue(192).data["number"] == 192
    assert calls["n"] == 3


def test_transient_error_after_retry_budget():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = client_with(handler)
    with pytest.raises(TransientError):
        client.get_issue(1)


def test_auth_error_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad credentials"})

    client = client_with(handler)
    with pytest.raises(AuthError):
        client.get_issue(1)


def test_retry_after_header_is_honoured():
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "7",
                                                "x-ratelimit-remaining": "10"})
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://api.github.com", transport=transport)
    client = GitHubClient("t", repo="r/x", http_client=http, sleep=slept.append,
                          backoff_cap=30)
    client.get_issue(1)
    assert slept == [7.0]


def test_redact_removes_token_and_authorization():
    assert redact("token=supersecret value", "supersecret") == "token=*** value"
    assert "supersecret" not in redact('{"Authorization": "Bearer supersecret"}', "supersecret")


def test_error_messages_never_leak_token():
    secret = "ghp_totally_secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = client_with(handler, token=secret)
    with pytest.raises(AuthError) as exc:
        client.get_issue(1)
    assert secret not in str(exc.value)
