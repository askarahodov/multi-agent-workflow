"""Tests for the Reviewer gate (style + architecture)."""

from __future__ import annotations

from quality_gates.gates.reviewer import ReviewerGate


def test_reviewer_passes_clean_workspace(clean_workspace):
    result = ReviewerGate().execute(str(clean_workspace))
    assert result.passed is True
    cats = {f.category for f in result.findings}
    assert {"arch", "style"} <= cats


def test_reviewer_fails_missing_manifest(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "README.md").write_text("hi")
    # no pyproject.toml -> architecture failure
    result = ReviewerGate().execute(str(ws))
    assert result.passed is False
    arch = [f for f in result.findings if f.category == "arch"][0]
    assert arch.passed is False
    assert "pyproject.toml" in arch.detail["missing"]


def test_reviewer_detects_todo_and_long_line(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n")
    (ws / "README.md").write_text("ok")
    (ws / "code.py").write_text("def f():\n    # TODO fix this\n    pass\n")
    (ws / "long.py").write_text("x = '" + "a" * 200 + "'\n")
    result = ReviewerGate().execute(str(ws))
    assert result.passed is False
    style = [f for f in result.findings if f.category == "style"][0]
    kinds = {v["kind"] for v in style.detail["violations"]}
    assert "todo" in kinds
    assert "long_line" in kinds


def test_reviewer_skips_vcs_and_virtualenvs(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("x")
    (ws / "README.md").write_text("x")
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("TODO inside git dir\n")
    (ws / ".venv").mkdir()
    (ws / ".venv" / "x.py").write_text("def f():\n    # FIXME\n    pass\n")
    result = ReviewerGate().execute(str(ws))
    # no production source files -> no style violations -> gate passes
    assert result.passed is True
