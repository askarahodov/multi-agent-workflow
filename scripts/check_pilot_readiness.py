"""Fail-closed pilot evidence validator (stdlib-only, no credentials or network).

This checks evidence metadata, NOT the veracity of a paid provider call.
The independent reviewer must validate referenced artifacts separately.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
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
                if url.port == 0:
                    errors.append(f"{key}: evidence URL must use a valid TCP port")
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



# The inventory schema (v1) deliberately allows remote HTTPS references for
# planning. A PASS based solely on a URL is not independently verifiable here.
# In the default CLI mode every PASS needs a locally retained, redacted file,
# an exact SHA-256 pin, and explicit operator review outside this tool.
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def _integrity_of_local_artifact(root: Path, reference: str, expected_sha: str) -> str | None:
    """Return a redacted error code or None; never include file paths/content.

    Symlinked ancestors, hard-linked files, traversal, non-regular files and
    oversized evidence are rejected. The digest protects against accidental
    replacement between collection and review; it is not proof that a model or
    independent reviewer produced the data.
    """
    parts = reference.split("/")
    if (
        not parts or any(part in ("", ".", "..") for part in parts)
        or any("\\" in part or ":" in part for part in parts)
        or reference.startswith("/") or reference.startswith("//")
        or not isinstance(expected_sha, str) or not _DIGEST.fullmatch(expected_sha)
    ):
        return "invalid local artifact path or SHA-256"
    # dir_fd, O_DIRECTORY and O_NOFOLLOW are required. On platforms that
    # cannot support race-safe traversal, refuse the full integrity gate rather
    # than claim that a pre-open path check protects against directory swaps.
    if (
        os.open not in os.supports_dir_fd
        or not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"))
    ):
        return "race-safe artifact verification unavailable on this platform"
    try:
        dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        # Start from a pinned "/" descriptor and open *every* root and
        # relative-directory component without following links. A concurrent
        # rename/symlink swap cannot redirect an already opened directory fd.
        with ExitStack() as stack:
            current = os.open("/", dir_flags)
            stack.callback(os.close, current)
            for component in (*root.parts[1:], *parts[:-1]):
                child = os.open(component, dir_flags, dir_fd=current)
                stack.callback(os.close, child)
                current = child
            fd = os.open(parts[-1], file_flags, dir_fd=current)
            stack.callback(os.close, fd)
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                return "evidence must be a regular, non-hardlinked file"
            if not 0 < opened.st_size <= _MAX_ARTIFACT_BYTES:
                return "evidence size outside allowed bounds"
            digest = hashlib.sha256()
            count = 0
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > _MAX_ARTIFACT_BYTES:
                    return "evidence size outside allowed bounds"
                digest.update(chunk)
            after = os.fstat(fd)
            if count != opened.st_size or (opened.st_size, opened.st_mtime_ns) != (
                after.st_size, after.st_mtime_ns
            ):
                return "evidence changed during hashing"
        if not hmac.compare_digest(digest.hexdigest(), expected_sha):
            return "evidence SHA-256 mismatch"
    except (OSError, ValueError, RuntimeError):
        return "evidence missing or inaccessible"
    return None


def validate_local_artifacts(report: dict, *, root: Path) -> list[str]:
    """Integrity-check every PASS artifact, without vouching for its meaning."""
    if not isinstance(report, dict) or not isinstance(report.get("checks"), dict):
        return ["invalid pilot evidence report"]
    try:
        if not root.is_absolute() or not root.is_dir() or root.is_symlink() or any(
            parent.is_symlink() for parent in root.parents
        ):
            return ["artifact root must be an existing absolute non-symlink directory"]
    except OSError:
        return ["artifact root is unavailable"]
    errors = []
    for key in REQUIRED:
        entry = report["checks"].get(key)
        if not isinstance(entry, dict) or entry.get("status") != "PASS":
            continue
        reference = entry.get("evidence")
        digest = entry.get("sha256")
        if not isinstance(reference, str) or not reference:
            errors.append(f"{key}: missing local artifact reference")
            continue
        # Remote URLs are acceptable as *references* in structure-only mode,
        # but cannot be hashed without accessing an external server.
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference) or reference.startswith("//"):
            errors.append(f"{key}: remote evidence not integrity-verified")
            continue
        result = _integrity_of_local_artifact(root, reference, digest)
        if result is not None:
            errors.append(f"{key}: {result}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON evidence report")
    parser.add_argument("--check-structure-only", action="store_true",
                        help="Validate structure without claiming live acceptance")
    parser.add_argument("--artifact-root", type=Path,
                        help="Absolute directory of private, redacted evidence files; required for full gate")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Pilot readiness FAIL: unreadable JSON ({type(exc).__name__})", file=sys.stderr)
        return 2
    errors = validate(report, require_live=not args.check_structure_only)
    if not args.check_structure_only:
        if args.artifact_root is None:
            errors.append("artifact root is required to integrity-check PASS evidence")
        else:
            errors.extend(validate_local_artifacts(report, root=args.artifact_root))
    for error in errors:
        print("Pilot readiness FAIL: " + error, file=sys.stderr)
    if errors:
        return 1
    if args.check_structure_only:
        print("Pilot evidence structure valid; LIVE ACCEPTANCE NOT VERIFIED")
    else:
        print("Pilot evidence SHA-256 integrity checked; LIVE AUTHENTICITY AND INDEPENDENT APPROVAL NOT VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
