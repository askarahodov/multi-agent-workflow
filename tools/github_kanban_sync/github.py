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

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlsplit

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
    page_count: int = 1
    first_page: Optional[tuple[dict[str, Any], ...]] = None


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
        self._verified_repo_id: Optional[int] = None
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

    # -- complete paginated reads ------------------------------------------
    def _repository_id(self) -> int:
        """Resolve /repositories/{id} aliases against the configured repo.

        GitHub's official pagination examples use numeric repository-ID paths
        even when the original request used /repos/{owner}/{repo}. Never trust
        a numeric ID provided by a Link header without verifying ownership.
        """
        if self._verified_repo_id is None:
            data = self.request("GET", f"/repos/{self.repo}").data
            if not isinstance(data, dict) or type(data.get("id")) is not int:
                raise GitHubError("unable to verify GitHub pagination repository")
            full_name = data.get("full_name")
            if full_name is not None and (
                not isinstance(full_name, str)
                or full_name.lower() != self.repo.lower()
            ):
                raise GitHubError("unexpected GitHub pagination repository")
            self._verified_repo_id = data["id"]
        return self._verified_repo_id

    def _has_next_page(self, headers: dict[str, str], *, path: str, page: int) -> bool:
        """Validate the next-page Link without following its untrusted URL.

        Construct the next request from our own path and parameters, never from
        an arbitrary Link destination that could disclose Authorization.
        """
        link = headers.get("link", "")
        for part in link.split(","):
            if not re.search(r';\s*rel="?next"?(?:\s*;|\s*$)', part, re.IGNORECASE):
                continue
            match = re.fullmatch(
                r'\s*<([^>]+)>;\s*rel="?next"?\s*', part, re.IGNORECASE
            )
            if match is None:
                raise GitHubError("invalid GitHub pagination Link")
            dest = urlsplit(match.group(1))
            base = urlsplit(self.api_base)
            query = parse_qs(dest.query)
            target_ok = dest.path == path
            if not target_ok:
                # Only GitHub's documented numeric alias is eligible. Check
                # the path suffix first, then resolve the ID from our own
                # authenticated /repos/{owner}/{repo} endpoint.
                prefix = f"/repos/{self.repo}"
                suffix = path[len(prefix):] if path.startswith(prefix + "/") else None
                candidate = re.fullmatch(r"/repositories/([0-9]+)(/.*)", dest.path)
                if candidate and suffix == candidate.group(2):
                    target_ok = int(candidate.group(1)) == self._repository_id()
            if (
                dest.scheme != base.scheme
                or dest.netloc != base.netloc
                or not target_ok
                or dest.username is not None
                or dest.password is not None
                or query.get("page") != [str(page + 1)]
                or query.get("per_page") != ["100"]
            ):
                raise GitHubError("invalid GitHub pagination destination")
            return True
        return False

    def _list_pages(
        self, path: str, *, params: dict[str, Any], etag: Optional[str] = None,
    ) -> Response:
        """Fetch every page before returning data to the ingest cursor.

        Pagination over mutable sorted lists is not an atomic snapshot. Retry a
        traversal once if the same ID appears on multiple pages (page boundary
        moved during the read); fail instead of silently advancing a cursor if
        the second traversal is also unstable. Ingest retains a conservative
        high-water mark for multi-page issue feeds.
        """
        identity_field = "id" if path.endswith("/comments") else "number"
        for attempt in range(2):
            records: list[dict[str, Any]] = []
            first: Optional[Response] = None
            first_page: Optional[tuple[dict[str, Any], ...]] = None
            for page in range(1, 1001):
                resp = self.request(
                    "GET", path, params={**params, "page": page},
                    etag=etag if page == 1 and attempt == 0 else None,
                )
                if page == 1:
                    if resp.not_modified:
                        return resp
                    first = resp
                if not isinstance(resp.data, list) or not all(
                    isinstance(item, dict) for item in resp.data
                ):
                    raise GitHubError("invalid GitHub paginated list response")
                if page == 1:
                    first_page = tuple(resp.data)
                records.extend(resp.data)
                more = self._has_next_page(resp.headers, path=path, page=page)
                if not more:
                    assert first is not None
                    ids = [
                        item[identity_field] for item in records
                        if item.get(identity_field) is not None
                    ]
                    if len(ids) != len(set(ids)):
                        if attempt == 0:
                            break  # restart all pages without a conditional GET
                        raise GitHubError("unstable GitHub pagination (duplicate IDs)")
                    headers = dict(first.headers)
                    # A full single page may gain page 2 without changing
                    # its contents. A multi-page feed's first ETag is similarly
                    # not a safe proof that every later page stayed unchanged.
                    if page > 1 or len(records) >= 100:
                        headers.pop("etag", None)
                    return Response(
                        first.status, headers, records, page_count=page,
                        first_page=first_page,
                    )
            else:
                raise GitHubError("GitHub paginated list exceeds 1000 pages")
        raise GitHubError("unstable GitHub pagination")

    # -- reads -------------------------------------------------------------
    def get_issue(self, number: int) -> Response:
        return self.request("GET", f"/repos/{self.repo}/issues/{number}")

    def list_issue_comments(self, number: int, *, since: Optional[str] = None,
                            etag: Optional[str] = None) -> Response:
        params: dict[str, Any] = {"per_page": 100}
        if since:
            params["since"] = since
        return self._list_pages(
            f"/repos/{self.repo}/issues/{number}/comments", params=params, etag=etag
        )

    def list_issues(self, *, since: Optional[str] = None, state: str = "all",
                    etag: Optional[str] = None) -> Response:
        params: dict[str, Any] = {"state": state, "per_page": 100, "sort": "updated",
                                  "direction": "asc"}
        if since:
            params["since"] = since
        return self._list_pages(f"/repos/{self.repo}/issues", params=params, etag=etag)

    def get_pull(self, number: int) -> Response:
        return self.request("GET", f"/repos/{self.repo}/pulls/{number}")

    def list_pulls(self, *, state: str = "all", etag: Optional[str] = None) -> Response:
        return self._list_pages(
            f"/repos/{self.repo}/pulls",
            params={"state": state, "per_page": 100}, etag=etag,
        )

    def combined_status(self, sha: str) -> Response:
        return self.request("GET", f"/repos/{self.repo}/commits/{sha}/status")

    def check_runs(self, sha: str) -> Response:
        """Fetch all check runs; never return a misleading partial success."""
        path = f"/repos/{self.repo}/commits/{sha}/check-runs"
        checks: list[dict[str, Any]] = []
        first: Optional[Response] = None
        for page in range(1, 1001):
            resp = self.request(
                "GET", path, params={"per_page": 100, "page": page}
            )
            if page == 1:
                first = resp
            body = resp.data
            if not isinstance(body, dict) or not isinstance(body.get("check_runs"), list):
                raise GitHubError("invalid GitHub check-runs response")
            batch = body["check_runs"]
            if not all(isinstance(item, dict) for item in batch):
                raise GitHubError("malformed GitHub check-run")
            checks.extend(batch)
            if not self._has_next_page(resp.headers, path=path, page=page):
                total = first.data.get("total_count") if first else None
                if total is not None and (
                    type(total) is not int or total != len(checks)
                ):
                    raise GitHubError("incomplete GitHub check-runs response")
                assert first is not None
                return Response(
                    first.status, first.headers,
                    {**first.data, "check_runs": checks},
                )
        raise GitHubError("GitHub check runs exceed 1000 pages")

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
