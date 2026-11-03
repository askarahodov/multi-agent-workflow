"""Offline regression tests for the pilot evidence gate."""
import hashlib
import json
import os
import subprocess

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_pilot_readiness as gate
from check_pilot_readiness import REQUIRED, validate, validate_local_artifacts


def make_report():
    return {
        "schema_version": 1,
        "commit_sha": "a" * 40,
        "checks": {
            key: {
                "status": "PASS",
                "evidence": f"docs/qa/evidence/{key}.json",
                "reviewer": "independent-reviewer",
            }
            for key in REQUIRED
        },
    }


def test_complete_evidence_inventory_is_structurally_valid():
    assert validate(make_report()) == []


def test_missing_live_proof_fails_closed():
    report = make_report()
    report["checks"]["live_openrouter_tool_call"]["status"] = "BLOCKED"
    assert any("live_openrouter_tool_call" in error for error in validate(report))
    assert validate(report, require_live=False) == []


def test_missing_review_and_artifact_fails():
    report = make_report()
    report["checks"]["independent_qa"].pop("reviewer")
    report["checks"]["git_commit_verified"]["evidence"] = ""
    errors = validate(report)
    assert any("independent_qa" in error for error in errors)
    assert any("git_commit_verified" in error for error in errors)


def test_rejects_secrets_and_path_traversal():
    report = make_report()
    report["checks"]["security_signoff"]["evidence"] = "../private/approval.txt"
    report["checks"]["clean_compose"]["evidence"] = "token=abcd1234"
    errors = validate(report)
    assert any("repository-relative" in error for error in errors)
    assert any("credential" in error for error in errors)


def test_cli_rejects_blocked_report(tmp_path):
    report = make_report()
    report["checks"]["clean_compose"]["status"] = "BLOCKED"
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_pilot_readiness.py"), str(path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "pilot not accepted" in result.stderr


def test_rejects_nested_json_secret_fields():
    for field in ("token", "secret", "api_key", "password", "authorization", "private_key"):
        report = make_report()
        report["extra"] = {"nested": [{field: "unredacted-credential-value"}]}
        assert any("credential" in error for error in validate(report)), field


def test_allows_explicitly_redacted_credential_fields():
    report = make_report()
    report["extra"] = {"token": "[REDACTED]"}
    assert validate(report) == []


def test_rejects_evidence_url_credentials_and_unverifiable_urls():
    unsafe = (
        "https://operator:password@example.org/evidence",
        "https://example.org/evidence?signature=example",
        "https://example.org/evidence#private",
        "https://",
        "https://[broken-ipv6/evidence",
        "http://example.org/evidence",
    )
    for url in unsafe:
        report = make_report()
        report["checks"]["clean_compose"]["evidence"] = url
        assert any("clean_compose" in error for error in validate(report)), url


def test_accepts_clean_https_evidence_url():
    report = make_report()
    report["checks"]["clean_compose"]["evidence"] = "https://example.org/evidence/report"
    assert validate(report) == []


def test_rejects_ambiguous_evidence_references():
    unsafe = (
        "HTTPS://operator:unredacted-credential@example.org/evidence?signature=value",
        " https://example.org/evidence",
        "https://example.org/evidence ",
        "//operator:password@example.org/evidence",
        "ftp://example.org/evidence",
        "C:\\\\private\\\\evidence.json",
        "docs\\\\private\\\\evidence.json",
        "docs/evidence.json?signature=value",
        "docs/evidence.json#token",
        "https:/example.org/evidence",
        "docs/evidence.json\\nother",
    )
    for reference in unsafe:
        report = make_report()
        report["checks"]["clean_compose"]["evidence"] = reference
        errors = validate(report)
        assert any("clean_compose" in error for error in errors), reference


def test_accepts_uppercase_https_without_credentials():
    report = make_report()
    report["checks"]["clean_compose"]["evidence"] = "HTTPS://example.org/evidence"
    assert validate(report) == []


