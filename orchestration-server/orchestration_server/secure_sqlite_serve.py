"""Explicit secure SQLite orchestration entrypoint for the trusted gateway.

Import auth middleware only AFTER installing a protected operator key file.
Never starts a development server, creates state, or opens a port on import.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def _private_key(path: str) -> str:
    if not path or not Path(path).is_absolute():
        raise ValueError("Absolute API key path required")
    entry = os.lstat(path)
    if (
        not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1
        or entry.st_mode & 0o077
        or (hasattr(os, "geteuid") and entry.st_uid != os.geteuid())
    ):
        raise ValueError("Private API key required")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        checked = os.fstat(fd)
        if (checked.st_dev, checked.st_ino) != (entry.st_dev, entry.st_ino):
            raise ValueError("API key changed")
        data = os.read(fd, 129)
    finally:
        os.close(fd)
    if not 32 <= len(data) <= 128 or b"\n" in data or b"\r" in data:
        raise ValueError("Invalid key length")
    return data.decode("ascii")


def config_from_env(env: dict[str, str] | None = None) -> tuple[str, str, str, str]:
    e = os.environ if env is None else env
    if e.get("MAW_SECURE_ORCH_ENABLED") != "1":
        raise ValueError("Explicit secure orchestration opt-in required")
    if e.get("ORCH_ATTEMPT_LEASE_ENABLED") != "1":
        raise ValueError("Attempt lease fencing required")
    if e.get("AUTH_ENABLED") != "true":
        raise ValueError("Authentication required")
    if any(e.get(k) for k in ("ADMIN_API_KEYS", "WRITE_API_KEYS", "READ_API_KEYS")):
        raise ValueError("Ambient API key values forbidden")
    try:
        database_url = e["ORCH_DATABASE_URL"]
        cert = e["ORCH_TLS_CERT_FILE"]
        tls_key = e["ORCH_TLS_KEY_FILE"]
        api_key = _private_key(e["MAW_ORCH_API_KEY_FILE"])
    except KeyError:
        raise ValueError("Secure orchestration configuration incomplete") from None
    # This fenced gateway supports only co-located SQLite, NOT PostgreSQL.
    prefix = "sqlite+aiosqlite:////"
    if not database_url.startswith(prefix) or "?" in database_url or "#" in database_url:
        raise ValueError("Absolute SQLite URL required")
    dbpath = "/" + database_url[len(prefix):]
    if not Path(dbpath).is_absolute() or ".." in Path(dbpath).parts:
        raise ValueError("Invalid SQLite path")
    if any(not Path(p).is_absolute() or Path(p).is_symlink() for p in (cert, tls_key)):
        raise ValueError("Absolute non-symlink TLS files required")
    for p in (dbpath, cert, tls_key):
        if not Path(p).is_file():
            raise ValueError("Database and TLS files required")
    st = os.lstat(tls_key)
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        raise ValueError("Private TLS key required")
    if not Path(dbpath).parent.is_dir():
        raise ValueError("Private SQLite parent directory required")
    return api_key, database_url, cert, tls_key


def main() -> int:
    try:
        key, _, cert, tls_key = config_from_env()
        # Import below deliberately: shared.auth_middleware snapshots env at import.
        os.environ["WRITE_API_KEYS"] = key
        from .api import build_app
        from .config import get_settings
        import uvicorn
        uvicorn.run(
            build_app(get_settings()), host="0.0.0.0", port=8443,
            ssl_certfile=cert, ssl_keyfile=tls_key,
            proxy_headers=False, server_header=False,
        )
    except (ValueError, OSError, RuntimeError, UnicodeError, KeyError):
        print("Secure orchestration FAIL_CLOSED: check protected state", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
