"""Tests for the GitHub client: ETag, rate limiting, backoff, redaction."""

from __future__ import annotations

import httpx
import pytest

from tools.github_kanban_sync.github import (
    AuthError,
    GitHubClient,
    GitHubError,
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


# -- Full pagination and fail-closed cursor protection (#192) ----------------

def _next_link(path: str, *, page: int = 2) -> str:
    return (
        f'<https://api.github.com{path}?per_page=100&page={page}>; rel="next", '
        f'<https://api.github.com{path}?per_page=100&page={page}>; rel="last"'
    )


def test_list_issues_fetches_all_pages_and_does_not_cache_page_one_etag():
    path = "/repos/askarahodov/multi-agent-workflow/issues"
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((
            request.url.params["page"],
            request.headers.get("if-none-match"),
        ))
        if request.url.params["page"] == "1":
            return httpx.Response(
                200, json=[{"number": 1}],
                headers={"etag": "W/page-one", "link": _next_link(path)},
            )
        return httpx.Response(200, json=[{"number": 2}])

    client = client_with(handler)
    out = client.list_issues(etag="W/old")
    assert [issue["number"] for issue in out.data] == [1, 2]
    assert seen == [("1", "W/old"), ("2", None)]
    assert "etag" not in out.headers  # first-page cache cannot cover other pages


def test_list_pulls_follows_link_even_if_page_has_fewer_than_100_items():
    path = "/repos/askarahodov/multi-agent-workflow/pulls"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(
                200, json=[{"number": 230}],
                headers={"link": _next_link(path)},
            )
        return httpx.Response(200, json=[{"number": 231}])

    client = client_with(handler)
    response = client.list_pulls()
    assert [pr["number"] for pr in response.data] == [230, 231]


def test_issue_comments_fetches_handoff_on_second_page():
    path = "/repos/askarahodov/multi-agent-workflow/issues/192/comments"

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        if page == "1":
            return httpx.Response(
                200, json=[{"id": 1}],
                headers={"link": _next_link(path)},
            )
        return httpx.Response(200, json=[{"id": 2, "body": "MIGRATION_182_HANDOFF"}])

    client = client_with(handler)
    response = client.list_issue_comments(192)
    assert [comment["id"] for comment in response.data] == [1, 2]


def test_check_runs_are_aggregated_across_pages_and_count_verified():
    path = "/repos/askarahodov/multi-agent-workflow/commits/abc/check-runs"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json={"total_count": 101, "check_runs": [
                    {"name": f"ci-{i}", "status": "completed", "conclusion": "success"}
                    for i in range(100)
                ]},
                headers={"link": _next_link(path)},
            )
        return httpx.Response(
            200, json={"total_count": 101, "check_runs": [
                {"name": "required-101", "status": "completed", "conclusion": "success"}
            ]}
        )

    client = client_with(handler)
    runs = client.check_runs("abc").data
    assert runs["total_count"] == len(runs["check_runs"]) == 101
    assert runs["check_runs"][-1]["name"] == "required-101"


def test_missing_check_run_page_fails_instead_of_reporting_partial_green():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"total_count": 101, "check_runs": [
                {"name": "unrelated", "status": "completed", "conclusion": "success"}
            ]},
        )

    with pytest.raises(GitHubError, match="incomplete"):
        client_with(handler).check_runs("abc")


def test_untrusted_external_pagination_link_is_never_followed():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200, json=[{"number": 1}],
            headers={"link": '<https://evil.example/steal?per_page=100&page=2>; rel="next"'},
        )

    with pytest.raises(GitHubError, match="destination"):
        client_with(handler).list_issues()
    assert len(seen) == 1
    assert seen[0].startswith("https://api.github.com/")


def test_malformed_or_backwards_pagination_link_fails_closed():
    path = "/repos/askarahodov/multi-agent-workflow/pulls"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[{"number": 1}],
            headers={"link": _next_link(path, page=1)},
        )

    with pytest.raises(GitHubError, match="destination"):
        client_with(handler).list_pulls()


def test_invalid_second_page_is_not_silently_accepted():
    path = "/repos/askarahodov/multi-agent-workflow/issues"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(
                200, json=[{"number": 1}],
                headers={"link": _next_link(path)},
            )
        return httpx.Response(200, json={"unexpected": "not an issue list"})

    with pytest.raises(GitHubError, match="paginated list"):
        client_with(handler).list_issues()


def test_full_single_page_must_not_keep_etag_when_page_two_appears():
    path = "/repos/askarahodov/multi-agent-workflow/issues"
    page_two_exists = False
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_two_exists
        requests.append((request.url.params["page"], request.headers.get("if-none-match")))
        if request.headers.get("if-none-match") == "W/first-page":
            return httpx.Response(304, headers={"etag": "W/first-page"})
        if request.url.params["page"] == "1":
            return httpx.Response(
                200, json=[{"number": i} for i in range(100)],
                headers={
                    "etag": "W/first-page",
                    **({"link": _next_link(path)} if page_two_exists else {}),
                },
            )
        return httpx.Response(200, json=[{"number": 100}])

    client = client_with(handler)
    initial = client.list_issues()
    assert len(initial.data) == 100
    assert "etag" not in initial.headers

    # GitHub's first 100 results remain byte-identical. A conditional GET on
    # page one would return 304 even though a new later page now exists.
    page_two_exists = True
    updated = client.list_issues(etag=initial.headers.get("etag"))
    assert len(updated.data) == 101
    assert updated.data[-1]["number"] == 100
    assert requests == [("1", None), ("1", None), ("2", None)]
