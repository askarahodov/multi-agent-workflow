"""Check the actual checkout against GitHub event identity before/after make check."""
from __future__ import annotations

import os
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}")


def validate(event, expected, head, base, commit_line):
    if not SHA.fullmatch(expected) or expected == "0" * 40:
        raise ValueError("Invalid GitHub checkout SHA")
    parts = commit_line.split()
    if not parts or parts[0] != expected:
        raise ValueError("Checkout does not match GitHub SHA")
    if event == "pull_request":
        if not all(SHA.fullmatch(x) and x != "0" * 40 for x in (head, base)):
            raise ValueError("Missing exact PR provenance")
        if parts[1:] != [base, head]:
            raise ValueError("Checkout is not the exact PR base/head merge")
    elif event not in {"push", "workflow_dispatch"} or head or base:
        raise ValueError("Unsupported checkpoint event or PR identity")
    return parts[0]


def main():
    try:
        line = subprocess.check_output(
            ["git", "rev-list", "--parents", "-n", "1", "HEAD"], text=True,
        )
        sha = validate(
            os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("GITHUB_SHA", ""),
            os.environ.get("PR_HEAD", ""),
            os.environ.get("PR_BASE", ""),
            line,
        )
        print("Verified checkpoint checkout:", sha)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("Checkpoint provenance failed:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
