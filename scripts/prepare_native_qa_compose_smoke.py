"""Build disposable non-provider TLS/Git/SQLite fixtures for secure QA Compose CI.

Only run from an ephemeral trusted CI runner. Never writes secrets to stdout,
commits, docker inspect environment or product source. Root is required only
to chown bind mounts to the distinct fixed container service UIDs.
"""
from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path


def checked(*argv: str) -> None:
    subprocess.run(argv, check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=30)


def private_dir(path: Path, uid: int) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chown(path, uid, uid)
    path.chmod(0o700)


def secret_file(path: Path, text: str, uid: int) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("Refusing to overwrite private QA fixture")
    path.write_text(text, encoding="ascii")
    path.chmod(0o600)
    os.chown(path, uid, uid)


def certificate(root: Path, name: str, uid: int, key: Path) -> Path:
    output = root / "certs" / f"{name}.crt"
    checked(
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-nodes", "-days", "1", "-sha256",
        "-subj", f"/CN={name}",
        "-addext", f"subjectAltName=DNS:{name}",
        "-keyout", str(key), "-out", str(output),
    )
    os.chown(key, uid, uid)
    key.chmod(0o600)
    output.chmod(0o644)
    return output


def prepare(root: Path) -> None:
    if root.exists():
        raise ValueError("QA fixture root must be new")
    root.mkdir(parents=True, mode=0o755)
    root.chmod(0o755)
    for suffix, uid in (
        ("keys-control", 10002), ("keys-qa", 10003),
        ("control", 10002), ("qg-data", 10003),
        ("qg-evidence", 10003), ("qg-artifacts", 10003),
        ("git", 10003), ("worktrees", 10003),
    ):
        private_dir(root / suffix, uid)
    (root / "certs").mkdir(mode=0o755)
    k2, k3 = root / "keys-control", root / "keys-qa"

    worker = secrets.token_urlsafe(40)
    orch_admin = secrets.token_urlsafe(40)
    qg_admin = secrets.token_urlsafe(40)
    signer = secrets.token_urlsafe(40)
    secret_file(k2 / "worker.key", worker, 10002)
    secret_file(k2 / "orch-admin.key", orch_admin, 10002)
    secret_file(k3 / "orch-admin.key", orch_admin, 10003)
    secret_file(k3 / "qg-admin.key", qg_admin, 10003)
    secret_file(k2 / "signing.key", signer, 10002)
    secret_file(k3 / "signing.key", signer, 10003)
    orch_cert = certificate(root, "secure-orchestration", 10002, k2 / "tls.key")
    qa_cert = certificate(root, "secure-quality-gates", 10003, k3 / "tls.key")

    db = root / "control" / "orchestration.db"
    with sqlite3.connect(db):
        pass
    os.chown(db, 10002, 10002)
    db.chmod(0o600)

    git = root / "git"
    checked("git", "-C", str(git), "init", "-q")
    (git / "pyproject.toml").write_text(
        "[project]\nname='qa-tls-smoke'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (git / "README.md").write_text("# Isolated QA fixture\n", encoding="utf-8")
    checked("git", "-C", str(git), "add", ".")
    checked("git", "-C", str(git), "-c", "user.name=QA Fixture",
            "-c", "user.email=qa@example.invalid",
            "commit", "-qm", "Offline QA fixture")
    for directory, subdirs, files in os.walk(git):
        for name in subdirs + files:
            os.chown(Path(directory) / name, 10003, 10003)

    files = {
        "MAW_CONTROL_HOST_DIR": root / "control",
        "MAW_ORCH_API_KEY_HOST_FILE": k2 / "worker.key",
        "MAW_ORCH_TLS_KEY_HOST_FILE": k2 / "tls.key",
        "MAW_ORCH_TLS_CERT_HOST_FILE": orch_cert,
        "MAW_ORCH_QA_ADMIN_HOST_FILE": k2 / "orch-admin.key",
        "MAW_ORCH_QA_SIGNING_HOST_FILE": k2 / "signing.key",
        "MAW_QA_DATA_HOST_DIR": root / "qg-data",
        "MAW_QA_EVIDENCE_HOST_DIR": root / "qg-evidence",
        "MAW_QA_ARTIFACT_HOST_DIR": root / "qg-artifacts",
        "MAW_QA_GIT_REPO_HOST_DIR": root / "git",
        "MAW_QA_WORKTREE_HOST_DIR": root / "worktrees",
        "MAW_QG_ADMIN_KEY_HOST_FILE": k3 / "qg-admin.key",
        "MAW_QG_SIGNING_KEY_HOST_FILE": k3 / "signing.key",
        "MAW_QG_TLS_KEY_HOST_FILE": k3 / "tls.key",
        "MAW_QG_TLS_CERT_HOST_FILE": qa_cert,
        "MAW_QA_CONTROL_ADMIN_HOST_FILE": k3 / "orch-admin.key",
        "MAW_QA_SERVICE_ADMIN_HOST_FILE": k3 / "qg-admin.key",
        "MAW_QA_ORCH_CA_HOST_FILE": orch_cert,
        "MAW_QA_SERVICE_CA_HOST_FILE": qa_cert,
    }
    env_file = root / "compose.env"
    env_file.write_text(
        "".join(f"{name}={path}\n" for name, path in sorted(files.items())),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    # sudo setup: only the unprivileged Docker client may read file paths.
    if "SUDO_UID" in os.environ:
        os.chown(
            env_file, int(os.environ["SUDO_UID"]),
            int(os.environ["SUDO_GID"]),
        )
    print("Secure QA fixture prepared (credential values never logged)")


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    root = Path(sys.argv[1])
    if not root.is_absolute() or root.is_symlink() or ".." in root.parts:
        print("Invalid fixture path", file=sys.stderr)
        return 3
    try:
        prepare(root)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Secure QA fixture preparation FAIL_CLOSED", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
