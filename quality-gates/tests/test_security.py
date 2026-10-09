"""Tests for the Security gate (dependency + secret scanning)."""

from __future__ import annotations

from conftest import FAKE_AWS_KEY, FAKE_GITHUB_TOKEN

from quality_gates.gates.security import SecurityGate


def test_security_passes_clean_workspace(clean_workspace):
    result = SecurityGate().execute(str(clean_workspace))
    assert result.passed is True
    cats = {f.category for f in result.findings}
    assert {"dep", "secret"} <= cats


def test_security_detects_known_vulnerable_dependency(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "requirements.txt").write_text("example-vuln-lib==1.0.0\n")
    result = SecurityGate().execute(str(ws))
    assert result.passed is False
    dep = [f for f in result.findings if f.category == "dep"][0]
    assert dep.passed is False
    assert dep.detail["vulnerable"][0]["package"] == "example-vuln-lib"


def test_security_prefix_x_version_advisory(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "requirements.txt").write_text("legacy-dep==0.9.3\n")
    result = SecurityGate().execute(str(ws))
    dep = [f for f in result.findings if f.category == "dep"][0]
    assert dep.passed is False
    assert dep.detail["vulnerable"][0]["package"] == "legacy-dep"


def test_security_detects_aws_key(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    # The fake AWS-shaped token is assembled at runtime from fragments, so no
    # literal secret-shaped string lives in this test's committed source.
    (ws / "settings.py").write_text(f'aws = "{FAKE_AWS_KEY}"\n')
    result = SecurityGate().execute(str(ws))
    secret = [f for f in result.findings if f.category == "secret"][0]
    assert secret.passed is False
    assert "AWS" in secret.detail["hits"][0]["reason"]


def test_security_redacts_secret_in_evidence(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    # ghp_ + 36 alphanumeric chars, assembled at runtime.
    (ws / "creds.py").write_text(f'token = "{FAKE_GITHUB_TOKEN}"\n')
    result = SecurityGate().execute(str(ws))
    secret = [f for f in result.findings if f.category == "secret"][0]
    matched = secret.detail["hits"][0]["matched"]
    assert FAKE_GITHUB_TOKEN not in matched  # redacted
    assert matched.startswith("ghp_") or matched.startswith("…")


def test_security_ignores_env_example(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / ".env.example").write_text(f"AWS_KEY={FAKE_AWS_KEY}\n")
    result = SecurityGate().execute(str(ws))
    assert result.passed is True
