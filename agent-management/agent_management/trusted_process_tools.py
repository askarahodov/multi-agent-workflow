"""Trusted opt-in read-only process tools; never accept model-supplied argv.

This adapter is deliberately NOT enabled in NativeFilesystemDispatcher until
the complete #20 sandbox/egress design has passed security acceptance.
"""
from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ToolPolicyDenied
from .tool_policy import ToolPolicyEngine


@dataclass(frozen=True)
class ProcessToolResult:
    ok: bool
    output: str
    error_code: str | None = None


class TrustedReadOnlyProcessTools:
    """Strict fixed-argv Git status and shell directory-listing operations.

    Executables, workspace, role permissions and command variants are supplied
    by the control plane, NOT by model tool arguments.
    """

    def __init__(
        self, workspace: str | os.PathLike[str], permissions: Mapping,
        *, git_executable: str, ls_executable: str,
        max_output_bytes: int = 65536, timeout_seconds: float = 5.0,
    ) -> None:
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 65536:
            raise ValueError("Invalid process output limit")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 15:
            raise ValueError("Invalid process timeout")
        if isinstance(timeout_seconds, float):
            import math
            if not math.isfinite(timeout_seconds):
                raise ValueError("Invalid process timeout")
        root = Path(workspace)
        if root.is_symlink() or not root.is_dir():
            raise ToolPolicyDenied("Trusted workspace must be an existing real directory")
        self.workspace = root.resolve(strict=True)
        self.permissions = dict(permissions)
        self.git = self._trusted_binary(git_executable, "git")
        self.ls = self._trusted_binary(ls_executable, "ls")
        self.max_output_bytes = max_output_bytes
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _trusted_binary(path: str, basename: str) -> str:
        if not isinstance(path, str) or not os.path.isabs(path):
            raise ToolPolicyDenied("Trusted executable must use an absolute path")
        p = Path(path)
        if p.is_symlink() or p.name != basename:
            raise ToolPolicyDenied("Unexpected executable path")
        st = p.stat()
        if not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111 or st.st_mode & 0o022:
            raise ToolPolicyDenied("Executable must be regular, executable and non-writable")
        return str(p)

    def execute(self, operation: str) -> ProcessToolResult:
        if operation == "git_status":
            action, resource = "git", "status"
            command = [
                self.git, "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=/dev/null",
                "-c", "core.pager=cat",
                "status", "--porcelain=v1", "--untracked-files=no",
                "--ignore-submodules=all",
            ]
        elif operation == "shell_list":
            action, resource = "shell", "ls"
            command = [self.ls, "-A", "--", "."]
        else:
            raise ToolPolicyDenied("Unsupported native process operation")

        ToolPolicyEngine.enforce(self.permissions, action, resource)
        # No inherited GIT_* variables, interactive config, pager, SSH or
        # user-controlled PATH; Python subprocess executes a trusted absolute
        # executable with shell=False and no provider-supplied arguments.
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
        try:
            done = subprocess.run(
                command, cwd=self.workspace, env=env, shell=False,
                stdin=subprocess.DEVNULL, capture_output=True,
                timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ProcessToolResult(False, "", "PROCESS_FAILED")
        if done.returncode != 0:
            return ProcessToolResult(False, "", "PROCESS_FAILED")
        if len(done.stdout) > self.max_output_bytes:
            return ProcessToolResult(False, "", "OUTPUT_LIMIT")
        try:
            output = done.stdout.decode("utf-8", errors="strict")
        except UnicodeError:
            return ProcessToolResult(False, "", "OUTPUT_INVALID")
        return ProcessToolResult(True, output)
