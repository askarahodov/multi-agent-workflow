"""Opt-in Docker boundary for operator-owned QA commands.

Not wired to signed QA yet. The caller must provide an already verified,
operator-controlled checkout and an absolute, pinned local image ID.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
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
    # Never allow this Docker-launching helper to run in a credential-bearing
    # QA signer/admin process. A separate no-secret launcher is required.
    credential_markers = (
        "QG_QA_ATTESTATION_KEY", "MAW_QG_SIGNING_KEY_FILE",
        "MAW_ORCH_QA_SIGNING_KEY_FILE", "MAW_QG_ADMIN_KEY_FILE",
        "MAW_QA_ORCH_ADMIN_KEY_FILE", "MAW_QA_SERVICE_ADMIN_KEY_FILE",
        "ADMIN_API_KEYS", "OPENROUTER_API_KEY",
    )
    if any(name in os.environ for name in credential_markers):
        raise SandboxError("QA Docker execution denied in credential-bearing process")
    if not _IMAGE.fullmatch(image_id):
        raise SandboxError("A pinned image digest is required")
    if not argv or any(type(a) is not str or not a or "\x00" in a for a in argv):
        raise SandboxError("Explicit nonempty argv required")
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise SandboxError("Invalid sandbox deadline")
    path = Path(checkout)
    if (not path.is_absolute() or not path.is_dir()
            or any(part.is_symlink() for part in (path, *path.parents))
            or any(c in str(path) for c in (",", "\n", "\r"))):
        raise SandboxError("Verified absolute checkout required")
    if not Path(docker).is_absolute():
        raise SandboxError("Absolute Docker executable required")
    name = "maw-qa-" + uuid.uuid4().hex
    cmd = [
        docker, "run", "--pull=never", "--name", name, "--rm", "--network=none", "--read-only",
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
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills the CLI process, not the container in dockerd.
        # Remove the uniquely named container explicitly before returning.
        try:
            removed = subprocess.run(
                [docker, "rm", "--force", name], shell=False,
                stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=15, check=False,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired) as cleanup_exc:
            raise SandboxError("Sandbox cleanup failed; operator intervention required") from cleanup_exc
        if removed.returncode != 0:
            raise SandboxError("Sandbox cleanup not confirmed; operator intervention required") from exc
        raise SandboxError("Sandbox execution timed out and container removed") from exc
    except OSError as exc:
        raise SandboxError("Sandbox execution failed closed") from exc
