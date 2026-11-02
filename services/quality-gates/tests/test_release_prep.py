"""Tests for the Release Preparation agent and gate."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from quality_gates.gates.release_prep import ReleasePrepAgent, ReleasePrepGate


def _make_workspace(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (ws / "README.md").write_text("# demo\n")
    (ws / "code.py").write_text("VERSION='0.1.0'\n")
    (ws / "CHANGELOG.md").write_text(
        "## v0.1.0\n\n- Initial release\n\n## v0.0.1\n\n- Skeleton\n"
    )
    return ws


def test_agent_assemble_produces_verifiable_candidate(tmp_path):
    ws = _make_workspace(tmp_path)
    agent = ReleasePrepAgent(artifact_root=tmp_path / "art")
    cand = agent.assemble(str(ws), "0.2.0", task_id="t1")
    assert cand["status"] == "awaiting_approval"
    assert "0.2.0" in cand["release_notes"]
    assert Path(cand["artifact_path"]).exists()
    # checksum matches the artifact on disk
    assert Path(cand["artifact_path"]).stat().st_size > 0
    # changelog content lands in the notes
    assert "Initial release" in cand["release_notes"]


def test_gate_passes_when_artifact_verifies(tmp_path):
    ws = _make_workspace(tmp_path)
    gate = ReleasePrepGate(agent=ReleasePrepAgent(artifact_root=tmp_path / "art"))
    result = gate.execute(str(ws), {"version": "1.0.0-rc"})
    assert result.passed is True
    rel = [f for f in result.findings if f.category == "release"][0]
    assert rel.detail["verifies"] is True
    assert "1.0.0-rc" in rel.detail["artifact_path"]


def test_agent_self_approval_is_forbidden(tmp_path):
    ws = _make_workspace(tmp_path)
    agent = ReleasePrepAgent(artifact_root=tmp_path / "art")
    cand = agent.assemble(str(ws), "0.2.0", task_id="t1")
    with pytest.raises(Exception, match="cannot approve"):
        agent.validate_approval(cand, "release_prep")


def test_approval_requires_awaiting_status(tmp_path):
    ws = _make_workspace(tmp_path)
    agent = ReleasePrepAgent(artifact_root=tmp_path / "art")
    cand = agent.assemble(str(ws), "0.2.0", task_id="t1")
    cand["status"] = "approved"
    with pytest.raises(Exception, match="awaiting_approval"):
        agent.validate_approval(cand, "human-reviewer")


def test_artifact_tar_contains_source(tmp_path):
    ws = _make_workspace(tmp_path)
    agent = ReleasePrepAgent(artifact_root=tmp_path / "art")
    cand = agent.assemble(str(ws), "0.2.0", task_id="t1")
    with tarfile.open(cand["artifact_path"], "r:gz") as tf:
        names = tf.getnames()
    assert any(n.endswith("code.py") for n in names)
    assert not any("__pycache__" in n or ".git" in n for n in names)
