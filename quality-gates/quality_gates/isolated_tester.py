"""Opt-in Docker boundary for operator-owned QA commands.

Not wired to signed QA yet. The caller must provide an already verified,
operator-controlled checkout and an absolute, pinned local image ID.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class SandboxError(RuntimeError):
    """An isolated test cannot be safely executed."""


def isolated_test(
    argv: tuple[str, ...],
    checkout: Path,
    image_id: str,
    *,
    timeout: int = 120,
    docker: str = "/usr/bin/docker",
) -> subprocess.CompletedProcess[str]:
    if not _IMAGE.fullmatch(image_id):
        raise SandboxError("A pinned image digest is required")
    if not argv or any(type(a) is not str or not a or "\x00" in a for a in argv):
        raise SandboxError("Explicit nonempty argv required")
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise SandboxError("Invalid sandbox deadline")
    path = Path(checkout)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise SandboxError("Verified absolute checkout required")
    if not Path(docker).is_absolute():
        raise SandboxError("Absolute Docker executable required")
    cmd = [
        docker, "run", "--rm", "--network=none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=512m", "--cpus=1",
        "--user=65534:65534", "--mount",
        f"type=bind,src={path},dst=/src,readonly",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--workdir=/src", "--env=HOME=/tmp", "--env=PYTHONNOUSERSITE=1",
        image_id, *argv,
    ]
    try:
        return subprocess.run(
            cmd, shell=False, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxError("Sandbox execution failed closed") from exc
