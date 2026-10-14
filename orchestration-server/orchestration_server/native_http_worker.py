"""HTTPS-only, authenticated transport for a future standalone native worker.

This module intentionally has NO provider, model, tool or process entrypoint.
A trusted deployment must inject the runner, approved workspace and ledger.
It may invoke a runner ONLY after the orchestration API returns a valid claim.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .native_bridge import InvalidNativeOutput, parse_native_output

_SERVER_ID = re.compile(r"[A-Za-z0-9-]{1,64}\\Z")

RemoteRunner = Callable[[dict[str, Any], str], Awaitable[str]]


class RemoteWorkerError(RuntimeError):
    """Sanitized transport/contract failure; never includes tokens or URLs."""


@dataclass(frozen=True)
class RemoteAttemptResult:
    task_id: str
    attempt_id: str
    status: str
    verified: bool


@dataclass(frozen=True)
class RemoteWorkerBatch:
    attempts: tuple[RemoteAttemptResult, ...]
    stopped_on_failure: bool


class NativeHttpWorker:
    """One bounded, explicit polling pass over the authenticated REST API.

    Never follows redirects, uses ambient proxies or reads credentials from
    untrusted task objects. HTTP is allowed only for explicit loopback dev,
    never for a remote host. Bad API responses fail closed before model calls.
    """

    def __init__(
        self,
        *,
        server_url: str,
        api_key: str,
        agent_id: str,
        runner: RemoteRunner,
        allow_loopback_http: bool = False,
        max_runs: int = 20,
        max_tasks_per_run: int = 50,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(server_url)
        is_loopback = parsed.hostname in ("127.0.0.1", "::1")
        if (
            parsed.scheme != "https"
            and not (allow_loopback_http and parsed.scheme == "http" and is_loopback)
        ):
            raise ValueError("Native worker requires HTTPS or explicit loopback development")
        if (
            not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ("", "/")
        ):
            raise ValueError("Native worker server URL must be a bare trusted origin")
        if not isinstance(api_key, str) or len(api_key.strip()) < 8:
            raise ValueError("Native worker API key is required")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("Trusted worker agent ID is required")
        if not callable(runner):
            raise TypeError("Trusted native runner required")
        if not (1 <= max_runs <= 200 and 1 <= max_tasks_per_run <= 200):
            raise ValueError("Native HTTP worker scan bounds invalid")
        if not 0 < timeout_seconds <= 120:
            raise ValueError("Native HTTP worker timeout invalid")
        self.agent_id = agent_id
        self.runner = runner
        self.max_runs = max_runs
        self.max_tasks_per_run = max_tasks_per_run
        self._client = httpx.AsyncClient(
            base_url=server_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self) -> NativeHttpWorker:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method, "/api/v1" + path, params=params, json=payload,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            raise RemoteWorkerError("Orchestration transport unavailable") from exc
        if response.status_code in (409, 422):
            raise _ClaimConflict("Orchestration claim was rejected")
        if response.status_code != (201 if path.endswith("/claim") else 200):
            # Never include potentially secret remote error bodies.
            raise RemoteWorkerError("Orchestration API request rejected")
        try:
            body = response.json()
        except ValueError as exc:
            raise RemoteWorkerError("Invalid orchestration API response") from exc
        if not isinstance(body, dict):
            raise RemoteWorkerError("Invalid orchestration API response")
        return body

    async def _page(
        self, path: str, *, params: dict[str, Any], max_items: int,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        next_cursor: str | None = None
        cursors: set[str] = set()
        while len(records) < max_items:
            remaining = max_items - len(records)
            q = {**params, "limit": min(remaining, 200)}
            if next_cursor is not None:
                q["after"] = next_cursor
            page = await self._request("GET", path, params=q)
            items = page.get("items")
            if not isinstance(items, list) or len(items) > q["limit"] or any(
                not isinstance(x, dict) for x in items
            ):
                raise RemoteWorkerError("Malformed orchestration cursor page")
            records.extend(items)
            next_cursor = page.get("next_cursor")
            if next_cursor is None or len(records) == max_items:
                break
            if not isinstance(next_cursor, str) or next_cursor in cursors or not items:
                raise RemoteWorkerError("Invalid orchestration pagination cursor")
            cursors.add(next_cursor)
        return records

    @staticmethod
    def _ready(task: dict[str, Any]) -> bool:
        if task.get("status") != "pending":
            return False
        retry_at = task.get("retry_at")
        if retry_at:
            if not isinstance(retry_at, str):
                raise RemoteWorkerError("Malformed retry time")
            try:
                dt = datetime.fromisoformat(retry_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise RemoteWorkerError("Malformed retry time") from exc
            if dt.tzinfo is None:
                raise RemoteWorkerError("Retry deadline has no timezone")
            if dt > datetime.now(timezone.utc):
                return False
        return True

    async def run_once(self) -> RemoteAttemptResult | None:
        """One explicit poll; at most one claim and one provider invocation."""
        runs = await self._page("/workflows/runs", params={"status": "running"}, max_items=self.max_runs)
        for run in runs:
            run_id = run.get("id")
            if not isinstance(run_id, str) or not _SERVER_ID.fullmatch(run_id):
                raise RemoteWorkerError("Malformed workflow run ID")
            tasks = await self._page(
                f"/workflows/runs/{run_id}/tasks", params={},
                max_items=self.max_tasks_per_run,
            )
            for task in tasks:
                if not self._ready(task):
                    continue
                task_id = task.get("id")
                if not isinstance(task_id, str) or not _SERVER_ID.fullmatch(task_id):
                    raise RemoteWorkerError("Malformed task ID")
                try:
                    claim = await self._request(
                        "POST", f"/tasks/{task_id}/claim",
                        payload={"agent_id": self.agent_id},
                    )
                except _ClaimConflict:
                    # Another worker claimed this task or its retry isn't due.
                    continue
                attempt_id = claim.get("id")
                if (
                    not isinstance(attempt_id, str)
                    or not _SERVER_ID.fullmatch(attempt_id)
                    or claim.get("task_id") != task_id
                    or claim.get("agent_id") != self.agent_id
                ):
                    raise RemoteWorkerError("Malformed orchestration claim response")
                try:
                    output = await self.runner(task, attempt_id)
                    decoded = parse_native_output(output)
                except Exception as exc:
                    reason = (
                        "native_output_invalid" if isinstance(exc, InvalidNativeOutput)
                        else "native_runner_failed"
                    )
                    failed = await self._request(
                        "POST", f"/tasks/{task_id}/attempts/{attempt_id}/fail",
                        params={"agent_id": self.agent_id},
                        payload={"error": reason},
                    )
                    return RemoteAttemptResult(task_id, attempt_id, str(failed.get("status")), False)
                submitted = await self._request(
                    "POST", f"/tasks/{task_id}/attempts/{attempt_id}/submit",
                    params={"agent_id": self.agent_id},
                    payload={"output": decoded},
                )
                verification = submitted.get("verification_result") or {}
                verified = (
                    submitted.get("status") == "completed"
                    and isinstance(verification, dict)
                    and verification.get("valid") is True
                )
                return RemoteAttemptResult(task_id, attempt_id, str(submitted.get("status")), verified)
        return None

    async def run_batch(self, *, max_attempts: int = 1) -> RemoteWorkerBatch:
        """Explicitly bounded pass; stop after first failure or empty queue."""
        if not 1 <= max_attempts <= 100:
            raise ValueError("Invalid remote worker batch limit")
        results: list[RemoteAttemptResult] = []
        for _ in range(max_attempts):
            attempt = await self.run_once()
            if attempt is None:
                break
            results.append(attempt)
            if not attempt.verified:
                return RemoteWorkerBatch(tuple(results), stopped_on_failure=True)
        return RemoteWorkerBatch(tuple(results), stopped_on_failure=False)


class _ClaimConflict(Exception):
    pass
