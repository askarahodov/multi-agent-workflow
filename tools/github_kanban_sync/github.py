"""Minimal GitHub REST client with the durability the sync needs.

Built directly on ``httpx`` (already a repo dependency) so the sync can use
conditional GETs, read rate-limit headers, and honour ``Retry-After`` — none of
which ``gh api`` exposes conveniently.

Guarantees
----------
* **ETag / 304** — a conditional GET that returns 304 short-circuits before any
  event is produced (SPEC §5.3 cost control).
* **Rate limiting** — the client reads ``x-ratelimit-remaining`` / ``-reset``;
  when the budget is exhausted it raises :class:`RateLimited` instead of spinning.
* **Backoff** — 5xx and ``429`` are retried with exponential backoff (capped); a
  ``Retry-After`` header, when present, wins.
* **No secret leakage** — the token is only ever placed in the request header and
  is scrubbed from every exception message.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from .config import DEFAULT_REPO


class GitHubError(RuntimeError):
    """Base class for sync GitHub errors (message is always token-free)."""


class AuthError(GitHubError):
    """401/403 without a rate-limit cause — the token lacks permission."""


class RateLimited(GitHubError):
    """The API budget is exhausted; ``reset`` is the epoch when it refills."""

    def __init__(self, message: str, reset: Optional[int] = None):
        super().__init__(message)
        self.reset = reset


class TransientError(GitHubError):
    """A retryable server-side failure after the retry budget was spent."""


def redact(text: str, token: Optional[str]) -> str:
    """Remove a token (and any ``Authorization:`` value) from ``text``."""
    import re

    if token:
        text = text.replace(token, "***")
    return re.sub(r"(?i)(authorization|token)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]+",
                  r"\1=***", text)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    data: Any
    not_modified: bool = False


class GitHubClient:
    def __init__(
        self,
        token: Optional[str] = None,
        *,
        repo: str = DEFAULT_REPO,
        api_base: str = "https://api.github.com",
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        http_client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.token = token
        self.repo = repo
        self.api_base = api_base.rstrip("/")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._sleep = sleep
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-kanban-sync",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = http_client or httpx.Client(
            base_url=self.api_base, timeout=timeout, headers=headers
        )

    def close(self) -> None:
        self._client.close()

    # -- core request ------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        etag: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Response:
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        attempt = 0
        while True:
            try:
                resp = self._client.request(
                    method, path, params=params, json=json_body, headers=headers
                )
            except httpx.HTTPError as exc:  # network/offline — retryable
                if attempt >= self.max_retries:
                    raise TransientError(redact(f"transport error: {exc}", self.token)) from exc
                self._sleep(min(self.backoff_base * (2 ** attempt), self.backoff_cap))
                attempt += 1
                continue

            status = resp.status_code
            if status == 304:
                return Response(304, dict(resp.headers), None, not_modified=True)
            if status in (200, 201, 204):
                data: Any = None
                if resp.content:
                    try:
                        data = resp.json()
                    except ValueError:
                        data = resp.text
                return Response(status, dict(resp.headers), data)
            if status in (401,):
                raise AuthError(redact(f"401 unauthorized for {path}", self.token))
            if status in (403, 429):
                remaining = resp.headers.get("x-ratelimit-remaining")
                reset = resp.headers.get("x-ratelimit-reset")
                if remaining == "0":
                    raise RateLimited(
                        redact(f"rate limited on {path}", self.token),
                        reset=int(reset) if reset and reset.isdigit() else None,
                    )
                # Secondary rate limit / abuse detection: back off and retry.
                if attempt >= self.max_retries:
                    raise GitHubError(redact(f"{status} on {path}", self.token))
                retry_after = _retry_after(dict(resp.headers), self.backoff_base, attempt, self.backoff_cap)
                self._sleep(retry_after)
                attempt += 1
                continue
            if status >= 500:
                if attempt >= self.max_retries:
                    raise TransientError(redact(f"{status} on {path}", self.token))
                retry_after = _retry_after(dict(resp.headers), self.backoff_base, attempt, self.backoff_cap)
                self._sleep(retry_after)
                attempt += 1
                continue
            raise GitHubError(redact(f"HTTP {status} on {path}", self.token))

    # -- reads -------------------------------------------------------------
    def get_issue(self, number: int) -> Response:
        return self.request("GET", f"/repos/{self.repo}/issues/{number}")

    def list_issue_comments(self, number: int, *, since: Optional[str] = None,
                            etag: Optional[str] = None) -> Response:
        params: dict[str, Any] = {"per_page": 100}
        if since:
            params["since"] = since
        return self.request(
            "GET", f"/repos/{self.repo}/issues/{number}/comments", params=params, etag=etag
        )

    def list_issues(self, *, since: Optional[str] = None, state: str = "all",
                    etag: Optional[str] = None) -> Response:
        params: dict[str, Any] = {"state": state, "per_page": 100, "sort": "updated",
                                  "direction": "asc"}
        if since:
            params["since"] = since
        return self.request("GET", f"/repos/{self.repo}/issues", params=params, etag=etag)

    def get_pull(self, number: int) -> Response:
        return self.request("GET", f"/repos/{self.repo}/pulls/{number}")

    def list_pulls(self, *, state: str = "all", etag: Optional[str] = None) -> Response:
        return self.request(
            "GET", f"/repos/{self.repo}/pulls",
            params={"state": state, "per_page": 100}, etag=etag,
        )

    def combined_status(self, sha: str) -> Response:
        return self.request("GET", f"/repos/{self.repo}/commits/{sha}/status")

    def check_runs(self, sha: str) -> Response:
        return self.request("GET", f"/repos/{self.repo}/commits/{sha}/check-runs",
                            params={"per_page": 100})

    def rate_limit(self) -> Response:
        return self.request("GET", "/rate_limit")

    # -- writes (publish path) --------------------------------------------
    def list_all_issue_comments(self, number: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            resp = self.request(
                "GET", f"/repos/{self.repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
            )
            batch = resp.data or []
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out

    def post_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        return self.request("POST", f"/repos/{self.repo}/issues/{number}/comments",
                            json_body={"body": body}).data

    def update_issue_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        return self.request("PATCH", f"/repos/{self.repo}/issues/comments/{comment_id}",
                            json_body={"body": body}).data

    def patch_issue(self, number: int, **fields: Any) -> dict[str, Any]:
        return self.request("PATCH", f"/repos/{self.repo}/issues/{number}",
                            json_body=fields).data


def _retry_after(headers: dict[str, str], base: float, attempt: int, cap: float) -> float:
    raw = headers.get("retry-after")
    if raw and raw.isdigit():
        return min(float(raw), cap)
    return min(base * (2 ** attempt), cap)
