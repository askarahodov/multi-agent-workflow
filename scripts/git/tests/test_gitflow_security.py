"""Security regression tests for the GitFlow enforcement tooling.

Covers the code-fixes for SEC-004, SEC-005, SEC-002/SEC-010, SEC-011 and
SEC-003/SEC-006 in `scripts/git/` and `.github/workflows/gitflow-policy.yml`.

Every test builds a real throwaway git repository/worktree in a temp dir and
exercises the actual hook scripts / modules — no mocking of git.

Run:  python -m pytest scripts/git/tests -q
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GIT_DIR = REPO_ROOT / "scripts" / "git"
HOOKS = GIT_DIR / "gitflow-hooks"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "gitflow-policy.yml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lifecycle = _load("worktree_lifecycle", GIT_DIR / "worktree-lifecycle.py")
context = _load("gitflow_context", GIT_DIR / "gitflow_context.py")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def make_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "tester")
    (path / "f.txt").write_text("x\n")
    git(path, "add", "f.txt")
    git(path, "commit", "-qm", "chore(t_00000000): seed")
    os.symlink(str(HOOKS), path / ".githooks")
    git(path, "config", "core.hooksPath", ".githooks")
    return path


def run_hook(hook: str, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOKS / hook), *args], cwd=cwd, capture_output=True, text=True
    )


# --------------------------------------------------------------------------- #
# SEC-002 / SEC-010 — core.hooksPath read-back + defensive hook guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("hook", ["pre-commit", "commit-msg", "pre-push", "post-merge"])
def test_hooks_refuse_when_hookspath_redirected(tmp_path, hook):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "core.hooksPath", "/tmp/evil")
    proc = run_hook(hook, repo)
    assert proc.returncode == 1, proc.stderr
    assert "SEC-010" in proc.stderr


def test_hooks_run_when_hookspath_canonical(tmp_path):
    repo = make_repo(tmp_path / "r")
    git(repo, "checkout", "-qb", "wt/t_00000000")
    msg = tmp_path / "msg"
    msg.write_text("chore(t_00000000): ok\n")
    proc = run_hook("commit-msg", repo, str(msg))
    assert proc.returncode == 0, proc.stderr
    assert "SEC-010" not in proc.stderr


def test_set_hooks_path_reads_back(tmp_path):
    repo = make_repo(tmp_path / "r")
    assert lifecycle.WorktreeLifecycle(repo)._set_hooks_path(repo) is True


def test_validate_flags_redirected_hookspath(tmp_path):
    repo = make_repo(tmp_path / "r")
    wt = repo / ".worktrees" / "t_de32abcd"
    git(repo, "worktree", "add", "-b", "wt/t_de32abcd", str(wt), "HEAD")
    lifecycle.WorktreeLifecycle(repo)._install_hooks(wt)
    assert git(wt, "config", "core.hooksPath").stdout.strip() == ".githooks"

    git(wt, "config", "core.hooksPath", "/tmp/evil")
    result = lifecycle.WorktreeLifecycle(repo).validate_worktree("t_de32abcd")
    assert result["checks"]["hooks_path_valid"] is False
    assert result["valid"] is False


# --------------------------------------------------------------------------- #
# SEC-004 — symlink target is absolute and confined to the hook template
# --------------------------------------------------------------------------- #
def test_install_hooks_creates_absolute_contained_symlink(tmp_path):
    repo = make_repo(tmp_path / "r")
    # Real template must exist inside the repo for the containment check.
    (repo / "scripts" / "git").mkdir(parents=True)
    os.symlink(str(HOOKS), repo / "scripts" / "git" / "gitflow-hooks")
    wt = repo / ".worktrees" / "t_004aaaaa"
    git(repo, "worktree", "add", "-b", "wt/t_004aaaaa", str(wt), "HEAD")

    assert lifecycle.WorktreeLifecycle(repo)._install_hooks(wt) is True
    target = os.readlink(wt / ".githooks")
    assert os.path.isabs(target)
    assert Path(target).resolve() == (repo / "scripts" / "git" / "gitflow-hooks").resolve()


def test_install_hooks_refuses_out_of_tree_template(tmp_path):
    repo = make_repo(tmp_path / "r")
    (repo / "scripts" / "git").mkdir(parents=True)
    os.symlink(str(HOOKS), repo / "scripts" / "git" / "gitflow-hooks")
    evil = tmp_path / "evil-hooks"
    evil.mkdir()
    (evil / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    wt = repo / ".worktrees" / "t_004bbbbb"
    git(repo, "worktree", "add", "-b", "wt/t_004bbbbb", str(wt), "HEAD")

    lc = lifecycle.WorktreeLifecycle(repo, hooks_src=evil)
    assert lc._install_hooks(wt) is False
    assert not (wt / ".githooks").is_symlink()


# --------------------------------------------------------------------------- #
# SEC-005 — pre-commit rejects a tracked .worktrees/
# --------------------------------------------------------------------------- #
def test_pre_commit_blocks_tracked_worktrees(tmp_path):
    repo = make_repo(tmp_path / "r", branch="wt/t_00000000")
    leak = repo / ".worktrees" / "t_deadbeef" / "leak.txt"
    leak.parent.mkdir(parents=True)
    leak.write_text("z\n")
    git(repo, "add", "-f", str(leak.relative_to(repo)))

    proc = run_hook("pre-commit", repo)
    assert proc.returncode == 1
    assert "SEC-005" in proc.stderr

    git(repo, "rm", "-q", "--cached", str(leak.relative_to(repo)))
    proc = run_hook("pre-commit", repo)
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------- #
# SEC-003 / SEC-006 — exact semver comparison in the CI gate
# --------------------------------------------------------------------------- #
def _workflow_semver():
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"(?m)^([ \t]*)(def semver\(s\):\n(?:\1[ \t].*\n)+)", text)
    assert m, "semver() not found in gitflow-policy.yml"
    # The function is embedded indented inside the workflow's `run: |` block;
    # re-add the def's own indentation then dedent so it can be exec'd.
    ns: dict = {}
    exec("import re\n" + textwrap.dedent(m.group(1) + m.group(2)), ns)  # noqa: S102 (test)
    return ns["semver"]


@pytest.mark.parametrize(
    "rules,schema,equal",
    [
        ("1.0", "1.0.0", True),
        ("1.0.0", "1.0.0", True),
        ("1.0.1", "1.0.0", False),
        ("1.1", "1.0.0", False),
        ("2.0", "1.0.0", False),
    ],
)
def test_semver_exact_comparison(rules, schema, equal):
    semver = _workflow_semver()
    assert (semver(rules) == semver(schema)) is equal


def test_workflow_no_longer_uses_major_minor_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "def mm(s)" not in text


# --------------------------------------------------------------------------- #
# SEC-011 — realpath containment for policy-bundle paths
# --------------------------------------------------------------------------- #
def _prep_policy_repo(repo: Path) -> None:
    (repo / "AGENT_GITFLOW_RULES.md").write_text('---\nversion: "1.0"\n---\n')
    (repo / "gitflow-policy.schema.json").write_text('{"version": "1.0.0"}')


def test_write_refuses_symlinked_context_file(tmp_path):
    repo = make_repo(tmp_path / "r")
    _prep_policy_repo(repo)
    (repo / "scripts" / "git").mkdir(parents=True)
    os.symlink(str(HOOKS), repo / "scripts" / "git" / "gitflow-hooks")
    wt = repo / ".worktrees" / "t_011aaaaa"
    git(repo, "worktree", "add", "-b", "wt/t_011aaaaa", str(wt), "HEAD")

    victim = tmp_path / "victim.txt"
    victim.write_text("original")
    os.symlink(str(victim), wt / "AGENT_GITFLOW_CONTEXT.json")

    with pytest.raises(RuntimeError, match="SEC-011"):
        context.write_workspace_policy(repo, "t_011aaaaa", wt)
    assert victim.read_text() == "original"


def test_bundle_refuses_policy_symlink_escaping_repo(tmp_path):
    repo = make_repo(tmp_path / "r")
    _prep_policy_repo(repo)
    outside = tmp_path / "outside.md"
    outside.write_text("---\nversion: \"9.9\"\n---\n")
    (repo / "AGENT_GITFLOW_RULES.md").unlink()
    os.symlink(str(outside), repo / "AGENT_GITFLOW_RULES.md")

    with pytest.raises(RuntimeError, match="escapes the repository root"):
        context.build_policy_bundle(repo, "t_deadbeef", repo)
