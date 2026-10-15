"""Verify operator evidence bytes, not merely an operator-supplied digest.

Only the trusted service config supplies the evidence directory. Untrusted
evidence_ref values never become an absolute path, and no symlink (including
any ancestor) is followed. This verifies a point-in-time file snapshot, NOT
whether an operator's claim about external side effects is true.
"""
from __future__ import annotations

import errno
import hashlib
import hmac
import os
import re
import stat
from pathlib import Path

from .errors import BusinessRuleError

_MAX_BYTES = 8 * 1024 * 1024
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PROTECTED = frozenset({".git", ".ssh", ".hermes", ".aws", ".gnupg", ".kube"})


class ReconciliationEvidenceVerifier:
    """Read a regular, unlinked file under a trusted, non-world-writable root.

    Root and parent ownership/mount isolation are a DEPLOYMENT prerequisite.
    Linux/POSIX only, fail closed on Windows or missing nofollow support.
    """

    def __init__(self, trusted_root: str | os.PathLike[str], *, max_bytes: int = _MAX_BYTES):
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ValueError("Evidence verification requires POSIX nofollow support")
        if not isinstance(max_bytes, int) or not 1 <= max_bytes <= _MAX_BYTES:
            raise ValueError("Evidence size limit invalid")
        if not isinstance(trusted_root, (str, os.PathLike)):
            raise ValueError("Trusted evidence root is required")
        candidate = Path(trusted_root)
        if not candidate.is_absolute() or candidate.is_symlink():
            raise ValueError("Trusted evidence root must be an absolute real directory")
        root = candidate.resolve(strict=True)
        info = root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("Trusted evidence root must not be group/world writable")
        self.root = str(root)
        self.max_bytes = max_bytes

    @staticmethod
    def _parts(reference: str) -> list[str]:
        if not isinstance(reference, str) or not reference or len(reference) > 160:
            raise BusinessRuleError("Invalid evidence reference")
        if "\\" in reference or "\x00" in reference or reference.startswith("/"):
            raise BusinessRuleError("Invalid evidence reference")
        parts = reference.split("/")
        if any(
            not _SAFE.fullmatch(part)
            or part in (".", "..")
            or part.lower() in _PROTECTED
            or part.lower().startswith(".env")
            for part in parts
        ):
            raise BusinessRuleError("Invalid evidence reference")
        return parts

    def verify(self, reference: str, expected_sha256: str) -> None:
        """Raise sanitized BusinessRuleError for missing, forged or unsafe proof."""
        parts = self._parts(reference)
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise BusinessRuleError("Invalid evidence SHA-256")

        fds: list[int] = []
        try:
            parent = os.open(self.root, _DIR_FLAGS)
            fds.append(parent)
            for part in parts[:-1]:
                parent = os.open(part, _DIR_FLAGS, dir_fd=parent)
                fds.append(parent)
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
            fds.append(fd)
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                raise BusinessRuleError("Evidence must be a regular unlinked file")
            if file_stat.st_size > self.max_bytes:
                raise BusinessRuleError("Evidence size limit exceeded")
            digest = hashlib.sha256()
            remaining = self.max_bytes
            while True:
                data = os.read(fd, min(64 * 1024, remaining + 1))
                if not data:
                    break
                if len(data) > remaining:
                    raise BusinessRuleError("Evidence size limit exceeded")
                digest.update(data)
                remaining -= len(data)
            if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
                raise BusinessRuleError("Evidence SHA-256 mismatch")
        except (OSError, UnicodeError) as exc:
            # Do not send filesystem paths or raw OS errors to the HTTP client.
            raise BusinessRuleError("Evidence unavailable or unsafe") from exc
        finally:
            for fd in reversed(fds):
                os.close(fd)
