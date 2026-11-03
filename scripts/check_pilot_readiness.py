"""Fail-closed pilot evidence validator (stdlib-only, no credentials or network).

This checks evidence metadata, NOT the veracity of a paid provider call.
The independent reviewer must validate referenced artifacts separately.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

REQUIRED = (
    "clean_compose", "browser_project_run", "live_openrouter_tool_call",
    "git_commit_verified", "contract_gate_negative",
    "independent_qa", "release_approval", "restart_persistence",
    "no_external_agent_cli", "security_signoff",
)
SHA = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN = re.compile(r"(?i)(?:sk-or-v1-|-----BEGIN .*PRIVATE KEY-----|(?:api[_-]?key|secret|token)\s*[:=]\s*[^\s,]+)")


def validate(report: dict, *, require_live: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        return ["schema_version must be 1"]
    if not SHA.fullmatch(str(report.get("commit_sha", ""))):
        errors.append("commit_sha must be a full Git commit SHA")
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return errors + ["checks must be an object"]
    for key in REQUIRED:
        entry = checks.get(key)
        if not isinstance(entry, dict):
            errors.append(f"{key}: missing check")
            continue
        status = entry.get("status")
        if status not in ("PASS", "FAIL", "BLOCKED"):
            errors.append(f"{key}: invalid status")
        if require_live and status != "PASS":
            errors.append(f"{key}: pilot not accepted ({status})")
        evidence = entry.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            errors.append(f"{key}: evidence reference required")
        elif evidence != evidence.strip() or any(ord(ch) < 32 for ch in evidence):
            errors.append(f"{key}: evidence reference must not contain surrounding whitespace or controls")
        elif "\\" in evidence:
            errors.append(f"{key}: evidence reference must use forward slashes")
        elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", evidence) or evidence.startswith("//"):
            try:
                url = urlsplit(evidence)
                if url.scheme.lower() != "https":
                    errors.append(f"{key}: evidence URL must use HTTPS")
                if not url.hostname:
                    errors.append(f"{key}: evidence URL requires a hostname")
                if url.username is not None or url.password is not None:
                    errors.append(f"{key}: evidence URL must not contain userinfo")
                if url.query or url.fragment or "?" in evidence or "#" in evidence:
                    errors.append(f"{key}: evidence URL must not contain query or fragment")
            except ValueError:
                errors.append(f"{key}: malformed evidence URL")
        elif (Path(evidence).is_absolute() or ".." in Path(evidence).parts
              or "?" in evidence or "#" in evidence):
            errors.append(f"{key}: evidence path must be repository-relative without query or fragment")
        if key in ("live_openrouter_tool_call", "independent_qa", "security_signoff"):
            if not isinstance(entry.get("reviewer"), str) or not entry["reviewer"].strip():
                errors.append(f"{key}: named reviewer required")
    def has_credential(value: object) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized in ("token", "secret", "api_key", "password", "authorization", "private_key"):
                    if item not in (None, "", "[REDACTED]"):
                        return True
                if has_credential(item):
                    return True
        elif isinstance(value, list):
            return any(has_credential(item) for item in value)
        elif isinstance(value, str):
            return FORBIDDEN.search(value) is not None
        return False

    if has_credential(report):
        errors.append("report contains apparent credential material")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON evidence report")
    parser.add_argument("--check-structure-only", action="store_true",
                        help="Validate structure without claiming live acceptance")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Pilot readiness FAIL: unreadable JSON ({type(exc).__name__})", file=sys.stderr)
        return 2
    errors = validate(report, require_live=not args.check_structure_only)
    for error in errors:
        print("Pilot readiness FAIL: " + error, file=sys.stderr)
    if errors:
        return 1
    if args.check_structure_only:
        print("Pilot evidence structure valid; LIVE ACCEPTANCE NOT VERIFIED")
    else:
        print("Pilot evidence inventory complete; independently inspect all artifacts before launch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
