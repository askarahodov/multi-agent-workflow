"""Read-only server-owned Git commit verification for leased native attempts."""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

from .errors import ConflictError

_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")


class TrustedGitCommitVerifier:
    """Inspect actual committed objects without trusting worker-reported SHA/paths."""

    def __init__(self, repository: str, git_executable: str):
        root, git = Path(repository), Path(git_executable)
        if (
            os.name != "posix" or not root.is_absolute() or not root.is_dir()
            or root.is_symlink() or any(p.is_symlink() for p in root.parents)
            or not (root / ".git").is_dir() or (root / ".git").is_symlink()
            or not git.is_absolute() or git.is_symlink() or git.name != "git"
            or not git.is_file()
        ):
            raise ValueError("Trusted read-only Git repository and binary required")
        metadata = (root / ".git").stat()
        binary = git.stat()
        if (
            metadata.st_mode & 0o022 or binary.st_mode & 0o022
            or not binary.st_mode & 0o111
            or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
        ):
            raise ValueError("Trusted Git metadata and executable must be protected")
        self.repository = root.resolve(strict=True)
        self.git = str(git)

    def _git(self, *args: str) -> bytes:
        env = {
            "PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
            "LANG": "C", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "",
        }
        try:
            result = subprocess.run(
                [self.git, "-c", "core.hooksPath=/dev/null",
                 "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
                 "-c", "core.attributesFile=/dev/null",
                 "-c", "diff.external=", "-c", "credential.helper=",
                 *args],
                cwd=str(self.repository), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise ConflictError("Trusted Git verification unavailable") from None
        if result.returncode != 0 or len(result.stdout) > 131072:
            raise ConflictError("Trusted Git verification rejected artifact")
        return result.stdout

    def verify(self, task_id: str, attempt_id: str, commit_sha: str,
               changed_paths: list[str]) -> None:
        if any(type(x) is not str or _ID.fullmatch(x) is None for x in (task_id, attempt_id)):
            raise ConflictError("Trusted Git attempt identity invalid")
        if type(commit_sha) is not str or _SHA.fullmatch(commit_sha) is None:
            raise ConflictError("Trusted Git SHA invalid")
        if type(changed_paths) is not list or not 1 <= len(changed_paths) <= 64:
            raise ConflictError("Trusted Git path list invalid")
        ref = f"refs/maw/attempts/{task_id}-{attempt_id}"
        resolved = self._git("rev-parse", "--verify", f"{ref}^{{commit}}").decode("ascii").strip()
        if resolved != commit_sha:
            raise ConflictError("Worker Git SHA does not match trusted attempt ref")
        parents = self._git("rev-list", "--parents", "-n", "1", resolved).split()
        if len(parents) != 2 or parents[0].decode("ascii") != resolved:
            raise ConflictError("Trusted Git commit topology invalid")
        raw = self._git(
            "diff-tree", "--no-commit-id", "-r", "--name-only", "-z", resolved,
        )
        try:
            actual = tuple(sorted(part.decode("utf-8") for part in raw.split(b"\0") if part))
        except UnicodeDecodeError:
            raise ConflictError("Trusted Git paths malformed") from None
        if len(actual) != len(changed_paths) or actual != tuple(sorted(changed_paths)):
            raise ConflictError("Worker paths differ from trusted Git commit")
        for path in actual:
            parts = path.split("/")
            if (
                not path.startswith("out/") or len(path) > 256 or "\\\\" in path
                or any(not part or part in (".", "..") for part in parts)
                or any(part.lower().startswith(".env") or part.lower() in
                       (".git", ".ssh", ".aws", ".hermes") or
                       part.lower().endswith((".key", ".pem", ".p12", ".pfx"))
                       for part in parts)
            ):
                raise ConflictError("Trusted Git paths violate artifact policy")
        raw_tree = self._git("ls-tree", "-r", "-z", resolved, "--", "out")
        entries = {}
        try:
            for entry in raw_tree.split(b"\0"):
                if not entry:
                    continue
                header, name = entry.split(b"\t", 1)
                mode, kind, _oid = header.split(b" ")
                path = name.decode("utf-8")
                if path in entries:
                    raise ConflictError("Duplicate trusted Git path")
                entries[path] = (mode, kind)
        except (ValueError, UnicodeError):
            raise ConflictError("Trusted Git tree malformed") from None
        if any(entries.get(path) not in ((b"100644", b"blob"), (b"100755", b"blob"))
               for path in actual):
            raise ConflictError("Trusted Git artifact is not a regular committed file")