def test_rejects_invalid_https_ports():
    for reference in (
        "https://example.org:not-a-port/evidence",
        "https://example.org:99999/evidence",
        "https://example.org:0/evidence",
    ):
        report = make_report()
        report["checks"]["clean_compose"]["evidence"] = reference
        assert any("clean_compose" in error for error in validate(report)), reference


def test_accepts_valid_https_nonstandard_port():
    report = make_report()
    report["checks"]["clean_compose"]["evidence"] = "https://example.org:8443/evidence"
    assert validate(report) == []


def create_private_pilot_artifacts(tmp_path):
    """Build real, separate, redacted files with bound SHA-256 pins."""
    root = tmp_path / "evidence"
    root.mkdir()
    report = make_report()
    for key in REQUIRED:
        path = root / (key + ".json")
        data = json.dumps({
            "check": key, "commit_sha": report["commit_sha"],
            "message": "sanitized evidence placeholder for filesystem integrity",
        }).encode("utf-8")
        path.write_bytes(data)
        report["checks"][key]["evidence"] = path.name
        report["checks"][key]["sha256"] = hashlib.sha256(data).hexdigest()
    return report, root


@pytest.mark.skipif(os.name != "posix", reason="POSIX race-safe artifact hashing required")
def test_pinned_local_evidence_integrity_is_checkable(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    assert validate(report) == []
    assert validate_local_artifacts(report, root=root) == []
    input_file = tmp_path / "inventory.json"
    input_file.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_pilot_readiness.py"),
         str(input_file), "--artifact-root", str(root)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "NOT VERIFIED" in result.stdout


def test_default_cli_does_not_accept_unpinned_or_unreadable_pass_artifacts(tmp_path):
    report = make_report()
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_pilot_readiness.py"), str(path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "artifact root is required" in result.stderr
    assert "Pilot evidence inventory complete" not in result.stdout


@pytest.mark.skipif(os.name != "posix", reason="POSIX race-safe artifact hashing required")
def test_late_artifact_mutation_invalidates_complete_pass_inventory(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    (root / "git_commit_verified.json").write_text("modified after digest capture")
    errors = validate_local_artifacts(report, root=root)
    assert any("git_commit_verified" in err and "SHA-256 mismatch" in err for err in errors)


@pytest.mark.skipif(os.name != "posix", reason="POSIX race-safe artifact hashing required")
def test_missing_or_nonexistent_or_empty_local_artifact_fails_closed(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    (root / "independent_qa.json").unlink()
    (root / "no_external_agent_cli.json").write_bytes(b"")
    report["checks"]["restart_persistence"]["sha256"] = ""
    errors = validate_local_artifacts(report, root=root)
    for name in ("independent_qa", "no_external_agent_cli", "restart_persistence"):
        assert any(name in error for error in errors), errors


def test_traversal_and_ambiguous_paths_cannot_escape_evidence_root(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    for invalid in ("../secret.json", "/etc/passwd", "//remote/pilot.json",
                    "sub/../other.json", "sub//other.json", "sub/./other.json",
                    "C:/secrets.txt", "folder\\private.json", "evidence:blob"):
        report["checks"]["security_signoff"]["evidence"] = invalid
        errors = validate_local_artifacts(report, root=root)
        assert any("security_signoff" in error for error in errors), invalid


@pytest.mark.skipif(os.name != "posix", reason="POSIX race-safe artifact hashing required")
def test_symlinked_and_hardlinked_evidence_refused(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    target = root / "clean_compose.json"
    alias = root / "alias.json"
    alias.symlink_to(target)
    report["checks"]["clean_compose"]["evidence"] = "alias.json"
    assert any("clean_compose" in err for err in validate_local_artifacts(report, root=root))
    alias.unlink()
    os.link(target, alias)
    assert any("non-hardlinked" in err for err in validate_local_artifacts(report, root=root))
    alias.unlink()


def test_https_references_are_structure_only_and_never_integrity_attested(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    report["checks"]["live_openrouter_tool_call"]["evidence"] = "https://example.org/review"
    assert validate(report) == []
    errors = validate_local_artifacts(report, root=root)
    assert any("remote evidence not integrity-verified" in err for err in errors)


@pytest.mark.skipif(os.name != "posix", reason="POSIX race-safe artifact hashing required")
def test_hash_errors_do_not_echo_secret_bearing_artifact_content(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    payload = b"DO_NOT_LOG_SECRET_VALUE_123456"
    (root / "security_signoff.json").write_bytes(payload)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_pilot_readiness.py"),
         str(inventory), "--artifact-root", str(root)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "DO_NOT_LOG_SECRET_VALUE_123456" not in result.stderr + result.stdout


@pytest.mark.skipif(os.name != "posix", reason="POSIX race-safe artifact hashing required")
def test_oversized_local_evidence_does_not_bypass_guard(tmp_path):
    report, root = create_private_pilot_artifacts(tmp_path)
    big = root / "clean_compose.json"
    with big.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    assert any("size outside" in err for err in validate_local_artifacts(report, root=root))


def test_structure_only_mode_does_not_claim_artifact_integrity(tmp_path):
    report = make_report()
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_pilot_readiness.py"),
         str(inventory), "--check-structure-only"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "LIVE ACCEPTANCE NOT VERIFIED" in result.stdout


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory descriptor traversal only")
def test_raced_ancestor_symlink_cannot_escape_opened_evidence_root(tmp_path, monkeypatch):
    report, root = create_private_pilot_artifacts(tmp_path)
    original_data = (root / "clean_compose.json").read_bytes()
    child = root / "nested"
    child.mkdir()
    (child / "clean_compose.json").write_bytes(original_data)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "clean_compose.json").write_bytes(original_data)
    report["checks"]["clean_compose"]["evidence"] = "nested/clean_compose.json"

    real_open = os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "nested" and dir_fd is not None and not swapped:
            swapped = True
            child.rename(root / "former_nested")
            child.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(gate.os, "open", swapping_open)
    monkeypatch.setattr(gate.os, "supports_dir_fd", os.supports_dir_fd | {swapping_open})
    errors = validate_local_artifacts(report, root=root)
    assert swapped
    assert any("clean_compose" in error for error in errors), errors



@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "mkfifo"),
                    reason="POSIX nonblocking FIFO open required")
def test_raced_fifo_replacement_has_external_hard_timeout(tmp_path):
    # If someone removes O_NONBLOCK in production code, the child's open()
    # blocks on the substituted FIFO. A *parent-enforced* timeout catches
    # this without hanging all of pytest/native-E2E until the job expires.
    report, root = create_private_pilot_artifacts(tmp_path)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(report), encoding="utf-8")
    child_script = """
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import check_pilot_readiness as gate

root = Path(sys.argv[2])
report = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
target = root / "clean_compose.json"
real_open = os.open
swapped = False

def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
    global swapped
    if path == "clean_compose.json" and dir_fd is not None and not swapped:
        swapped = True
        target.rename(root / "clean_compose.bak")
        os.mkfifo(target)
    return real_open(path, flags, mode, dir_fd=dir_fd)

gate.os.open = swapping_open
gate.os.supports_dir_fd = os.supports_dir_fd | {swapping_open}
errors = gate.validate_local_artifacts(report, root=root)
if not swapped or not any("clean_compose" in error for error in errors):
    sys.exit(1)
print("raced FIFO rejected")
"""
    result = subprocess.run(
        [sys.executable, "-c", child_script, str(ROOT), str(root), str(inventory)],
        capture_output=True, text=True, check=False, timeout=4,
    )
    assert result.returncode == 0, result.stderr
    assert "raced FIFO rejected" in result.stdout
