"""Fail-closed, finite opt-in bootstrap for a trusted native leased worker.

No provider/model or secrets are loaded here. The trusted application must
inject a leased runner (e.g. TrustedLeasedGatewayRunner) after verifying
its isolation and gateway credentials. Importing this module has no effects.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .native_http_worker import LeasedRemoteRunner, NativeHttpWorker
from .native_worker_supervisor import NativeWorkerSupervisor, SupervisorReport


@dataclass(frozen=True, repr=False)
class NativeWorkerConfig:
    server_url: str
    api_key: str
    agent_id: str
    max_polls: int
    poll_interval_seconds: float
    max_attempts_per_poll: int
    allow_loopback_http: bool = False

    def __repr__(self) -> str:
        return "NativeWorkerConfig(<redacted>)"


def _private_key(path: str) -> str:
    if not path or not Path(path).is_absolute():
        raise ValueError("Trusted API key file must be an absolute path")
    st = os.lstat(path)  # reject symlinks before read
    import stat
    if (
        not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
        or st.st_mode & 0o077
        or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())
    ):
        raise ValueError("Trusted API key file must be private and regular")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        checked = os.fstat(fd)
        if (checked.st_dev, checked.st_ino) != (st.st_dev, st.st_ino):
            raise ValueError("API key file changed during validation")
        data = os.read(fd, 257)
    finally:
        os.close(fd)
    if not 8 <= len(data) <= 256 or b"\n" in data or b"\r" in data:
        raise ValueError("Invalid trusted API key file")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid trusted API key encoding") from exc


def config_from_env(env: Mapping[str, str] | None = None) -> NativeWorkerConfig:
    """Require explicit enablement and private on-disk credentials.

    There is no fallback to unauthenticated/legacy runner, default URL,
    ambient API key, or automatic provider invocation.
    """
    e = os.environ if env is None else env
    if e.get("MAW_NATIVE_WORKER_ENABLED") != "1":
        raise ValueError("Native worker requires explicit opt-in")
    if e.get("MAW_NATIVE_WORKER_LEASE_REQUIRED") != "1":
        raise ValueError("Native worker requires trusted attempt leases")
    try:
        config = NativeWorkerConfig(
            server_url=e["MAW_NATIVE_WORKER_SERVER_URL"],
            api_key=_private_key(e["MAW_NATIVE_WORKER_API_KEY_FILE"]),
            agent_id=e["MAW_NATIVE_WORKER_AGENT_ID"],
            max_polls=int(e["MAW_NATIVE_WORKER_MAX_POLLS"]),
            poll_interval_seconds=float(e["MAW_NATIVE_WORKER_POLL_SECONDS"]),
            max_attempts_per_poll=int(e.get("MAW_NATIVE_WORKER_BATCH_SIZE", "1")),
            allow_loopback_http=e.get("MAW_NATIVE_WORKER_DEV_LOOPBACK_HTTP") == "1",
        )
    except KeyError as exc:
        raise ValueError("Native worker configuration incomplete") from None
    # Reuse the actual production transport bounds; do not make a network call.
    async def _no_execution(*_args):
        raise RuntimeError("Unconfigured native execution forbidden")
    probe = NativeHttpWorker(
        server_url=config.server_url, api_key=config.api_key,
        agent_id=config.agent_id, leased_runner=_no_execution, require_lease=True,
        allow_loopback_http=config.allow_loopback_http,
    )
    # Constructor validation has no I/O, but client resources must be closed.
    # Avoid a persistent client during config validation by validating
    # supervisor limits separately.
    if not 1 <= config.max_polls <= 1000:
        raise ValueError("Invalid bounded poll count")
    if not 0.01 <= config.poll_interval_seconds <= 3600:
        raise ValueError("Invalid bounded poll interval")
    if not 1 <= config.max_attempts_per_poll <= 100:
        raise ValueError("Invalid bounded batch size")
    return config


async def run_trusted_worker(
    config: NativeWorkerConfig,
    *,
    leased_runner: LeasedRemoteRunner,
    stop_event: asyncio.Event,
) -> SupervisorReport:
    """One finite leased polling session. No automatic retry after a failure."""
    if not callable(leased_runner):
        raise TypeError("Trusted leased runner required")
    async with NativeHttpWorker(
        server_url=config.server_url,
        api_key=config.api_key,
        agent_id=config.agent_id,
        leased_runner=leased_runner,
        require_lease=True,
        allow_loopback_http=config.allow_loopback_http,
    ) as worker:
        return await NativeWorkerSupervisor(
            worker,
            max_polls=config.max_polls,
            poll_interval_seconds=config.poll_interval_seconds,
            max_attempts_per_poll=config.max_attempts_per_poll,
        ).run(stop_event)
