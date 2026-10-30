"""Explicit authenticated TLS Quality Gates entrypoint for native QA receipts.

This is operator-controlled single-tenant local infrastructure; it is not an
OS sandbox for executing arbitrary untrusted test programs.
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path

from shared.auth_middleware import install_access_log_redaction

install_access_log_redaction()


def _private_key_file(value: str) -> str:
    if not value or not Path(value).is_absolute():
        raise ValueError("Absolute private QA key required")
    p = Path(value)
    if p.is_symlink():
        raise ValueError("QA key symlink rejected")
    st = os.lstat(p)
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_mode & 0o077
            or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())):
        raise ValueError("QA key must be private, regular and service-owned")
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        checked = os.fstat(fd)
        if (checked.st_dev, checked.st_ino) != (st.st_dev, st.st_ino):
            raise ValueError("QA key changed during read")
        raw = os.read(fd, 129)
    finally:
        os.close(fd)
    if not 32 <= len(raw) <= 128 or b"\n" in raw or b"\r" in raw:
        raise ValueError("QA key length invalid")
    return raw.decode("ascii")


def config_from_env(env: dict[str, str] | None = None):
    e = os.environ if env is None else env
    if e.get("MAW_SECURE_QG_ENABLED") != "1" or e.get("AUTH_ENABLED") != "true":
        raise ValueError("Signed QA requires explicit authenticated opt-in")
    if any(e.get(k) for k in ("ADMIN_API_KEYS", "WRITE_API_KEYS",
                              "READ_API_KEYS", "QG_QA_ATTESTATION_KEY")):
        raise ValueError("Ambient QA API/signing credentials denied")
    try:
        admin_path = e["MAW_QG_ADMIN_KEY_FILE"]
        signature_path = e["MAW_QG_SIGNING_KEY_FILE"]
        dbpath = e["MAW_QG_DATABASE_PATH"]
        cert = e["QG_TLS_CERT_FILE"]
        tls_key = e["QG_TLS_KEY_FILE"]
        evidence = e["QG_EVIDENCE_ROOT"]
        artifact = e["QG_ARTIFACT_ROOT"]
    except KeyError:
        raise ValueError("Signed QA private configuration incomplete") from None
    if admin_path == signature_path:
        raise ValueError("Distinct QA admin and signer key files required")
    admin = _private_key_file(admin_path)
    signing = _private_key_file(signature_path)
    if admin == signing:
        raise ValueError("QA signing and admin keys must differ")
    for raw in (dbpath, cert, tls_key, evidence, artifact):
        p = Path(raw)
        if not p.is_absolute() or p.is_symlink() or ".." in p.parts:
            raise ValueError("Signed QA paths must be absolute and unlinked")
    for directory in (Path(dbpath).parent, Path(evidence), Path(artifact)):
        if not directory.is_dir() or directory.stat().st_mode & 0o077:
            raise ValueError("Signed QA state directory must be private")
    if not Path(cert).is_file() or not Path(tls_key).is_file():
        raise ValueError("Signed QA TLS files required")
    tls_stat = os.lstat(tls_key)
    if (not stat.S_ISREG(tls_stat.st_mode) or tls_stat.st_nlink != 1
            or tls_stat.st_mode & 0o077
            or (hasattr(os, "geteuid") and tls_stat.st_uid != os.geteuid())):
        raise ValueError("Private TLS key required")
    return admin, signing, dbpath, cert, tls_key, evidence, artifact


def main() -> int:
    try:
        admin, signing, dbpath, cert, tls_key, evidence, artifact = config_from_env()
        # Import auth after installing only this server's ADMIN identity.
        os.environ["ADMIN_API_KEYS"] = admin
        from .api import build_app
        from .config import Settings
        from .db import build_engine, build_session_factory, create_all
        settings = Settings(
            evidence_root=Path(evidence), artifact_root=Path(artifact),
            qa_attestation_key=signing, cert_file=cert, key_file=tls_key,
        )
        engine = build_engine(f"sqlite+aiosqlite:///{dbpath}")

        async def prepare():
            await create_all(engine)
        asyncio.run(prepare())
        app = build_app(settings, sf=build_session_factory(engine))
        os.environ.pop("ADMIN_API_KEYS", None)
        import uvicorn
        uvicorn.run(
            app, host="0.0.0.0", port=9444, ssl_certfile=cert,
            ssl_keyfile=tls_key, proxy_headers=False, server_header=False,
        )
        return 0
    except (ValueError, OSError, UnicodeError, KeyError, RuntimeError):
        print("Signed QA FAIL_CLOSED: check operator state", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
