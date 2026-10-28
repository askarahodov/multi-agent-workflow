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
    create_cmd = [
        docker, "create", "--pull=never", "--name", name, "--network=none",
        "--ipc=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=64",
        "--memory=512m", "--cpus=1", "--user=65534:65534",
        "--mount", f"type=bind,src={path},dst=/src,readonly",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--workdir=/src", "--env=HOME=/tmp", "--env=PYTHONNOUSERSITE=1",
        image_id, *argv,
    ]
    child_kwargs = dict(
        shell=False, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, check=False, env={"PATH": "/usr/bin:/bin"},
    )

    def force_remove() -> None:
        try:
            removed = subprocess.run(
                [docker, "rm", "--force", name], timeout=15, **child_kwargs
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError("Sandbox cleanup failed; operator intervention required") from exc
        if removed.returncode != 0:
            raise SandboxError("Sandbox cleanup not confirmed; operator intervention required")

    # The daemon must finish creating the container before we can start it.
    # No combined docker-run request can create a container after the CLI has
    # already timed out and its subsequent rm has raced the daemon.
    try:
        created = subprocess.run(create_cmd, timeout=timeout, **child_kwargs)
    except subprocess.TimeoutExpired as exc:
        # A create timeout has no trustworthy lifecycle state. Removal is
        # best-effort; even a successful rm cannot prove no late creation.
        try:
            force_remove()
        except SandboxError:
            pass
        raise SandboxError("Sandbox create timed out; operator intervention required") from exc
    except OSError as exc:
        raise SandboxError("Sandbox create failed closed") from exc
    if created.returncode != 0:
        return subprocess.CompletedProcess(
            create_cmd, created.returncode, created.stdout, created.stderr,
        )

    try:
        started = subprocess.run(
            [docker, "start", "--attach", name], timeout=timeout,
            **child_kwargs,
        )
        # The attach CLI's return code is not proof of the container's
        # status; wait supplies the daemon-observed container exit code.
        waited = subprocess.run([docker, "wait", name], timeout=15, **child_kwargs)
        if waited.returncode != 0 or not re.fullmatch(
            r"[0-9]{1,3}", waited.stdout.strip()
        ):
            raise SandboxError("Sandbox exit status unavailable")
        exit_code = int(waited.stdout.strip())
        if exit_code > 255:
            raise SandboxError("Invalid sandbox exit status")
        return subprocess.CompletedProcess(
            create_cmd, exit_code, started.stdout, started.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError("Sandbox execution timed out and container removed") from exc
    except OSError as exc:
        raise SandboxError("Sandbox execution failed closed") from exc
    finally:
        # If the daemon confirmed create, removal must be attempted on every
        # execution path. Cleanup failure supersedes a possible test success.
        force_remove()
