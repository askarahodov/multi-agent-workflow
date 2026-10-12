"""Tests for GitStorage (task item (e)): status, commit, diff, scoping."""

from __future__ import annotations

import os
import subprocess

import pytest

from tools.git_storage import GitStorage, GitStorageError


@pytest.fixture
def repo(tmp_path):
    """A fresh bare-less git repository with an initial commit."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.test"], cwd=root, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=root, capture_output=True, check=True
    )
    (root / "README.md").write_text("# Repo\n")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)
    return root


def test_status_and_dirty(repo):
    gs = GitStorage(repo)
    assert gs.dirty() is False
    (repo / "a.txt").write_text("hello")
    assert gs.dirty() is True
    rows = gs.status()
    assert any(r["path"].endswith("a.txt") for r in rows)


def test_commit_creates_commit(repo):
    gs = GitStorage(repo)
    (repo / "a.txt").write_text("hello\n")
    result = gs.commit("add a.txt", paths=["a.txt"])
    assert result.short_hash  # e.g. 8 chars
    assert result.message == "add a.txt"
    assert gs.dirty() is False
    assert "a.txt" in result.changed_files


def test_commit_requires_message(repo):
    gs = GitStorage(repo)
    with pytest.raises(GitStorageError):
        gs.commit("   ")


def test_commit_with_no_change_raises(repo):
    gs = GitStorage(repo)
    with pytest.raises(GitStorageError):
        gs.commit("noop")  # nothing staged → no change


def test_log_and_head(repo):
    gs = GitStorage(repo)
    assert gs.head_sha() is not None
    (repo / "b.txt").write_text("b")
    gs.commit("second", paths=["b.txt"])
    lines = gs.log(max_entries=5)
    assert any("second" in ln for ln in lines)


def test_diff(repo):
    gs = GitStorage(repo)
    (repo / "README.md").write_text("# Repo\nchanged\n")
    diff = gs.diff()
    assert "README.md" in diff


def test_author_env_set_on_request():
    repo = None
    # author is only surfaced through env; GitStorage accepts and stores it.
    gs = GitStorage(os.getcwd(), author_name="Agent", author_email="agent@local")
    assert gs.author_name == "Agent"
    assert gs.author_email == "agent@local"


def test_is_repo(repo):
    assert GitStorage(repo).is_repo() is True
    assert GitStorage("/tmp").is_repo() is False