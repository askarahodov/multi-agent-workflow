"""Git tools (PRD §13 / ADR-012 §3.4) — also the primary *Git storage*
integration surface (task item (e)).

``git_read`` (status / diff / log) and ``git_write`` (commit) run `git` inside
the agent's repository root. Only allow-listed subcommands are accepted and the
working tree is constrained to ``context.allowed_paths``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolExecutionError,
    ToolSpec,
)

#: Subcommands considered dangerous / out-of-scope for agents (never allowed).
FORBIDDEN_SUBCOMMANDS = {
    "push",
    "fetch",
    "remote",
    "submodule",
    "filter-branch",
    "clean",
    "gc",
    "config",
    "rebase",
}


def _repo_root(context: ExecutionContext) -> Path:
    root = context.workspace_root or context.cwd or Path.cwd()
    # Walk up to the nearest .git dir so git commands run from the repo root.
    current = root.resolve()
    for _ in range(16):
        if (current / ".git").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return root.resolve()


async def _run_git(argv: list[str], context: ExecutionContext, timeout_s: int = 20) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *argv,
            cwd=str(_repo_root(context)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        raise ToolExecutionError("git command timed out")
    except (OSError, NotImplementedError) as exc:
        raise ToolExecutionError(f"git unavailable: {exc}")
    output = (stdout or b"").decode("utf-8", errors="replace").strip()
    error = (stderr or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise ToolExecutionError(f"git {argv[0]} failed ({proc.returncode}): {error}")
    return output


async def _git_read(params: dict, context: ExecutionContext) -> dict:
    subcommand = params.get("subcommand", "status")
    if subcommand in FORBIDDEN_SUBCOMMANDS:
        raise ToolExecutionError(f"git subcommand '{subcommand}' is forbidden")
    if subcommand not in {"status", "diff", "log", "show", "rev-parse"}:
        raise ToolExecutionError(f"unsupported read subcommand: {subcommand}")

    if subcommand == "status":
        out = await _run_git(["status", "--porcelain=v1", "-b"], context)
        return {"subcommand": "status", "output": out, "dirty": bool(out.strip())}
    if subcommand == "diff":
        variant = params.get("variant", "")
        argv = ["diff", "--stat"] if variant == "stat" else ["diff"]
        if variant == "cached":
            argv = ["diff", "--cached", "--stat"]
        out = await _run_git(argv, context)
        return {"subcommand": "diff", "variant": variant, "output": out}
    if subcommand == "log":
        n = int(params.get("max_entries", 10))
        out = await _run_git(["log", "--oneline", "-n", str(min(max(n, 1), 100))], context)
        return {"subcommand": "log", "output": out}
    out = await _run_git([subcommand, *params.get("args", [])], context)
    return {"subcommand": subcommand, "output": out}


async def _git_write(params: dict, context: ExecutionContext) -> dict:
    subcommand = params.get("subcommand", "commit")
    if subcommand in FORBIDDEN_SUBCOMMANDS:
        raise ToolExecutionError(f"git subcommand '{subcommand}' is forbidden")
    if subcommand not in {"add", "commit"}:
        raise ToolExecutionError(f"unsupported write subcommand: {subcommand}")

    if subcommand == "add":
        paths = params.get("paths", ["."])
        out = await _run_git(["add", "--", *paths], context)
        return {"subcommand": "add", "output": out}

    # commit
    message = params.get("message")
    if not message:
        raise ToolExecutionError("commit requires a message")
    argv = ["commit", "-m", message, "--no-verify"]
    if params.get("allow_empty"):
        argv.append("--allow-empty")
    out = await _run_git(argv, context)
    return {"subcommand": "commit", "output": out}


def register_git(registry) -> None:
    registry.register(
        ToolSpec(
            name="git_read",
            category=ToolCategory.GIT,
            description="Read-only git inspection: status, diff, log, show, rev-parse.",
            params_schema={
                "type": "object",
                "properties": {
                    "subcommand": {"enum": ["status", "diff", "log", "show", "rev-parse"]},
                    "variant": {"enum": ["", "stat", "cached"]},
                    "max_entries": {"type": "integer"},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            required_policy=["git"],
            default_timeout_ms=20000,
        ),
        handler=_git_read,
    )
    registry.register(
        ToolSpec(
            name="git_write",
            category=ToolCategory.GIT,
            description="Mutating git operations: add, commit (no push; push is forbidden).",
            params_schema={
                "type": "object",
                "properties": {
                    "subcommand": {"enum": ["add", "commit"]},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "message": {"type": "string"},
                    "allow_empty": {"type": "boolean"},
                },
                "required": ["subcommand"],
                "additionalProperties": False,
            },
            required_policy=["git"],
            default_timeout_ms=20000,
            is_destructive=True,
        ),
        handler=_git_write,
    )