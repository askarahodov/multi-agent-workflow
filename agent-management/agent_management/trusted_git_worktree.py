"""Operator-owned, opt-in local Git worktrees; never a model-facing Git tool.

The trusted control plane provisions a detached per-attempt worktree before
model calls. The model can edit only out/** via ScopedFilesystemExecutor. A
trusted coordinator may commit those files under a live SQLite attempt fence.
No git command, path, commit message, hooks, credentials or branch names are
accepted from the LLM. A crash after ledger claim remains CLAIMED forever
until operator reconciliation; automatic commit replay is forbidden.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shared.attempt_fence import TrustedSqliteAttemptFence
from .errors import ToolPolicyDenied
from .tool_ledger import SqliteToolLedger

_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")
_MAX_FILES = 64
_MAX_TOTAL_BYTES = 4 * 1_048_576
_PROTECTED = frozenset({".git", ".gitattributes", ".gitmodules", ".env", ".ssh", ".aws", ".hermes"})
_PRIVATE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


@dataclass(frozen=True)
class GitArtifact:
    commit_sha: str
    changed_paths: tuple[str, ...]


class TrustedGitWorktreeStore:
    """One local reviewed source repository and private per-attempt directory.

    Do NOT mount this repository's .git into an untrusted model process.
    This is a control-plane service, not a general Git sandbox. Its root
    and git executable must be owned by the trusted operator.
    """

    def __init__(self, repository: str | os.PathLike[str],
                 worktree_home: str | os.PathLike[str], *,
                 git_executable: str, timeout_seconds: float = 15.0):
        if os.name != "posix":
            raise ToolPolicyDenied("Trusted Git worktrees require POSIX isolation")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30:
            raise ValueError("Invalid bounded Git timeout")
        git = Path(git_executable)
        if not git.is_absolute() or git.is_symlink() or git.name != "git":
            raise ToolPolicyDenied("Pinned absolute Git executable required")
        try:
            st = git.stat()
        except OSError:
            raise ToolPolicyDenied("Trusted Git executable unavailable") from None
        if not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111 or st.st_mode & 0o022:
            raise ToolPolicyDenied("Git executable must be immutable and executable")
        self.git = str(git)
        self.repository = self._directory(repository)
        self.home = self._directory(worktree_home)
        if self.repository == self.home or self.repository.is_relative_to(self.home) or self.home.is_relative_to(self.repository):
            raise ToolPolicyDenied("Git repository and worktrees must be separate")
        if self.home.stat().st_mode & 0o077:
            raise ToolPolicyDenied("Trusted worktree directory must be private (0700)")
        if not (self.repository / ".git").is_dir() or (self.repository / ".git").is_symlink():
            raise ToolPolicyDenied("Operator repository must have a real private .git directory")
        st_repo = (self.repository / ".git").stat()
        if st_repo.st_mode & 0o022 or (
            hasattr(os, "geteuid") and st_repo.st_uid != os.geteuid()
        ):
            raise ToolPolicyDenied("Operator Git control directory must not be agent-writable")
        self.timeout_seconds = timeout_seconds
        self._check_repository_config()

    @staticmethod
    def _directory(path: str | os.PathLike[str]) -> Path:
        root = Path(path)
        if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
            raise ToolPolicyDenied("Trusted Git path must be absolute without symlinks")
        if not root.is_dir():
            raise ToolPolicyDenied("Trusted Git directory must exist")
        return root.resolve(strict=True)

    def _git(self, cwd: Path, *argv: str) -> bytes:
        # No shell, PATH lookup, ambient hooks, pager, credentials, user
        # config, external filter/diff program or network transport.
        env = {
            "PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
            "LANG": "C", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "",
            "GIT_AUTHOR_NAME": "Native Worker", "GIT_AUTHOR_EMAIL": "native@localhost",
            "GIT_COMMITTER_NAME": "Native Worker", "GIT_COMMITTER_EMAIL": "native@localhost",
        }
        flags = (
            "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false",
            "-c", "core.pager=cat",
            "-c", "core.attributesFile=/dev/null",
            "-c", "commit.gpgsign=false",
            "-c", "diff.external=",
            "-c", "credential.helper=",
        )
        try:
            result = subprocess.run(
                [self.git, *flags, *argv], cwd=str(cwd), env=env,
                shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                check=False, timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ToolPolicyDenied("Trusted Git operation unavailable") from None
        if result.returncode or len(result.stdout) > 131072:
            raise ToolPolicyDenied("Trusted Git operation denied or failed")
        return result.stdout

    def _check_repository_config(self) -> None:
        git_dir = self.repository / ".git"
        attributes = git_dir / "info" / "attributes"
        if attributes.exists() and attributes.read_bytes().strip():
            raise ToolPolicyDenied("Repository Git attribute overrides denied")
        for parent, dirs, files in os.walk(self.repository):
            if ".git" in dirs:
                dirs.remove(".git")
            if ".gitattributes" in files:
                raise ToolPolicyDenied("Git attributes in source tree denied")
            if any(Path(parent, part).is_symlink() for part in dirs):
                raise ToolPolicyDenied("Symlinked repository directory denied")
        names = self._git(self.repository, "config", "--local", "--name-only", "--list", "-z")
        for key in names.decode("utf-8").split("\x00"):
            if not key:
                continue
            lowered = key.lower()
            if lowered.startswith((
                "filter.", "include.", "includeif.", "alias.", "url.", "protocol.",
                "credential.", "submodule.", "diff.", "merge.", "gpg.",
            )) or lowered in {
                "core.hookspath", "core.fsmonitor", "core.worktree",
                "core.sshcommand", "core.pager", "core.attributesfile", "commit.gpgsign",
            }:
                raise ToolPolicyDenied("Untrusted local Git configuration denied")
        if self._git(self.repository, "rev-parse", "--is-inside-work-tree").strip() != b"true":
            raise ToolPolicyDenied("Operator Git checkout required")
        self._git(self.repository, "rev-parse", "--verify", "HEAD")

    @staticmethod
    def _identity(task_id: str, attempt_id: str) -> str:
        if not all(type(x) is str and _ID.fullmatch(x) for x in (task_id, attempt_id)):
            raise ToolPolicyDenied("Trusted task and attempt IDs required")
        return f"task-{task_id}-attempt-{attempt_id}"

    def _path(self, task_id: str, attempt_id: str) -> Path:
        return self.home / self._identity(task_id, attempt_id)

    def provision(self, task_id: str, attempt_id: str) -> Path:
        """Create a fresh detached worktree, never reuse a previous attempt."""
        path = self._path(task_id, attempt_id)
        if path.exists() or path.is_symlink():
            raise ToolPolicyDenied("Attempt worktree already exists; no replay")
        self._check_repository_config()
        self._git(self.repository, "worktree", "add", "--detach", str(path), "HEAD")
        if path.is_symlink() or not path.is_dir() or not (path / ".git").is_file():
            raise ToolPolicyDenied("Git worktree creation not trustworthy")
        (path / "out").mkdir(mode=0o700, exist_ok=True)
        return path

    @staticmethod
    def _allowed_file(path: str) -> None:
        if not path.startswith("out/") or "\\" in path or "\x00" in path:
            raise ToolPolicyDenied("Git commit may contain only out/ artifacts")
        parts = path.split("/")
        if any(
            not segment or segment in (".", "..")
            or segment.lower() in _PROTECTED
            or segment.lower().startswith(".env.")
            or segment.lower().endswith(_PRIVATE_SUFFIXES)
            for segment in parts
        ):
            raise ToolPolicyDenied("Protected Git artifact denied")

    def _validate_artifacts(self, path: Path) -> tuple[str, ...]:
        out = path / "out"
        if out.is_symlink() or not out.is_dir():
            raise ToolPolicyDenied("Trusted artifact directory unavailable")
        changed = self._git(
            path, "status", "--porcelain=v1", "-z",
            "--untracked-files=all", "--no-renames",
        )
        paths: list[str] = []
        for record in changed.split(b"\0"):
            if not record:
                continue
            if len(record) < 4 or record[2:3] != b" ":
                raise ToolPolicyDenied("Ambiguous Git status entry denied")
            try:
                relative = record[3:].decode("utf-8")
            except UnicodeDecodeError:
                raise ToolPolicyDenied("Non-UTF8 artifact path denied") from None
            self._allowed_file(relative)
            paths.append(relative)
        if not paths or len(paths) > _MAX_FILES or len(set(paths)) != len(paths):
            raise ToolPolicyDenied("Empty or oversized Git artifact set denied")
        size = 0
        # Detect even ignored/private/symlink files that Git status does not show.
        for parent, dirs, files in os.walk(out, followlinks=False):
            for name in dirs + files:
                file = Path(parent, name)
                relative = file.relative_to(path).as_posix()
                self._allowed_file(relative)
                st = file.lstat()
                if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                    raise ToolPolicyDenied("Non-regular Git artifact denied")
                if stat.S_ISREG(st.st_mode):
                    if st.st_nlink != 1:
                        raise ToolPolicyDenied("Hard-linked Git artifact denied")
                    size += st.st_size
                    if size > _MAX_TOTAL_BYTES:
                        raise ToolPolicyDenied("Git artifact bytes exceeded")
        return tuple(sorted(paths))

    def commit(self, task_id: str, attempt_id: str, *,
               fence: TrustedSqliteAttemptFence,
               ledger: SqliteToolLedger) -> GitArtifact:
        """Commit scoped output with an active server attempt and at-most-once ID.

        In particular no automatic retry is possible after an ambiguous Git
        commit even if a network/client/process crash drops its response.
        """
        if not isinstance(fence, TrustedSqliteAttemptFence) or not isinstance(ledger, SqliteToolLedger):
            raise TypeError("Trusted SQLite attempt fence and ledger required")
        if task_id != fence.task_id or attempt_id != fence.attempt_id:
            raise ToolPolicyDenied("Git attempt identity mismatch")
        path = self._path(task_id, attempt_id)
        if path.is_symlink() or not path.is_dir() or not (path / ".git").is_file():
            raise ToolPolicyDenied("Attempt worktree unavailable")
        with fence.operation():
            if not ledger.claim(fence.execution_scope, "git-commit-v1", "git_commit"):
                raise ToolPolicyDenied("Git commit already attempted; reconciliation required")
            try:
                paths = self._validate_artifacts(path)
                self._git(path, "add", "--all", "--", "out")
                staged = self._git(path, "diff", "--cached", "--name-only", "--no-renames", "-z")
                staged_paths = tuple(sorted(p.decode("utf-8") for p in staged.split(b"\0") if p))
                if staged_paths != paths:
                    raise ToolPolicyDenied("Unapproved staged Git paths denied")
                self._git(path, "commit", "-m", f"Native artifact {task_id} {attempt_id}")
                sha = self._git(path, "rev-parse", "--verify", "HEAD").strip().decode("ascii")
                if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
                    raise ToolPolicyDenied("Invalid Git commit identity")
                # Detached worktree commits are garbage-collected after their
                # worktrees disappear. Preserve immutable attempt evidence
                # under an operator-controlled ref with create-if-absent CAS.
                ref = f"refs/maw/attempts/{task_id}-{attempt_id}"
                self._git(
                    self.repository, "update-ref", ref, sha, "0" * len(sha),
                )
                ledger.finalize(fence.execution_scope, "git-commit-v1", ok=True)
                return GitArtifact(sha, paths)
            except Exception:
                # Git may already have committed. Never mark ambiguous
                # failures as safe to retry; CLAIMED is for reconciliation.
                raise
