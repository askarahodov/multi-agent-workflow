"""Security contract for the opt-in no-secret runner entrypoint."""
from __future__ import annotations

import subprocess

import pytest

from quality_gates import operator_qa_runner as runner
from quality_gates.isolated_tester import SandboxError

IMAGE = "sha256:" + "a" * 64


def job(path):
    return {"command_id": "python-version", "checkout": str(path), "image_id": IMAGE, "commit_sha": "a" * 40}


@pytest.mark.parametrize("change", [
    {"command_id": "shell"},
    {"command_id": ["python-version"]},
    {"extra": "attack"},
])
def test_invalid_operator_job_cannot_execute(monkeypatch, tmp_path, change):
    monkeypatch.setattr(runner, "isolated_test", lambda *a, **k: pytest.fail("Docker invoked"))
    value = job(tmp_path)
    value.update(change)
    with pytest.raises(SandboxError):
        runner.execute_operator_job(value)


@pytest.mark.parametrize("key", [
    "MAW_QG_SIGNING_KEY_FILE", "MAW_QG_ADMIN_KEY_FILE",
    "MAW_QA_ORCH_ADMIN_KEY_FILE", "ADMIN_API_KEYS",
])
def test_signer_identity_denied(monkeypatch, tmp_path, key):
    monkeypatch.setenv(key, "")
    monkeypatch.setattr(runner, "isolated_test", lambda *a, **k: pytest.fail("Docker invoked"))
    with pytest.raises(SandboxError, match="credentials"):
        runner.execute_operator_job(job(tmp_path))


def test_operator_job_only_uses_allowlisted_argv(monkeypatch, tmp_path):
    calls = []
    def fake_test(argv, checkout, image_id):
        calls.append((argv, checkout, image_id))
        return subprocess.CompletedProcess(argv, 0, "ok", "")
    monkeypatch.setattr(runner, "_verify_checkout", lambda *args: None)
    monkeypatch.setattr(runner, "isolated_test", fake_test)
    outcome = runner.execute_operator_job(job(tmp_path))
    assert calls == [(("python", "--version"), tmp_path, IMAGE)]
    assert outcome == {"schema_version": 1, "kind": "untrusted_qa_execution",
                       "command_id": "python-version", "exit_code": 0,
                       "stdout_tail": "ok", "stderr_tail": ""}
    assert "signature" not in outcome and "passed" not in outcome


def test_unpinned_image_rejected_by_sandbox_without_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_verify_checkout", lambda *args: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Docker invoked"))
    value = job(tmp_path)
    value["image_id"] = "python:latest"
    with pytest.raises(SandboxError, match="pinned image"):
        runner.execute_operator_job(value)


def test_failed_test_is_not_a_trusted_qa_verdict(monkeypatch, tmp_path):
    def fake_test(argv, checkout, image_id):
        return subprocess.CompletedProcess(argv, 13, "bad", "failed")
    monkeypatch.setattr(runner, "_verify_checkout", lambda *args: None)
    monkeypatch.setattr(runner, "isolated_test", fake_test)
    outcome = runner.execute_operator_job(job(tmp_path))
    assert outcome["kind"] == "untrusted_qa_execution"
    assert outcome["schema_version"] == 1
    assert outcome["exit_code"] == 13
    assert not any(k in outcome for k in (
        "signature", "attestation", "passed", "qa_receipt", "commit_sha",
    ))



def test_checkout_dirty_or_wrong_commit_rejected_before_docker(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=qa@example.test",
                    "-c", "user.name=QA", "commit", "--allow-empty", "-qm", "init"], check=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    value = job(repo)
    value["commit_sha"] = "0" * 40
    monkeypatch.setattr(runner, "isolated_test", lambda *a, **k: pytest.fail("Docker invoked"))
    with pytest.raises(SandboxError, match="SHA mismatch"):
        runner.execute_operator_job(value)
    value["commit_sha"] = head
    (repo / "untracked.txt").write_text("unexpected")
    with pytest.raises(SandboxError, match="dirty"):
        runner.execute_operator_job(value)
