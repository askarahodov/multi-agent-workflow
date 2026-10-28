"""Standalone opt-in QA execution boundary (not a signed QA component).

Input is operator-owned. Never import or mount signer credentials here.
No attestation can be issued by this module.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .isolated_tester import SandboxError, isolated_test

_ALLOWED_COMMANDS: dict[str, tuple[str, ...]] = {
    "python-unit": ("python", "-m", "pytest", "-q"),
    "python-version": ("python", "--version"),
}
_CREDENTIAL_MARKERS = (
    "MAW_QG_SIGNING_KEY_FILE", "MAW_QG_ADMIN_KEY_FILE",
    "MAW_ORCH_QA_SIGNING_KEY_FILE", "MAW_QA_ORCH_ADMIN_KEY_FILE",
    "MAW_QA_SERVICE_ADMIN_KEY_FILE", "QG_QA_ATTESTATION_KEY",
    "ADMIN_API_KEYS", "OPENROUTER_API_KEY",
)


def _verify_checkout(checkout: str, commit_sha: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", commit_sha) is None:
        raise SandboxError("Expected full Git commit SHA")
    try:
        head = subprocess.run(
            ["git", "-C", checkout, "rev-parse", "--verify", "HEAD"],
            env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
            timeout=10, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", checkout, "status", "--porcelain", "--untracked-files=all"],
            env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
            timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxError("Verified Git checkout required") from exc
    if head != commit_sha or status:
        raise SandboxError("QA Git checkout SHA mismatch or dirty workspace")


def execute_operator_job(job: dict[str, object]) -> dict[str, object]:
    """Execute an operator-selected allowlisted command, never sign evidence."""
    if type(job) is not dict or set(job) != {"command_id", "checkout", "image_id", "commit_sha"}:
        raise SandboxError("Exact operator job fields required")
    if any(key in os.environ for key in _CREDENTIAL_MARKERS):
        raise SandboxError("Runner must not inherit signing or admin credentials")
    command_id, checkout, image_id = (job[k] for k in ("command_id", "checkout", "image_id"))
    if type(command_id) is not str or command_id not in _ALLOWED_COMMANDS:
        raise SandboxError("Unknown QA command identifier")
    if type(checkout) is not str or type(image_id) is not str:
        raise SandboxError("Invalid operator checkout or image ID")
    commit_sha = job["commit_sha"]
    if type(commit_sha) is not str:
        raise SandboxError("Expected full Git commit SHA")
    _verify_checkout(checkout, commit_sha)
    result = isolated_test(_ALLOWED_COMMANDS[command_id], Path(checkout), image_id)
    _verify_checkout(checkout, commit_sha)
    return {
        "schema_version": 1,
        "kind": "untrusted_qa_execution",
        "command_id": command_id,
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in no-secret QA runner")
    parser.add_argument("--job-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        # Do not parse inline untrusted JSON through a shell, and cap input size.
        if args.job_file.stat().st_size > 4096:
            raise SandboxError("Operator job too large")
        job = json.loads(args.job_file.read_text(encoding="utf-8"))
        output = execute_operator_job(job)
        print(json.dumps(output, sort_keys=True))
        return 0 if output["exit_code"] == 0 else 1
    except (SandboxError, OSError, UnicodeError, ValueError, TypeError):
        print("QA_RUNNER_FAIL_CLOSED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
