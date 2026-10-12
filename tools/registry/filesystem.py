"""Filesystem tools (PRD §13 / ADR-012 §3.4).

``fs_read`` / ``fs_write`` / ``fs_list`` / ``fs_search`` operate on the
agent's scoped workspace only. Every path is canonicalized (symlinks resolved)
and must fall inside the execution context's allowed prefixes; anything else is
denied before the filesystem is touched.

Handler contract: each handler returns *raw JSON-serializable data* on success
(the registry validates it against the result schema) and raises
:class:`ToolExecutionError` on failure.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolExecutionError,
    ToolSpec,
    canonical_path,
    is_within,
)

# Max size (bytes) read by fs_read to avoid reading huge files accidentally.
MAX_READ_BYTES = 25 * 1024 * 1024
MAX_SEARCH_RESULTS = 100
MAX_SEARCH_DEPTH = 32


def _ensure_scope(path: Path, context: ExecutionContext) -> Path:
    """Canonicalize and confirm ``path`` is inside the workspace scope."""
    resolved = canonical_path(path)
    allowed = context.allowed_paths or (context.workspace_root and (str(context.workspace_root.resolve()),))
    if allowed and not is_within(resolved, allowed):
        raise ToolExecutionError(f"path {resolved} outside allowed workspace scope")
    return resolved


async def _fs_read(params: dict, context: ExecutionContext) -> dict:
    target = _ensure_scope(Path(params["path"]), context)
    if not target.is_file():
        raise ToolExecutionError(f"not a readable file: {target}")
    if target.stat().st_size > MAX_READ_BYTES:
        raise ToolExecutionError(f"file too large to read ({target.stat().st_size} bytes)")
    try:
        data = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolExecutionError(f"read failed: {exc}") from exc
    return {"path": str(target), "content": data}


async def _fs_write(params: dict, context: ExecutionContext) -> dict:
    target = _ensure_scope(Path(params["path"]), context)
    content = params.get("content", "")
    mode = params.get("mode", "write")  # "write" (truncate) or "append"
    try:
        if mode == "append":
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ToolExecutionError(f"write failed: {exc}") from exc
    return {"path": str(target), "bytes": len(content.encode("utf-8"))}


async def _fs_list(params: dict, context: ExecutionContext) -> dict:
    base = _ensure_scope(Path(params["path"] or "."), context)
    if not base.is_dir():
        raise ToolExecutionError(f"not a directory: {base}")
    recursive = bool(params.get("recursive", False))
    entries = []
    if not recursive:
        for child in sorted(base.iterdir()):
            if child.is_symlink() and not child.is_file() and not child.is_dir():
                continue
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
    else:
        for root, dirs, files in os.walk(base):
            depth = len(Path(root).relative_to(base).parts)
            if depth >= MAX_SEARCH_DEPTH:
                dirs[:] = []
                continue
            dirs.sort()
            for name in sorted(files):
                p = Path(root) / name
                entries.append({"name": str(p.relative_to(base)), "type": "file", "size": p.stat().st_size})
    if len(entries) > MAX_SEARCH_RESULTS:
        entries = entries[:MAX_SEARCH_RESULTS]
    return {"path": str(base), "entries": entries, "count": len(entries)}


async def _fs_search(params: dict, context: ExecutionContext) -> dict:
    base = _ensure_scope(Path(params["path"] or "."), context)
    pattern = params.get("pattern", "")
    if not pattern:
        raise ToolExecutionError("pattern is required")
    if not base.is_dir():
        raise ToolExecutionError(f"not a directory: {base}")
    matches = []
    for root, dirs, files in os.walk(base):
        depth = len(Path(root).relative_to(base).parts)
        if depth >= MAX_SEARCH_DEPTH:
            dirs[:] = []
            continue
        for name in files + dirs:
            if pattern in name:
                matches.append(str((Path(root) / name).relative_to(base)))
        if len(matches) >= MAX_SEARCH_RESULTS:
            break
    return {"path": str(base), "matches": matches, "count": len(matches)}


def register_filesystem(registry) -> None:
    registry.register(
        ToolSpec(
            name="fs_read",
            category=ToolCategory.FILESYSTEM,
            description="Read a text file inside the scoped workspace.",
            params_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "max_bytes": {"type": "integer"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            required_policy=["fs_read"],
            default_timeout_ms=10000,
        ),
        handler=_fs_read,
    )
    registry.register(
        ToolSpec(
            name="fs_write",
            category=ToolCategory.FILESYSTEM,
            description="Write (or append) text to a file inside the scoped workspace.",
            params_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {"enum": ["write", "append"]},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            result_schema={"type": "object", "properties": {"path": {"type": "string"}, "bytes": {"type": "integer"}}, "required": ["path", "bytes"]},
            required_policy=["fs_write"],
            default_timeout_ms=10000,
            is_destructive=True,
        ),
        handler=_fs_write,
    )
    registry.register(
        ToolSpec(
            name="fs_list",
            category=ToolCategory.FILESYSTEM,
            description="List directory entries (optionally recursive) in the workspace.",
            params_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean"}},
                "additionalProperties": False,
            },
            result_schema={"type": "object", "properties": {"path": {"type": "string"}, "entries": {"type": "array"}, "count": {"type": "integer"}}, "required": ["path", "entries", "count"]},
            required_policy=["fs_read"],
            default_timeout_ms=10000,
        ),
        handler=_fs_list,
    )
    registry.register(
        ToolSpec(
            name="fs_search",
            category=ToolCategory.FILESYSTEM,
            description="Search filenames within the workspace for a substring.",
            params_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}},
                "required": ["pattern"],
                "additionalProperties": False,
            },
            result_schema={"type": "object", "properties": {"path": {"type": "string"}, "matches": {"type": "array"}, "count": {"type": "integer"}}, "required": ["path", "matches", "count"]},
            required_policy=["fs_read"],
            default_timeout_ms=10000,
        ),
        handler=_fs_search,
    )