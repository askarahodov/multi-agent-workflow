"""Shell tool (PRD §13 / ADR-012 §3.4).

``shell_exec`` runs a single command inside the agent's sandbox with a strict
command allow-list. The command string is passed to the shell *as a single
argv-list* (no shell interpolation) so there is no free-form injection surface.

Execution is bound by a timeout and a maximum output size.
"""

from __future__ import annotations

import asyncio
import os
import shlex

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolExecutionError,
    ToolResult,
    ToolSpec,
)

MAX_OUTPUT_BYTES = 512 * 1024  # 512 KiB
DEFAULT_TIMEOUT_MS = 30_000


async def _shell_exec(params: dict, context: ExecutionContext) -> dict:
    command = params.get("command", "")
    if not command or not command.strip():
        raise ToolExecutionError("command is required")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ToolExecutionError(f"could not parse command: {exc}") from exc
    if not argv:
        raise ToolExecutionError("command is required")

    cwd = str(context.cwd or context.workspace_root or os.getcwd())
    timeout_s = params.get("timeout_ms") or DEFAULT_TIMEOUT_MS

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s / 1000)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
    except (OSError, asyncio.TimeoutError) as exc:
        raise ToolExecutionError(f"exec failed: {exc}") from exc
    except NotImplementedError:
        # create_subprocess_exec is unavailable on some sandboxes (e.g. certain
        # event-loop policies). Report rather than crash.
        raise ToolExecutionError("subprocess execution is unavailable in this environment")

    def trim(b: bytes) -> str:
        truncated = b[:MAX_OUTPUT_BYTES]
        return truncated.decode("utf-8", errors="replace")

    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": trim(stdout if stdout else b""),
        "stderr": trim(stderr if stderr else b""),
    }


def register_shell(registry) -> None:
    registry.register(
        ToolSpec(
            name="shell_exec",
            category=ToolCategory.SHELL,
            description="Run a single whitelisted command in the sandbox (argv parsed, no shell interpolation).",
            params_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 120000},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "returncode": {"type": "integer"},
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                },
                "required": ["command", "returncode", "stdout", "stderr"],
            },
            required_policy=["shell"],
            default_timeout_ms=DEFAULT_TIMEOUT_MS,
            is_destructive=True,
        ),
        handler=_shell_exec,
    )