"""Explicit finite native worker command; no implicit background execution."""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from .native_worker_bootstrap import config_from_env


async def run_worker() -> int:
    """Only explicit run connects a fixed provider to a leased gateway."""
    from .native_worker_bootstrap import run_trusted_worker
    from .native_worker_wiring import (
        construct_trusted_runner, trusted_runner_config_from_env,
    )

    worker_config = config_from_env()
    runner_config = trusted_runner_config_from_env(os.environ)
    if runner_config.agent_id != worker_config.agent_id:
        raise ValueError("Trusted worker and runner identities differ")
    if len({worker_config.api_key, runner_config.gateway_key,
            runner_config.provider_key}) != 3:
        raise ValueError("Trusted credentials must be distinct")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    registered: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
            registered.append(signum)
        except (NotImplementedError, RuntimeError):
            # On Windows, KeyboardInterrupt is handled by asyncio.run().
            pass

    runner, provider = construct_trusted_runner(runner_config)
    try:
        report = await run_trusted_worker(
            worker_config, leased_runner=runner, stop_event=stop,
        )
        # Do not print run, task, agent IDs, outputs or credentials.
        print(f"Native worker stopped: {report.reason}")
        return 0 if report.reason in ("STOPPED", "POLL_LIMIT") else 3
    finally:
        await provider.aclose()
        for signum in registered:
            loop.remove_signal_handler(signum)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="maw-native-worker",
        description="Explicit finite trusted native worker operation.",
    )
    parser.add_argument(
        "command", choices=("preflight", "run"),
        help="preflight checks local worker settings; run performs bounded opt-in work",
    )
    args = parser.parse_args(argv)
    if args.command == "preflight":
        try:
            config_from_env()
        except (ValueError, OSError, OverflowError):
            print("Native worker preflight FAILED: check private configuration", file=sys.stderr)
            return 2
        print("Native worker local preflight OK (no connection or execution tested)")
        return 0

    try:
        return asyncio.run(run_worker())
    except (ValueError, OSError, RuntimeError, TypeError, OverflowError):
        # Provider exceptions can contain URLs or secrets; never echo them.
        print("Native worker stopped FAIL_CLOSED; reconcile attempts before restart", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("Native worker interrupted; reconcile in-flight attempts", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
