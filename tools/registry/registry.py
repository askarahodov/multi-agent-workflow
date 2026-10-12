"""The ToolRegistry: resolve, validate, police and execute tools.

A process-scoped registry (ADR-012 §3.1). Tools register by name; execution
goes through :meth:`ToolRegistry.execute`, which applies param-schema
validation, ToolPolicy enforcement, timeout and retry handling, then invokes
the tool's handler inside the supplied :class:`ExecutionContext`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Optional

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPolicyDeniedError,
    ToolResult,
    ToolSpec,
    ToolStatus,
    monotonic_ms,
    stable_hash,
)


class ToolRegistry:
    """Process-scoped registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._call_log: list[dict[str, Any]] = []

    # -- registration -------------------------------------------------------
    def register(self, spec: ToolSpec, handler=None) -> ToolSpec:
        """Register a tool (optionally binding a handler at registration time).

        A handler may also be attached later via :meth:`bind`. Duplicate names
        overwrite the previous spec (versioning is a post-v1 concern).
        """
        if handler is not None:
            spec.handler = handler
        self._tools[spec.name] = spec
        self._tools = dict(sorted(self._tools.items()))
        return spec

    def bind(self, name: str, handler) -> None:
        """Attach (or replace) the runtime handler for an already-registered tool."""
        self._tools[name].handler = handler

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def get_or_raise(self, name: str) -> ToolSpec:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolNotFoundError(f"Unknown tool: {name}")
        return spec

    def names(self) -> list[str]:
        return list(self._tools)

    def list_available(self, policy_permissions: dict | None = None) -> list[str]:
        """Names of tools, optionally filtered by which the policy permits."""
        from .policies import policy_allows

        out = []
        for name in self.names():
            spec = self._tools[name]
            if policy_permissions is None:
                out.append(name)
                continue
            ok = all(
                policy_allows(policy_permissions, kind)
                for kind in spec.required_policy
            )
            if ok:
                out.append(name)
        return out

    # -- execution ----------------------------------------------------------
    async def execute(
        self,
        name: str,
        params: dict,
        context: ExecutionContext,
        *,
        policy_permissions: dict | None = None,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Execute a tool end to end: resolve → validate → enforce → run.

        ``policy_permissions`` are the agent's ToolPolicy permissions; when
        omitted the registry enforces *no* allowed lists for application-level
        kinds and denies any tool that requires a policy kind not granted.
        """
        spec = self.get(name)
        started = monotonic_ms()
        if spec is None:
            result = ToolResult.error(f"Unknown tool: {name}", tool=name)
            self._log_error(name, result, context)
            return result

        # 1. Param validation.
        try:
            spec.validate_params(params)
        except Exception as exc:
            return ToolResult.error(f"invalid params: {exc}", tool=name)

        # 2. Policy enforcement (deny-by-default, ADR-103 / ADR-012 §3.3).
        if policy_permissions is not None:
            from .policies import check_disallowed

            disallowed = check_disallowed(spec, params, policy_permissions, context)
            if disallowed:
                result = ToolResult.denied(disallowed, tool=name)
                result.duration_ms = monotonic_ms() - started
                self._log(spec, params, result, context)
                return result

        if spec.handler is None:
            result = ToolResult.error(f"tool '{name}' has no handler bound", tool=name)
            result.duration_ms = monotonic_ms() - started
            self._log(spec, params, result, context)
            return result

        timeout = timeout_ms if timeout_ms is not None else spec.default_timeout_ms

        # 3. Execute with timeout (and in-process retries for idempotent specs).
        try:
            handler = spec.handler
            data = await self._run_with_retries(handler, spec, params, context, timeout)
        except ToolPolicyDeniedError as exc:
            result = ToolResult.denied(str(exc), tool=name)
            result.duration_ms = monotonic_ms() - started
            self._log(spec, params, result, context)
            return result
        except asyncio.TimeoutError:
            result = ToolResult.timeout(tool=name, duration_ms=monotonic_ms() - started)
            self._log(spec, params, result, context)
            return result
        except ToolExecutionError as exc:
            result = ToolResult.error(str(exc), tool=name, duration_ms=monotonic_ms() - started)
            self._log(spec, params, result, context)
            return result

        # 4. Result schema validation.
        try:
            spec.validate_result(data)
        except Exception as exc:
            result = ToolResult.error(f"invalid result: {exc}", tool=name, duration_ms=monotonic_ms() - started)
            self._log(spec, params, result, context)
            return result

        result = ToolResult.success(data, tool=name, duration_ms=monotonic_ms() - started)
        self._log(spec, params, result, context)
        return result

    async def _invoke_handler(self, handler, params: dict, context: ExecutionContext):
        """Call a tool handler, transparently supporting sync and async handlers.

        Handlers may be plain functions returning a value, ``async def``
        coroutines, or functions returning a :class:`~tools.registry.base.ToolResult`.
        """
        result = handler(params, context)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, ToolResult):
            if result.status is ToolStatus.ERROR:
                raise ToolExecutionError(result.error or "tool returned an error result")
            if result.status is ToolStatus.DENIED:
                raise ToolPolicyDeniedError(result.error or "tool call denied")
            return result.data
        return result

    async def _run_with_retries(self, handler, spec: ToolSpec, params: dict, context: ExecutionContext, timeout_ms: int):
        attempts = max(spec.max_retries, 0) + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    self._invoke_handler(handler, params, context), timeout=timeout_ms / 1000
                )
            except asyncio.TimeoutError:
                raise
            except ToolExecutionError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(0.1 * (2**attempt))
        if last_exc is not None:
            raise ToolExecutionError(str(last_exc))
        raise ToolExecutionError("tool failed")

    # -- audit log -----------------------------------------------------------
    def _log(self, spec: ToolSpec, params: dict, result: ToolResult, context: ExecutionContext) -> None:
        entry = {
            "tool": spec.name,
            "category": spec.category.value,
            "run_id": context.run_id,
            "agent_instance_id": context.agent_instance_id,
            "params_hash": stable_hash(params),
            "result_status": result.status.value,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }
        self._call_log.append(entry)

    def _log_error(self, name: str, result: ToolResult, context: ExecutionContext) -> None:
        self._call_log.append(
            {
                "tool": name,
                "category": "unknown",
                "run_id": context.run_id,
                "agent_instance_id": context.agent_instance_id,
                "params_hash": None,
                "result_status": result.status.value,
                "error": result.error,
                "duration_ms": result.duration_ms,
            }
        )

    def recent_calls(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._call_log[-limit:]

    def clear_log(self) -> None:
        self._call_log = []


# A default singleton registry — tool implementations register against this so
# callers can use ``get_tool_registry()`` instead of constructing their own.
_DEFAULT: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ToolRegistry()
    return _DEFAULT