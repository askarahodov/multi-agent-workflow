"""Offline-only validation for the isolated trusted gateway image.

Never creates a ledger, opens orchestration SQLite, starts TLS or serves
requests. This does NOT constitute gateway deployment acceptance.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys


def _private_regular_file(value: str, *, owner: bool = True) -> None:
    if not value or not Path(value).is_absolute():
        raise ValueError("Private absolute file required")
    entry = os.lstat(value)
    if (
        not stat.S_ISREG(entry.st_mode)
        or entry.st_nlink != 1
        or entry.st_mode & 0o077
        or (owner and hasattr(os, "geteuid") and entry.st_uid != os.geteuid())
    ):
        raise ValueError("Private file permissions invalid")


def validate_local_config(env: dict[str, str] | None = None) -> None:
    settings = dict(os.environ if env is None else env)
    if settings.get("MAW_TRUSTED_GATEWAY_ENABLED") != "1":
        raise ValueError("Gateway requires explicit opt-in")
    required = (
        "MAW_GATEWAY_WORKSPACE_ROOT",
        "MAW_GATEWAY_ORCHESTRATION_SQLITE",
        "MAW_GATEWAY_LEDGER_SQLITE",
        "MAW_GATEWAY_KEY_FILE",
        "MAW_GATEWAY_TLS_CERT_FILE",
        "MAW_GATEWAY_TLS_KEY_FILE",
    )
    if any(not settings.get(key) for key in required):
        raise ValueError("Gateway settings incomplete")
    root = Path(settings["MAW_GATEWAY_WORKSPACE_ROOT"])
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid workspace root")
    if not (root / "src").is_dir() or not (root / "out").is_dir():
        raise ValueError("Workspace layout incomplete")
    db = Path(settings["MAW_GATEWAY_ORCHESTRATION_SQLITE"])
    ledger = Path(settings["MAW_GATEWAY_LEDGER_SQLITE"])
    secret = Path(settings["MAW_GATEWAY_KEY_FILE"])
    if any(not path.is_absolute() for path in (db, ledger, secret)):
        raise ValueError("Trusted paths must be absolute")
    if any(path == root or root in path.parents for path in (db, ledger, secret)):
        raise ValueError("Control files cannot be in workspace")
    if len({str(db), str(ledger), str(secret)}) != 3:
        raise ValueError("Control file paths must be distinct")
    _private_regular_file(str(db), owner=False)
    _private_regular_file(str(secret))
    _private_regular_file(settings["MAW_GATEWAY_TLS_KEY_FILE"])
    cert = Path(settings["MAW_GATEWAY_TLS_CERT_FILE"])
    if not cert.is_absolute() or cert.is_symlink() or not cert.is_file():
        raise ValueError("TLS certificate required")
    if not ledger.parent.is_dir() or ledger.is_symlink():
        raise ValueError("Trusted ledger parent required")
    # No ledger writes here. Factory will verify ancestors and ownership too.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline gateway validation only")
    parser.add_argument("command", choices=("preflight",))
    parser.parse_args(argv)
    try:
        validate_local_config()
    except (OSError, ValueError, OverflowError):
        print("Trusted gateway preflight FAILED: private settings required", file=sys.stderr)
        return 2
    print("Trusted gateway local preflight OK; TLS and fencing NOT tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
