"""Isolated process entrypoint for one bounded pinned HTTPS GET.

Only TrustedHTTPSExecutor launches this module. Input is trusted control-plane
configuration; output is strict bounded JSON with no upstream error detail.
"""
from __future__ import annotations

import base64
import json
import signal
import sys
from pathlib import Path

# In Python isolated mode (-I), trust only this script's own fixed package root.
# Never import from the process cwd, PYTHONPATH or an untrusted workspace.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_management.trusted_https import TrustedHTTPSExecutor


def _timeout(_signal, _frame):
    raise TimeoutError("HTTPS deadline")


def main() -> int:
    try:
        request = json.load(sys.stdin)
        timeout = float(request["timeout_seconds"])
        signal.signal(signal.SIGALRM, _timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            executor = TrustedHTTPSExecutor(
                request["permissions"],
                allowed_targets={k: tuple(v) for k, v in request["allowed_targets"].items()},
                timeout_seconds=timeout,
                max_response_bytes=request["max_response_bytes"],
            )
            result = executor.get(request["url"])
            print(json.dumps({
                "ok": True, "status": result.status,
                "body": base64.b64encode(result.content).decode("ascii"),
            }))
            return 0
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    except Exception:
        # Never leak provider response bodies, URLs or network internals.
        print('{"ok":false}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
