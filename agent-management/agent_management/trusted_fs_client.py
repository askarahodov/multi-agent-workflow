"""Trusted remote filesystem dispatcher and opt-in leased agent runner.

Model-controlled data is *only* a tool_call event. Run/task/agent identity,
server lease, gateway origin and gateway credential come from trusted worker
construction. No database mount or workspace path is needed on remote workers.

The gate is a separate privileged service; use only with strict OS isolation.
This client never retries ambiguous requests, redirects or replays tool calls.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from .native_tool_dispatch import NativeFilesystemDispatcher, ToolOutcome

_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{40,128}\Z")
_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_ERRORS_FOR_MODEL = frozenset({"UNKNOWN_TOOL", "INVALID_ARGUMENTS", "POLICY_DENIED", "TOOL_IO_ERROR"})


class TrustedGatewayError(RuntimeError):
    """Sanitized loss of trusted remote I/O authorization or availability."""


class TrustedRemoteFilesystemDispatcher:
    """Opaque per-attempt identity bound once by the trusted HTTP-worker.

    Allows only explicitly authenticated HTTPS transport. Gateway errors
    indicating an ambiguous side effect or revoked lease are fatal to the
    agent loop; they are NOT handed to the model for retry.
    """

    def __init__(
        self, *,
        gateway_url: str,
        gateway_key: str,
        run_id: str,
        task_id: str,
        attempt_id: str,
        agent_id: str,
        lease_token: str,
        timeout_seconds: float = 10.0,
        ca_file: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(gateway_url)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Trusted tool gateway requires bare HTTPS origin")
        if not isinstance(gateway_key, str) or not 32 <= len(gateway_key) <= 128:
            raise ValueError("Dedicated trusted gateway key required")
        if any(not isinstance(v, str) or not _ID.fullmatch(v)
               for v in (run_id, task_id, attempt_id, agent_id)):
            raise ValueError("Trusted control-plane identifiers required")
        if not isinstance(lease_token, str) or not _TOKEN.fullmatch(lease_token):
            raise ValueError("Server-issued attempt lease required")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Gateway timeout outside trusted bounds")
        self._identity = {
            "run_id": run_id, "task_id": task_id, "attempt_id": attempt_id,
            "agent_id": agent_id, "lease_token": lease_token,
        }
        self._client = httpx.AsyncClient(
            base_url=gateway_url.rstrip("/"),
            headers={"X-Gateway-Key": gateway_key},
            follow_redirects=False,
            timeout=timeout_seconds, trust_env=False,
            verify=ca_file if ca_file is not None else True, transport=transport,
        )

    @staticmethod
    def tools_schema() -> list[dict[str, Any]]:
        return NativeFilesystemDispatcher.tools_schema()

    async def __aenter__(self) -> TrustedRemoteFilesystemDispatcher:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self._client.aclose()

    async def dispatch_async(self, event: Mapping[str, Any]) -> ToolOutcome:
        # Never let the provider choose identity, origin or any transport header.
        if (
            not isinstance(event, dict)
            or event.get("type") != "tool_call"
            or not isinstance(event.get("id"), str)
            or not _CALL_ID.fullmatch(event["id"])
            or not isinstance(event.get("name"), str)
            or not isinstance(event.get("arguments"), dict)
        ):
            raise TrustedGatewayError("Invalid remote tool request")
        name = event["name"]
        # Shape/arguments/path policy and durable at-most-once are validated
        # by the gateway. Restrict names here as defense-in-depth.
        if name not in ("read_file", "write_file"):
            raise TrustedGatewayError("Unauthorized remote tool name")
        try:
            response = await self._client.post(
                "/v1/filesystem/dispatch",
                json={**self._identity, "event": event},
                follow_redirects=False,
            )
        except (httpx.RequestError, ValueError, TypeError):
            raise TrustedGatewayError(
                "Remote tool outcome unavailable; attempt requires reconciliation"
            ) from None
        # Do not consume or disclose unexpected remote response bodies.
        # A timeout or redirect may have occurred *after* a side effect.
        if response.status_code != 200:
            raise TrustedGatewayError(
                "Remote tool rejected; attempt requires reconciliation"
            )
        try:
            body = response.json()
        except ValueError:
            raise TrustedGatewayError("Malformed remote tool outcome") from None
        if (
            not isinstance(body, dict) or set(body) != {"ok", "content", "error_code"}
            or type(body["ok"]) is not bool
            or not isinstance(body["content"], str)
        ):
            raise TrustedGatewayError("Malformed remote tool outcome")
        if len(body["content"]) > 1_048_576:
            raise TrustedGatewayError("Remote tool output exceeds size limit")
        if body["ok"]:
            if body["error_code"] is not None:
                raise TrustedGatewayError("Inconsistent remote tool outcome")
            return ToolOutcome(event["id"], name, True, body["content"])
        if body["content"] or body["error_code"] not in _ERRORS_FOR_MODEL:
            # ATTEMPT_FENCED, DUPLICATE_CALL, ledger outages and unknown codes
            # are fatal, never a prompt inviting the model to try again.
            raise TrustedGatewayError(
                "Remote tool attempt no longer safe; reconciliation required"
            )
        return ToolOutcome(event["id"], name, False, "", body["error_code"])


class TrustedLeasedGatewayRunner:
    """Explicit worker integration: NativeHttpWorker(leased_runner=instance).

    The provider and initial messages are injected by a trusted application.
    run_id and task_id are taken only from the authenticated server task
    returned after a claim; lease comes only from the trusted claim response.
    """

    def __init__(
        self, *,
        gateway_url: str,
        gateway_key: str,
        agent_id: str,
        provider: Any,
        messages: Sequence[Mapping[str, Any]],
        transport: httpx.AsyncBaseTransport | None = None,
        ca_file: str | None = None,
        max_turns: int = 3,
        max_total_tokens: int = 1024,
        max_tool_calls: int = 4,
        journal_factory: Any | None = None,
    ) -> None:
        if any(not isinstance(v, Mapping) for v in messages) or not messages:
            raise ValueError("Trusted initial agent messages required")
        if max_turns < 1 or max_total_tokens < 1 or max_tool_calls < 0:
            raise ValueError("Trusted agent budgets required")
        self._gateway_url = gateway_url
        self._gateway_key = gateway_key
        self._agent_id = agent_id
        self._provider = provider
        self._messages = [dict(item) for item in messages]
        self._transport = transport
        self._ca_file = ca_file
        if journal_factory is not None and not callable(journal_factory):
            raise TypeError("Trusted journal factory must be callable")
        self._journal_factory = journal_factory
        self._limits = (max_turns, max_total_tokens, max_tool_calls)

    async def __call__(
        self, task: dict[str, Any], attempt_id: str, lease: Any,
    ) -> str:
        if (
            not isinstance(task, dict)
            or not hasattr(lease, "token")
            or not hasattr(lease, "generation")
            or not hasattr(lease, "expires_at")
            or type(lease.generation) is not int or lease.generation < 1
            or not isinstance(lease.expires_at, datetime)
            or lease.expires_at.tzinfo is None
            or lease.expires_at <= datetime.now(timezone.utc)
        ):
            raise TrustedGatewayError("Invalid trusted task or lease")
        # task and lease are supplied to this callable by NativeHttpWorker,
        # never by model tool arguments. Do not extend model messages with it.
        async with TrustedRemoteFilesystemDispatcher(
            gateway_url=self._gateway_url, gateway_key=self._gateway_key,
            run_id=task.get("workflow_run_id"), task_id=task.get("id"),
            attempt_id=attempt_id, agent_id=self._agent_id,
            lease_token=lease.token, transport=self._transport,
            ca_file=self._ca_file,
        ) as dispatcher:
            from .agent_loop import run_agent_loop
            from .agent_journal import AgentEventJournal

            journal = None
            if self._journal_factory is not None:
                journal = self._journal_factory(task, attempt_id)
                if not isinstance(journal, AgentEventJournal):
                    raise TypeError("Trusted journal factory must return an AgentEventJournal")
            result = await run_agent_loop(
                self._provider, dispatcher, self._messages,
                max_turns=self._limits[0],
                max_total_tokens=self._limits[1],
                max_tool_calls=self._limits[2],
                journal=journal,
            )
            return result.output
