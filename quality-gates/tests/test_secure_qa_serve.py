"""Offline security contract for opt-in TLS Quality Gates serving."""
from __future__ import annotations
import os

import pytest
from quality_gates.secure_qa_serve import config_from_env


def fixture_env(tmp_path):
    control = tmp_path / "control"
    evidence = tmp_path / "evidence"
    artifacts = tmp_path / "artifacts"
    for p in (control, evidence, artifacts):
        p.mkdir(mode=0o700)
    admin = control / "admin.key"
    signer = control / "signing.key"
    tls = control / "server.key"
    cert = control / "server.crt"
    admin.write_text("qg-admin-" + "a" * 40)
    signer.write_text("qg-signature-" + "b" * 40)
    tls.write_text("-----BEGIN PRIVATE KEY-----\nplaceholder\n-----END PRIVATE KEY-----\n")
    cert.write_text("test-certificate")
    for p in (admin, signer, tls):
        os.chmod(p, 0o600)
    return {
        "MAW_SECURE_QG_ENABLED": "1", "AUTH_ENABLED": "true",
        "MAW_QG_ADMIN_KEY_FILE": str(admin),
        "MAW_QG_SIGNING_KEY_FILE": str(signer),
        "MAW_QG_DATABASE_PATH": str(control / "quality.sqlite3"),
        "QG_TLS_CERT_FILE": str(cert), "QG_TLS_KEY_FILE": str(tls),
        "QG_EVIDENCE_ROOT": str(evidence), "QG_ARTIFACT_ROOT": str(artifacts),
    }


def test_secure_qa_config_is_offline_and_has_distinct_keys(tmp_path):
    env = fixture_env(tmp_path)
    before = set((tmp_path / "control").iterdir())
    admin, signing, db, cert, tls, evidence, artifact = config_from_env(env)
    assert admin != signing and len(admin) >= 32 and len(signing) >= 32
    assert db.endswith("quality.sqlite3")
    assert set((tmp_path / "control").iterdir()) == before


@pytest.mark.parametrize("name,value", [
    ("AUTH_ENABLED", "false"),
    ("MAW_SECURE_QG_ENABLED", "0"),
    ("ADMIN_API_KEYS", "an-untrusted-secret"),
    ("QG_QA_ATTESTATION_KEY", "ambient-signing"),
    ("MAW_QG_DATABASE_PATH", "relative.sqlite3"),
    ("QG_EVIDENCE_ROOT", "/no-such-qa-evidence"),
])
def test_secure_qa_rejects_unsafe_modes(tmp_path, name, value):
    env = {**fixture_env(tmp_path), name: value}
    with pytest.raises((ValueError, OSError)):
        config_from_env(env)


def test_secure_qa_rejects_symlink_and_world_readable_key(tmp_path):
    env = fixture_env(tmp_path)
    os.chmod(env["MAW_QG_SIGNING_KEY_FILE"], 0o644)
    with pytest.raises(ValueError, match="private"):
        config_from_env(env)
    os.chmod(env["MAW_QG_SIGNING_KEY_FILE"], 0o600)
    link = tmp_path / "signing-link"
    link.symlink_to(env["MAW_QG_SIGNING_KEY_FILE"])
    env["MAW_QG_SIGNING_KEY_FILE"] = str(link)
    with pytest.raises(ValueError, match="symlink"):
        config_from_env(env)


def test_secure_qa_no_half_config_or_identical_keys(tmp_path):
    env = fixture_env(tmp_path)
    env.pop("MAW_QG_SIGNING_KEY_FILE")
    with pytest.raises(ValueError, match="incomplete"):
        config_from_env(env)
    env = fixture_env(tmp_path)
    env["MAW_QG_SIGNING_KEY_FILE"] = env["MAW_QG_ADMIN_KEY_FILE"]
    with pytest.raises(ValueError, match="Distinct"):
        config_from_env(env)
