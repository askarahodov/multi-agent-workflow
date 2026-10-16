"""HTTPS-only, authenticated transport for a future standalone native worker.

This module intentionally has NO provider, model, tool or process entrypoint.
A trusted deployment must inject the runner, approved workspace and ledger.
It may invoke a runner ONLY after the orchestration API returns a valid claim.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .native_bridge import InvalidNativeOutput, parse_native_output

_SERVER_ID = re.compile(r"[A-Za-z0-9-]{1,64}")

RemoteRunner = Callable[[dict[str, Any], str], Awaitable[str]]
LeasedRemoteRunner = Callable[[dict[str, Any], str, "TrustedAttemptLease"], Awaitable[str]]


class RemoteWorkerError(RuntimeError):
    """Sanitized transport/contract failure; never includes tokens or URLs."""


@dataclass(frozen=True, repr=False)
class TrustedAttemptLease:
    """Opaque capability only for trusted runner, never LLM/tool payload."""

    token: str
    generation: int
    expires_at: datetime


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
        runner: RemoteRunner | None = None,
        leased_runner: LeasedRemoteRunner | None = None,
        require_lease: bool = False,
        lease_renew_interval_seconds: float = 1.0,
        allow_loopback_http: bool = False,
        max_runs: int = 20,
        max_tasks_per_run: int = 50,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        stop_event: asyncio.Event | None = None,
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
        if require_lease:
            if not callable(leased_runner):
                raise TypeError("Trusted leased runner is required")
        elif not callable(runner) or leased_runner is not None:
            raise TypeError("Trusted native runner required")
        if (
            isinstance(lease_renew_interval_seconds, bool)
            or not isinstance(lease_renew_interval_seconds, (int, float))
            or not 0 < lease_renew_interval_seconds <= 30
            or (isinstance(lease_renew_interval_seconds, float) and not math.isfinite(lease_renew_interval_seconds))
        ):
            raise ValueError("Lease renewal interval must be between 0 and 30 seconds")
        if (
            type(max_runs) is not int or type(max_tasks_per_run) is not int
            or not (1 <= max_runs <= 200 and 1 <= max_tasks_per_run <= 200)
        ):
            raise ValueError("Native HTTP worker scan bounds invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 120
            or (isinstance(timeout_seconds, float) and not math.isfinite(timeout_seconds))
        ):
            raise ValueError("Native HTTP worker timeout invalid")
        if stop_event is not None and not isinstance(stop_event, asyncio.Event):
            raise TypeError("Trusted shutdown event required")
        self._stop_event = stop_event
        self.agent_id = agent_id
        self.runner = runner
        self.leased_runner = leased_runner
        self.require_lease = require_lease
        self.lease_renew_interval_seconds = lease_renew_interval_seconds
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
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method, "/api/v1" + path, params=params, json=payload,
                headers=headers, follow_redirects=False,
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

    @staticmethod
    def _parse_lease_expiry(value: Any) -> datetime:
        if not isinstance(value, str):
            raise RemoteWorkerError("Malformed attempt lease expiry")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RemoteWorkerError("Malformed attempt lease expiry") from exc
        if parsed.tzinfo is None:
            raise RemoteWorkerError("Attempt lease expiry requires timezone")
        expires = parsed.astimezone(timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise RemoteWorkerError("Attempt lease is expired")
        return expires

    def _lease_from_claim(self, claim: dict[str, Any]) -> TrustedAttemptLease:
        token = claim.get("lease_token")
        generation = claim.get("lease_generation")
        if (
            not isinstance(token, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token)
            or type(generation) is not int
            or generation < 1
            or generation != claim.get("attempt_number")
        ):
            raise RemoteWorkerError("Malformed server-issued attempt lease")
        expires = self._parse_lease_expiry(claim.get("lease_expires_at"))
        return TrustedAttemptLease(token, generation, expires)

    async def _renew_attempt(
        self, task_id: str, attempt_id: str, lease: TrustedAttemptLease,
    ) -> TrustedAttemptLease:
        try:
            response = await self._request(
                "POST", f"/tasks/{task_id}/attempts/{attempt_id}/lease/renew",
                payload={"agent_id": self.agent_id, "lease_token": lease.token},
            )
        except (_ClaimConflict, RemoteWorkerError):
            raise RemoteWorkerError("Attempt lease renewal unavailable") from None
        if type(response.get("generation")) is not int or response["generation"] != lease.generation:
            raise RemoteWorkerError("Attempt lease generation mismatch")
        expires = self._parse_lease_expiry(response.get("expires_at"))
        return TrustedAttemptLease(lease.token, lease.generation, expires)

    async def _execute_with_renewal(
        self, task: dict[str, Any], attempt_id: str, lease: TrustedAttemptLease,
    ) -> str:
        """Renew only while the runner is active; stop/ESTOP aborts submission.

        Cancellation does not prove a subprocess stopped. The control-plane
        lease/tool gateway is the authoritative fence; an interrupted attempt
        must be reconciled before another execution is permitted.
        """
        assert self.leased_runner is not None
        if self._stop_event is not None and self._stop_event.is_set():
            raise RemoteWorkerError("Worker stopped; attempt requires reconciliation")
        runner_task = asyncio.create_task(
            self.leased_runner(task, attempt_id, lease)
        )
        stop_task = (
            asyncio.create_task(self._stop_event.wait())
            if self._stop_event is not None else None
        )
        try:
            while True:
                if self._stop_event is not None and self._stop_event.is_set():
                    raise RemoteWorkerError("Worker stopped; attempt requires reconciliation")
                left = (lease.expires_at - datetime.now(timezone.utc)).total_seconds()
                if left <= 0:
                    raise RemoteWorkerError("Attempt lease expired during runner")
                interval = min(self.lease_renew_interval_seconds, left / 2)
                waiting = {runner_task}
                if stop_task is not None:
                    waiting.add(stop_task)
                done, _ = await asyncio.wait(
                    waiting, timeout=interval, return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task is not None and stop_task in done:
                    raise RemoteWorkerError("Worker stopped; attempt requires reconciliation")
                if runner_task in done:
                    output = await runner_task
                    if self._stop_event is not None and self._stop_event.is_set():
                        raise RemoteWorkerError("Worker stopped; attempt requires reconciliation")
                    # Recheck the active lease immediately before submit.
                    await self._renew_attempt(task["id"], attempt_id, lease)
                    return output
                lease = await self._renew_attempt(task["id"], attempt_id, lease)
        finally:
            if stop_task is not None:
                stop_task.cancel()
            if not runner_task.done():
                runner_task.cancel()
            # wait_for(task) can wait forever if a non-cooperative runner
            # suppresses CancelledError. Never block shutdown indefinitely.
            pending = {runner_task}
            if stop_task is not None:
                pending.add(stop_task)
            done, _ = await asyncio.wait(pending, timeout=1.0)
            for finished in done:
                if not finished.cancelled():
                    # Consume (but never log) provider errors/secret-bearing text.
                    try:
                        finished.exception()
                    except Exception:
                        pass

    async def run_once(self) -> RemoteAttemptResult | None:
        """One explicit poll; at most one claim and one provider invocation."""
        if self._stop_event is not None and self._stop_event.is_set():
            return None
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
                if self._stop_event is not None and self._stop_event.is_set():
                    return None
                if task.get("workflow_run_id") != run_id:
                    raise RemoteWorkerError("Task does not belong to discovered workflow run")
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
                if self.require_lease:
                    lease = self._lease_from_claim(claim)
                    # Only trusted runner receives the secret; task/model
                    # payload remains unchanged. On any failure leave the
                    # attempt quarantinable, never auto-replay it.
                    try:
                        output = await self._execute_with_renewal(task, attempt_id, lease)
                        decoded = parse_native_output(output)
                    except Exception:
                        raise RemoteWorkerError(
                            "Leased execution stopped; attempt requires reconciliation"
                        ) from None
                else:
                    try:
                        assert self.runner is not None
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
                    headers={"X-Attempt-Lease": lease.token} if self.require_lease else None,
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
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
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
