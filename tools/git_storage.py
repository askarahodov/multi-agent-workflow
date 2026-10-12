"""Git storage integration (task item (e)).

:class:`GitStorage` is a small, safe wrapper around `git` that the platform and
its agents use to persist artifacts to a git repository: stage files, commit,
and inspect status/diff/log. It complements the git *tools* in
:mod:`tools.registry.git` with a convenience service-level facade.

Safety properties:
* ``push`` is never offered here — releasing to a remote is an explicit,
  human-gated action out of scope for agent storage.
* Subcommands are fixed; there is no free-form command string.
* Running under ``GIT_TERMINAL_PROMPT=0`` prevents interactive credential
  prompts, and a timeout bounds every call.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .resilience import OperationTimeout


class GitStorageError(Exception):
    """Base class for git-storage errors."""


@dataclass
class CommitResult:
    """The outcome of a successful commit."""

    commit_hash: str
    short_hash: str
    message: str
    changed_files: list[str]

    def to_dict(self) -> dict:
        return {
            "commit_hash": self.commit_hash,
            "short_hash": self.short_hash,
            "message": self.message,
            "changed_files": self.changed_files,
        }


class GitStorage:
    """Filesystem-scoped git persistence facade."""

    def __init__(
        self,
        repo_root: str | os.PathLike,
        *,
        timeout_s: float = 20.0,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.timeout_s = timeout_s
        self.author_name = author_name
        self.author_email = author_email

    # -- introspection --------------------------------------------------------
    def is_repo(self) -> bool:
        return (self.repo_root / ".git").exists() or self._git(["rev-parse", "--is-inside-work-tree"], check=False).returncode == 0

    def status(self) -> list[dict]:
        """Porcelain status: list of ``{path, index, worktree}`` tuples."""
        out = self._git(["status", "--porcelain=v1"]).stdout
        rows = []
        for line in out.splitlines():
            if len(line) < 3:
                continue
            rows.append({"path": line[3:], "index": line[0], "worktree": line[1]})
        return rows

    def dirty(self) -> bool:
        out = self._git(["status", "--porcelain=v1"]).stdout
        return bool(out.strip())

    def diff(self, *, stat: bool = False) -> str:
        argv = ["diff", "--stat"] if stat else ["diff"]
        return self._git(argv).stdout

    def log(self, max_entries: int = 10) -> list[str]:
        n = min(max(int(max_entries), 1), 200)
        out = self._git(["log", "--oneline", "-n", str(n)]).stdout
        return [ln for ln in out.splitlines() if ln.strip()]

    def head_sha(self) -> str | None:
        result = self._git(["rev-parse", "HEAD"], check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    # -- mutations -------------------------------------------------------------
    def add(self, paths: list[str] | str) -> None:
        if isinstance(paths, str):
            paths = [paths]
        from .resilience import retry

        retry(lambda: self._git(["add", "--", *paths], check=True), max_attempts=3, base_delay_s=0.2, max_delay_s=1.0)

    def commit(self, message: str, *, paths: list[str] | None = None, allow_empty: bool = False) -> CommitResult:
        if not message or not message.strip():
            raise GitStorageError("commit message is required")
        if paths:
            self.add(paths)
        # The set of files that will actually be committed (index moves/adds)
        # captured *after* any explicit path add.
        committed_paths = [p["path"] for p in self.status() if p["index"] in ("M", "A")]
        before = self.head_sha()
        argv = ["commit", "-m", message]
        if allow_empty:
            argv.append("--allow-empty")
        env = dict(os.environ)
        if self.author_name or self.author_email:
            env["GIT_AUTHOR_NAME"] = self.author_name or "agent"
            env["GIT_AUTHOR_EMAIL"] = self.author_email or "agent@local"
            env["GIT_COMMITTER_NAME"] = self.author_name or "agent"
            env["GIT_COMMITTER_EMAIL"] = self.author_email or "agent@local"
        result = self._git(argv, env=env, check=True)
        after = self.head_sha()
        if after is None:
            raise GitStorageError("commit produced no reachable HEAD")
        if after == before:
            raise GitStorageError("commit produced no change")
        return CommitResult(
            commit_hash=after,
            short_hash=after[:8],
            message=message,
            changed_files=committed_paths,
        )

    # -- plumbing ----------------------------------------------------------------
    def _git(self, argv: list[str], *, check: bool = True, env: dict | None = None):
        from types import SimpleNamespace

        base_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        if env:
            base_env.update(env)
        try:
            proc = subprocess.run(
                ["git", *argv],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                env=base_env,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise OperationTimeout(f"git {' '.join(argv)} timed out", operation="git", timeout_s=self.timeout_s) from exc
        except OSError as exc:
            raise GitStorageError(f"git unavailable: {exc}") from exc
        if check and proc.returncode != 0:
            raise GitStorageError(f"git {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}")
        return SimpleNamespace(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)