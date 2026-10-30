"""Filesystem-only execution boundary for untrusted native agent tool requests.

The workspace root and policy must come from a trusted control plane; never let
an LLM choose either one. On POSIX, directory-descriptor traversal with
O_NOFOLLOW prevents symlink traversal, including races between validation and I/O.
No subprocess, Git, network or shell operations are exposed here.

This is a staged component, NOT proof of a complete secure agent sandbox.
"""
from __future__ import annotations

import errno
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .errors import ToolPolicyDenied
from .tool_policy import ToolPolicyEngine

_BLOCKED_SEGMENTS = frozenset({
    ".git", ".ssh", ".aws", ".hermes", ".kube", ".gnupg",
})
_PRIVATE_SUFFIXES = (".pem", ".p12", ".pfx", ".key")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
_TEMP_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)


class ScopedFilesystemExecutor:
    """Only read/write regular text files inside one trusted workspace.

    Fail closed on Windows and platforms without descriptor-relative nofollow
    operations; a separate verified Windows implementation is required.
    """

    def __init__(
        self,
        workspace_root: str | os.PathLike[str],
        permissions: Mapping[str, Any],
        *,
        max_read_bytes: int = 1_048_576,
        max_write_bytes: int = 1_048_576,
    ) -> None:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ToolPolicyDenied("Scoped filesystem executor requires POSIX nofollow support")
        if max_read_bytes <= 0 or max_write_bytes <= 0:
            raise ValueError("File size limits must be positive")
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace root must be an existing directory")
        self.root = str(root)
        self.permissions = dict(permissions)
        self.max_read_bytes = max_read_bytes
        self.max_write_bytes = max_write_bytes

    def _checked_parts(self, path: str | os.PathLike[str], action: str) -> list[str]:
        if not isinstance(path, (str, os.PathLike)):
            raise ToolPolicyDenied("Invalid workspace resource")
        text = os.fspath(path)
        if not isinstance(text, str) or not text or "\x00" in text or "\\" in text:
            raise ToolPolicyDenied("Invalid workspace resource")

        # Reject any explicit dot traversal; normpath would otherwise conceal it.
        raw_parts = text.split("/")
        if any(part in (".", "..") for part in raw_parts):
            raise ToolPolicyDenied("Workspace path traversal denied")
        absolute = os.path.abspath(text if os.path.isabs(text) else os.path.join(self.root, text))
        try:
            if os.path.commonpath((self.root, absolute)) != self.root:
                raise ToolPolicyDenied("Filesystem access outside workspace denied")
        except ValueError as exc:
            raise ToolPolicyDenied("Filesystem access outside workspace denied") from exc

        rel = os.path.relpath(absolute, self.root)
        if rel == ".":
            raise ToolPolicyDenied("Workspace root is not a file")
        parts = rel.split(os.sep)
        for part in parts:
            lowered = part.lower()
            if (
                part in ("", ".", "..")
                or lowered in _BLOCKED_SEGMENTS
                or lowered == ".env"
                or lowered.startswith(".env.")
                or lowered.endswith(_PRIVATE_SUFFIXES)
            ):
                raise ToolPolicyDenied("Protected workspace resource denied")

        # Always enforce before opening even the first path component.
        ToolPolicyEngine.enforce(self.permissions, action, absolute)
        return parts

    @contextmanager
    def _parent_fd(self, parts: list[str]) -> Iterator[int]:
        """Open every ancestor as a directory without following symlinks."""
        opened: list[int] = []
        try:
            fd = os.open(self.root, _DIR_FLAGS)
            opened.append(fd)
            for part in parts[:-1]:
                try:
                    fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise ToolPolicyDenied("Symlink or non-directory ancestor denied") from exc
                    raise
                opened.append(fd)
            yield fd
        finally:
            for fd in reversed(opened):
                os.close(fd)

    @staticmethod
    def _validate_regular(st: os.stat_result) -> None:
        if not stat.S_ISREG(st.st_mode):
            raise ToolPolicyDenied("Only regular workspace files are allowed")
        # Also reject hard links to avoid writes to the same inode outside the
        # workspace. Atomic replacement prevents modifying an existing inode.
        if st.st_nlink > 1:
            raise ToolPolicyDenied("Hard-linked workspace files are denied")

    def read_text(self, path: str | os.PathLike[str]) -> str:
        """Read at most max_read_bytes from an allowed regular UTF-8 file."""
        parts = self._checked_parts(path, "fs_read")
        with self._parent_fd(parts) as parent:
            try:
                fd = os.open(parts[-1], _READ_FLAGS, dir_fd=parent)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise ToolPolicyDenied("Symlink file denied") from exc
                raise
            try:
                self._validate_regular(os.fstat(fd))
                chunks: list[bytes] = []
                remaining = self.max_read_bytes
                while True:
                    # A regular-file read may return fewer bytes than requested.
                    # Probe one extra byte when the limit is reached.
                    chunk = os.read(fd, min(65_536, remaining + 1))
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        raise ToolPolicyDenied("Read size limit exceeded")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                return b"".join(chunks).decode("utf-8")
            finally:
                os.close(fd)

    def write_text(self, path: str | os.PathLike[str], content: str) -> None:
        """Atomically replace an allowed file without following symlinks."""
        parts = self._checked_parts(path, "fs_write")
        if not isinstance(content, str):
            raise ToolPolicyDenied("Only UTF-8 text writes are allowed")
        data = content.encode("utf-8")
        if len(data) > self.max_write_bytes:
            raise ToolPolicyDenied("Write size limit exceeded")

        with self._parent_fd(parts) as parent:
            try:
                old = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                self._validate_regular(old)

            temporary = f".{parts[-1]}.scoped-{secrets.token_hex(12)}"
            fd = os.open(temporary, _TEMP_FLAGS, 0o600, dir_fd=parent)
            try:
                try:
                    with os.fdopen(fd, "wb", closefd=False) as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(fd)
                finally:
                    os.close(fd)
                # os.replace overwrites a symlink *itself*, never follows it.
                # Therefore a concurrent swap of the destination cannot escape
                # the workspace or modify an inode outside the directory.
                os.replace(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
