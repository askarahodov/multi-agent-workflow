"""Operator-only preflight for the opt-in native leased worker.

This command does not import a provider, contact the network, start polling,
or print identities and credentials. A successful preflight is NOT proof of
reachable orchestration, trusted gateway, or complete autonomous deployment.
"""
from __future__ import annotations

import argparse
import sys

from .native_worker_bootstrap import config_from_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="maw-native-worker",
        description="Check trusted native worker local configuration without execution.",
    )
    parser.add_argument(
        "command", choices=("preflight",),
        help="preflight validates local settings; it never executes agent work",
    )
    args = parser.parse_args(argv)
    assert args.command == "preflight"
    try:
        config_from_env()
    except (ValueError, OSError, OverflowError):
        # Never print exception text: paths/contents from OS may be sensitive.
        print("Native worker preflight FAILED: check private configuration", file=sys.stderr)
        return 2
    print("Native worker local preflight OK (no connection or execution tested)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
