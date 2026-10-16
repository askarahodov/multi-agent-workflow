"""Trusted, exact-argv command boundary; never parse model-supplied shell strings.

This is a narrow #20 stage, NOT a general shell/Git sandbox. Trusted control
plane provisions an immutable set of exact command tuples and an immutable
executable mapping. No model input may select executable paths or environment.
HTTP and arbitrary Git actions remain disabled until separately vetted.
"""
from __future__ import annotations

import os
import re
import selectors
import signal
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .errors import ToolPolicyDenied
from .tool_policy import ToolPolicyEngine

_SAFE_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_FORBIDDEN = {"hermes", "codex", "claude", "aider", "openclaw", "opencode"}


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int
    output: str


class TrustedCommandExecutor:
    """Exact approved argv only; no shell expansion, PATH lookup or overrides.

    The workspace must be a trusted, non-symlinked directory in a sandbox
    without access to secrets, host mounts, or the Docker socket. A subprocess
    boundary by itself is NOT a security sandbox.
    """

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        permissions: Mapping[str, list[str]],
        *,
        executables: Mapping[str, str],
        approved_argv: Mapping[str, Sequence[tuple[str, ...]]],
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65_536,
    ) -> None:
        if os.name != "posix":
            raise ToolPolicyDenied("POSIX command sandbox required")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 1_048_576:
            raise ValueError("Invalid command output limit")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
            raise ValueError("Invalid command timeout")
        root = Path(workspace)
        if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
            raise ToolPolicyDenied("Untrusted workspace alias")
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise ToolPolicyDenied("Workspace must be a directory")
        if set(executables) != set(approved_argv):
            raise ValueError("Command allowlists must have pinned executables")
        validated: dict[str, tuple[tuple[str, ...], ...]] = {}
        for name, commands in approved_argv.items():
            if not _SAFE_NAME.fullmatch(name) or name in _FORBIDDEN:
                raise ToolPolicyDenied("Unapproved native command")
            binary = executables[name]
            if not isinstance(binary, str) or not os.path.isabs(binary):
                raise ToolPolicyDenied("Commands require absolute executable paths")
            binary_path = Path(binary)
            if binary_path.is_symlink() or not binary_path.is_file():
                raise ToolPolicyDenied("Command executable must be a regular pinned file")
            if not commands or any(
                not isinstance(argv, tuple) or not argv
                or any(type(arg) is not str or not arg or "\x00" in arg for arg in argv)
                for argv in commands
            ):
                raise ToolPolicyDenied("Malformed exact command allowlist")
            # Reject configuration that would allow known programmatic overrides.
            if name == "git" and any(
                argv[0] not in ("status", "rev-parse")
                or argv not in (("status", "--porcelain=v1", "--untracked-files=no"),
                                ("rev-parse", "--is-inside-work-tree"))
                for argv in commands
            ):
                raise ToolPolicyDenied("Only two read-only Git probes are supported")
            validated[name] = tuple(commands)
        self.workspace = str(resolved)
        self.permissions = dict(permissions)
        self.executables = dict(executables)
        self.approved_argv = validated
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def execute(self, name: str, argv: Sequence[str]) -> CommandOutcome:
        """Authorize exact command before creating a child process."""
        if not isinstance(name, str) or name not in self.approved_argv:
            raise ToolPolicyDenied("Unknown native executable")
        if not isinstance(argv, (tuple, list)) or type(argv) is list and not argv:
            raise ToolPolicyDenied("Malformed command arguments")
        if any(type(arg) is not str for arg in argv):
            raise ToolPolicyDenied("Malformed command arguments")
        command = tuple(argv)
        if command not in self.approved_argv[name]:
            raise ToolPolicyDenied("Command arguments not allowlisted")
        kind = "git" if name == "git" else "shell"
        # Deliberately use the full argv tuple for policy matching; never
        # grant authority based only on the executable basename.
        ToolPolicyEngine.enforce(self.permissions, kind, " ".join((name, *command)))
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_VALUE_1": "/dev/null",
            "GIT_CONFIG_KEY_2": "core.pager",
            "GIT_CONFIG_VALUE_2": "cat",
        }
        child = None
        chunks: list[bytes] = []
        remaining = self.max_output_bytes
        deadline = time.monotonic() + self.timeout_seconds
        try:
            child = subprocess.Popen(
                [self.executables[name], *command], cwd=self.workspace,
                env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                shell=False, start_new_session=True,
            )
            assert child.stdout is not None
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    wait = deadline - time.monotonic()
                    if wait <= 0:
                        raise ToolPolicyDenied("Native command timeout")
                    if not selector.select(wait):
                        raise ToolPolicyDenied("Native command timeout")
                    data = os.read(child.stdout.fileno(), min(8192, remaining + 1))
                    if not data:
                        break
                    if len(data) > remaining:
                        raise ToolPolicyDenied("Command output limit exceeded")
                    chunks.append(data)
                    remaining -= len(data)
            if child.wait(timeout=max(0.001, deadline - time.monotonic())) is None:
                raise ToolPolicyDenied("Native command timeout")
            try:
                output = b"".join(chunks).decode("utf-8")
            except UnicodeDecodeError:
                raise ToolPolicyDenied("Non-text command output denied") from None
            return CommandOutcome(child.returncode, output)
        except (OSError, subprocess.TimeoutExpired):
            raise ToolPolicyDenied("Native command execution unavailable") from None
        finally:
            if child is not None:
                if child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait()

