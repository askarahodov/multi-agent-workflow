#!/usr/bin/env python3
"""Read-only first-run API preflight through the same-origin frontend proxy.

No credentials, request bodies, database writes, or paid provider requests.
Do not print response bodies: error payloads may contain secrets or stack traces.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CHECKS = (
    ("orchestration", "/api/v1/projects", "list"),
    ("agent-management", "/api/v1/providers", "page"),
    ("agent-management", "/api/v1/model-profiles", "page"),
    ("agent-management", "/api/v1/agents/definitions", "page"),
    ("agent-management", "/api/v1/tool-policies", "page"),
)


def validate_base_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "localhost", "127.0.0.1", "::1"
    ) or parsed.username or parsed.password or parsed.path not in ("", "/") or (
        parsed.query or parsed.fragment
    ):
        raise ValueError("base URL must be a plain loopback http(s) origin without credentials or paths")
    # Ensure invalid ports raise now, not while making requests.
    _ = parsed.port
    return url.rstrip("/")


def probe(base_url: str, *, opener=urlopen) -> tuple[bool, list[str]]:
    """Never return response bodies/URLs with credentials to callers."""
    base = validate_base_url(base_url)
    messages = []
    ok = True
    for subsystem, path, kind in CHECKS:
        request = Request(base + path, headers={"Accept": "application/json"})
        try:
            with opener(request, timeout=5) as response:
                status = response.status
                # Bound the response size; startup catalog should not be huge.
                raw = response.read(1024 * 1024 + 1)
            parsed = json.loads(raw) if status == 200 and len(raw) <= 1024 * 1024 else None
            valid = (
                isinstance(parsed, list) if kind == "list"
                else isinstance(parsed, dict) and isinstance(parsed.get("items"), list)
            )
            result = "PASS" if status == 200 and valid else f"FAIL HTTP {status} / invalid JSON envelope"
        except HTTPError as exc:
            result = f"FAIL HTTP {exc.code}"
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            result = "FAIL unavailable or invalid JSON"
        if not result.startswith("PASS"):
            ok = False
        messages.append(f"{subsystem}: GET {path} — {result}")
    return ok, messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only onboarding API preflight (no paid calls)")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    args = parser.parse_args(argv)
    try:
        ok, messages = probe(args.base_url)
    except ValueError as exc:
        print(f"Invalid base URL: {exc}", file=sys.stderr)
        return 2
    for message in messages:
        print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
