"""Offline regression tests for the pilot evidence gate."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_pilot_readiness import REQUIRED, validate


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
