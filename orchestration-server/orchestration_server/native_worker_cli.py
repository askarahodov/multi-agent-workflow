"""Explicit finite native worker command; no implicit background execution."""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from .native_worker_bootstrap import config_from_env


def dispatch_limits(env: dict[str, str]) -> tuple[int, int]:
    try:
        sessions = int(env.get('MAW_NATIVE_DISPATCH_MAX_SESSIONS', '1'))
        completions = int(env.get('MAW_NATIVE_DISPATCH_MAX_COMPLETIONS', '1'))
    except (ValueError, OverflowError):
        raise ValueError('Invalid native dispatch budget') from None
    if not 1 <= sessions <= 100 or not 1 <= completions <= 100:
        raise ValueError('Native dispatch budget outside bounds')
    return sessions, completions


async def run_worker(*, dispatch: bool = False) -> int:
    """Only explicit run connects a fixed provider to a leased gateway."""
    from .native_worker_bootstrap import run_trusted_worker, run_trusted_dispatch
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
        if dispatch:
            max_sessions, max_completions = dispatch_limits(dict(os.environ))
            report = await run_trusted_dispatch(
                worker_config, leased_runner=runner, stop_event=stop,
                max_sessions=max_sessions, max_completions=max_completions,
            )
        else:
            report = await run_trusted_worker(
                worker_config, leased_runner=runner, stop_event=stop,
            )
        # IDs, prompts, URLs and credentials must never reach stdout.
        print(f"Native worker stopped: {report.reason}")
        return 3 if report.reason == "FAIL_CLOSED" else 0
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
        "command", choices=("preflight", "run", "dispatch"),
        help="preflight verifies config; run is one session; dispatch runs bounded automatic polling",
    )
    args = parser.parse_args(argv)
    if args.command == "preflight":
        try:
            from .native_worker_wiring import trusted_runner_config_from_env
            worker = config_from_env()
            dispatch_limits(dict(os.environ))
            runner = trusted_runner_config_from_env(os.environ)
            if runner.agent_id != worker.agent_id:
                raise ValueError("Trusted worker and runner identities differ")
            if len({worker.api_key, runner.gateway_key, runner.provider_key}) != 3:
                raise ValueError("Trusted credentials must be distinct")
        except (ValueError, OSError, OverflowError, TypeError):
            print("Native worker preflight FAILED: check private configuration", file=sys.stderr)
            return 2
        print("Native worker local preflight OK (no connection or execution tested)")
        return 0

    try:
        return asyncio.run(run_worker(dispatch=args.command == "dispatch"))
    except (ValueError, OSError, RuntimeError, TypeError, OverflowError):
        # Provider exceptions can contain URLs or secrets; never echo them.
        print("Native worker stopped FAIL_CLOSED; reconcile attempts before restart", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("Native worker interrupted; reconcile in-flight attempts", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
