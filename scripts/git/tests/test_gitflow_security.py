"""Security regression tests for the GitFlow enforcement tooling.

Covers the code-fixes for SEC-004, SEC-005, SEC-002/SEC-010, SEC-011 and
SEC-003/SEC-006 in `scripts/git/` and `.github/workflows/gitflow-policy.yml`.

Every test builds a real throwaway git repository/worktree in a temp dir and
exercises the actual hook scripts / modules — no mocking of git.

Run:  python -m pytest scripts/git/tests -q
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

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
    for name in ("AGENT_GITFLOW_RULES.md", "gitflow-policy.schema.json"):
        (repo / name).write_bytes((REPO_ROOT / name).read_bytes())


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


# --------------------------------------------------------------------------- #
# Follow-up — the hooks must not stay configured-but-inert (core.hooksPath
# pointing into the void is exactly the primary-repo defect: direct commits to
# main run with NO hooks at all because git silently skips a missing dir).
# --------------------------------------------------------------------------- #
def test_hooks_activation_flags_void_hookspath(tmp_path):
    repo = make_repo(tmp_path / "r")
    (repo / ".githooks").unlink()  # core.hooksPath now resolves to nothing
    result = context.hooks_activation(repo)
    assert result["active"] is False
    assert result["checks"]["hooks_path_configured"] is True
    assert result["checks"]["hooks_dir_present"] is False


def test_hooks_activation_true_when_installed(tmp_path):
    repo = make_repo(tmp_path / "r")
    result = context.hooks_activation(repo)
    assert result["active"] is True
    assert all(result["checks"].values())


def test_check_workspace_requires_live_hooks(tmp_path):
    repo = make_repo(tmp_path / "r")
    wt = repo / ".worktrees" / "t_011bbbbb"
    git(repo, "worktree", "add", "-b", "wt/t_011bbbbb", str(wt), "HEAD")
    # A freshly created worktree has no .githooks yet -> not compliant.
    assert not (wt / ".githooks").exists()
    result = context.check_workspace(repo, "t_011bbbbb", wt)
    assert result["checks"]["hooks_active"] is False
    assert result["compliant"] is False


def test_install_script_check_mode(tmp_path):
    repo = make_repo(tmp_path / "r")
    script = REPO_ROOT / "scripts" / "install-gitflow-hooks.sh"

    (repo / ".githooks").unlink()  # inert: hooksPath -> void
    proc = subprocess.run(
        ["bash", str(script), "--check", "--repo", str(repo)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    assert "points into the void" in proc.stderr

    os.symlink(str(HOOKS), repo / ".githooks")  # active again
    proc = subprocess.run(
        ["bash", str(script), "--check", "--repo", str(repo)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "hooks active" in proc.stdout


# --------------------------------------------------------------------------- #
# Follow-up — CI must actually invoke the canonical commit checker (GF-04).
# --------------------------------------------------------------------------- #
def test_workflow_invokes_check_commits_from_base():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/git/gitflow-hooks/check_commits.py" in text
    # Must be materialized from the trusted base, not the PR head.
    assert "worktree add" in text
    assert "${{ steps.branch.outputs.base }}" in text


# --------------------------------------------------------------------------- #
# SEC-FIX — CI expression injection (CWE-78). github.head_ref is attacker
# controlled and, when textually interpolated into a `run:` body, the shell
# executes it. Untrusted values must be passed via `env:` instead.
# --------------------------------------------------------------------------- #
def _steps():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []) or []:
            yield step


def _step(name_prefix: str) -> dict:
    for step in _steps():
        if str(step.get("name", "")).startswith(name_prefix):
            return step
    raise AssertionError(f"step '{name_prefix}…' not found in gitflow-policy.yml")


def test_workflow_has_no_expression_interpolation_in_shell_blocks():
    """No ``${{ … }}`` may appear in any run:/script: body of this workflow.

    Any interpolation in a shell body is textually substituted by Actions
    BEFORE bash runs, so a value containing ``$(``/backticks executes. All
    such values must go through ``env:`` (where the shell treats them as data).
    """
    offenders = []
    for step in _steps():
        for field in ("run", "script"):
            body = step.get(field)
            if isinstance(body, str) and "${{" in body:
                offenders.append(f"{step.get('name')!r}[{field}]")
    assert offenders == [], f"expression interpolation inside shell block(s): {offenders}"


@pytest.mark.parametrize("hostile", ["feat/a$(touch pwned)", "feat/a`touch pwned`", "feat/a;touch pwned"])
def test_resolve_branch_step_treats_head_ref_as_data(tmp_path, hostile):
    """The resolve step must NOT execute a hostile branch name as shell."""
    script = _step("Resolve branch name")["run"]
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "EVENT_NAME": "pull_request",
        "HEAD_REF": hostile,
        "BASE_SHA": "0" * 40,
        "GITHUB_OUTPUT": str(out),
    }
    proc = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "pwned").exists(), "github.head_ref was executed as shell!"
    assert f"branch={hostile}" in out.read_text(encoding="utf-8")


def test_naming_validation_rejects_hostile_branch_without_executing(tmp_path):
    script = _step("Validate branch naming")["run"]
    env = {**os.environ, "BRANCH": "feat/a$(touch pwned)"}
    proc = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert proc.returncode == 1, proc.stdout
    assert not (tmp_path / "pwned").exists(), "branch name was executed as shell!"


def test_head_ref_is_passed_through_env():
    step = _step("Resolve branch name")
    assert step.get("env", {}).get("HEAD_REF") == "${{ github.head_ref }}"
    # The hostile inline form must be gone.
    assert 'BRANCH="${{ github.head_ref }}"' not in WORKFLOW.read_text(encoding="utf-8")



# GF-07: post-merge cleanup must be fail-closed even through legacy force flag.
def _cleanup_fixture(tmp_path):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "--unset", "core.hooksPath")
    wt = repo / ".worktrees" / "t_345abcde"
    assert git(repo, "worktree", "add", "-b", "wt/t_345abcde", str(wt), "main").returncode == 0
    return repo, wt, lifecycle.WorktreeLifecycle(repo)


def test_cleanup_legacy_force_never_discards_dirty_or_unique_work(tmp_path):
    repo, wt, lc = _cleanup_fixture(tmp_path)
    (wt / "precious.txt").write_text("uncommitted")
    result = lc.cleanup_worktree("t_345abcde", force_guard=True, maintenance_window=True)
    assert result["reason"] == "uncommitted_work_guard"
    assert (wt / "precious.txt").read_text() == "uncommitted"
    assert git(wt, "add", "precious.txt").returncode == 0
    assert git(wt, "commit", "-qm", "feat(test): preserve unique work").returncode == 0
    result = lc.cleanup_worktree("t_345abcde", force_guard=True, maintenance_window=True)
    assert result["reason"] == "unmerged_commits_guard"
    assert wt.exists() and lc.branch_exists("wt/t_345abcde")


def test_cleanup_preserves_ignored_files_and_wrong_worktree(tmp_path):
    repo, wt, lc = _cleanup_fixture(tmp_path)
    (repo / ".git" / "info" / "exclude").write_text("precious.txt\n")
    (wt / "precious.txt").write_text("ignored data")
    assert lc.cleanup_worktree("t_345abcde", force_guard=True, maintenance_window=True)["reason"] == "uncommitted_work_guard"
    assert (wt / "precious.txt").exists()
    (wt / "precious.txt").unlink()
    assert git(wt, "checkout", "-qb", "other").returncode == 0
    assert lc.cleanup_worktree("t_345abcde", maintenance_window=True)["reason"] == "worktree_path_guard"
    assert wt.exists()


def test_cleanup_never_removes_surviving_remote_ref(tmp_path):
    repo, wt, lc = _cleanup_fixture(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    assert git(remote, "init", "--bare", "-q").returncode == 0
    assert git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert git(repo, "push", "-q", "origin", "main", "wt/t_345abcde").returncode == 0
    result = lc.cleanup_worktree("t_345abcde", force_guard=True, maintenance_window=True)
    assert result["reason"] == "remote_branch_pending_cleanup"
    assert wt.exists() and lc.branch_exists("wt/t_345abcde")
    assert git(remote, "rev-parse", "--verify", "refs/heads/wt/t_345abcde").returncode == 0
    # Simulate GitHub's confirmed merged-head deletion, then local cleanup.
    assert git(repo, "push", "-q", "origin", "--delete", "wt/t_345abcde").returncode == 0
    assert lc.cleanup_worktree("t_345abcde", maintenance_window=True)["verified_clean"] is True
    assert not wt.exists() and not lc.branch_exists("wt/t_345abcde")


def test_cleanup_does_not_trust_unpublished_local_merge(tmp_path):
    repo, wt, lc = _cleanup_fixture(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    assert git(remote, "init", "--bare", "-q").returncode == 0
    assert git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert git(repo, "push", "-q", "origin", "main").returncode == 0
    (wt / "local.txt").write_text("unique")
    assert git(wt, "add", "local.txt").returncode == 0
    assert git(wt, "commit", "-qm", "feat(test): local work").returncode == 0
    assert git(repo, "merge", "--ff-only", "wt/t_345abcde").returncode == 0
    assert lc.cleanup_worktree("t_345abcde", maintenance_window=True)["reason"] == "unmerged_commits_guard"
    assert wt.exists()


def test_cleanup_retains_tip_that_moves_after_worktree_removal(tmp_path, monkeypatch):
    repo, wt, lc = _cleanup_fixture(tmp_path)
    branch = "wt/t_345abcde"
    assert git(repo, "checkout", "-b", "unique").returncode == 0
    assert git(repo, "commit", "--allow-empty", "-m", "chore(test): unique").returncode == 0
    moved = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert git(repo, "checkout", "main").returncode == 0
    original = lifecycle.delete_merged_ref
    def concurrent(repo_path, name, expected, target, target_tip):
        assert git(repo_path, "update-ref", "refs/heads/" + name, moved).returncode == 0
        original(repo_path, name, expected, target, target_tip)
    monkeypatch.setattr(lifecycle, "delete_merged_ref", concurrent)
    result = lc.cleanup_worktree("t_345abcde", maintenance_window=True)
    assert result["status"] == "blocked"
    assert git(repo, "rev-parse", branch).stdout.strip() == moved


def test_lifecycle_window_and_shared_mutation_lock(tmp_path):
    repo, wt, lc = _cleanup_fixture(tmp_path)
    assert lc.cleanup_worktree("t_345abcde", force_guard=True)["reason"] == "maintenance_window_guard"
    from guarded_ref import repo_mutation_lock
    with repo_mutation_lock(wt):
        assert lc.cleanup_worktree("t_345abcde", maintenance_window=True)["reason"] == "mutation_lock_guard"
        with pytest.raises(lifecycle.LifecycleError, match="mutation_lock_guard"):
            lc.create_worktree("t_1234abcd", "main")
    assert wt.exists() and lc.branch_exists("wt/t_345abcde")
    assert not lc.branch_exists("wt/t_1234abcd")
    assert lc.cleanup_worktree("t_345abcde", maintenance_window=True)["verified_clean"]


@pytest.mark.parametrize("case", ["missing-rules", "missing-schema", "broken-yaml", "broken-json", "version-drift", "empty-rules"])
def test_policy_injection_rejects_missing_or_stale_registry(tmp_path, case):
    repo = make_repo(tmp_path / "r")
    _prep_policy_repo(repo)
    rules = repo / "AGENT_GITFLOW_RULES.md"
    schema = repo / "gitflow-policy.schema.json"
    if case == "missing-rules":
        rules.unlink()
    elif case == "missing-schema":
        schema.unlink()
    elif case == "broken-yaml":
        rules.write_text("---\nversion: [\n---\n")
    elif case == "broken-json":
        schema.write_text("{")
    elif case == "version-drift":
        data = json.loads(schema.read_text())
        data["version"] = "1.0.0"
        schema.write_text(json.dumps(data))
    else:
        rules.write_text('---\nversion: "1.3.0"\nrules: []\n---\n')
    with pytest.raises(RuntimeError):
        context.build_policy_bundle(repo, "t_deadbeef", repo)


def test_policy_bundle_and_pointer_must_match_current_registry(tmp_path):
    repo = make_repo(tmp_path / "r")
    _prep_policy_repo(repo)
    (repo / "scripts" / "git").mkdir(parents=True)
    os.symlink(str(HOOKS), repo / "scripts" / "git" / "gitflow-hooks")
    # Check bundle freshness independently of hook activation.
    expected = context.build_policy_bundle(repo, "t_deadbeef", repo)
    bundle = repo / "AGENT_GITFLOW_CONTEXT.json"
    pointer = repo / ".agent-gitflow.json"
    bundle.write_text(json.dumps(expected))
    pointer.write_text(json.dumps({
        "task_id": "t_deadbeef", "branch_name": expected["branch_name"],
        "policy_path": expected["rules_path"], "schema_path": expected["schema_path"],
        "context_path": str(bundle), "policy_version": expected["version"],
    }))
    assert context.check_workspace(repo, "t_deadbeef", repo)["checks"]["policy_current"]
    expected["version"] = "1.0.0"
    bundle.write_text(json.dumps(expected))
    assert not context.check_workspace(repo, "t_deadbeef", repo)["checks"]["policy_current"]


def test_checkpoint_runs_for_every_pr_and_executes_literal_make_check():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/make-check-checkpoint.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers["pull_request"]) == {"types"}
    assert set(triggers["pull_request"]["types"]) == {"opened", "reopened", "synchronize", "ready_for_review", "edited"}
    assert "pull_request_target" not in triggers
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["make-check"]["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == {"persist-credentials": False, "fetch-depth": 0}
    actual = next(s for s in steps if s.get("name") == "Execute exact Makefile target")
    assert "if" not in actual and "continue-on-error" not in actual
    assert "make check" in actual["run"].splitlines()
    assert "python3 scripts/git/checkpoint_provenance.py" in actual["run"].splitlines()
    upload = next(s for s in steps if s.get("name") == "Publish exact PR checkpoint receipt")
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["if"] == "github.event_name == 'pull_request'"
    assert "github.event.pull_request.number" in upload["with"]["name"]
    assert "github.sha" in upload["with"]["name"] and "github.run_attempt" in upload["with"]["name"]


@pytest.mark.parametrize("case", ["wrong-checkout", "wrong-head", "wrong-base", "head-only", "manual-with-pr", "missing-base"])
def test_checkpoint_provenance_rejects_stale_or_unrelated_candidate(case):
    module = _load("checkpoint_provenance", GIT_DIR / "checkpoint_provenance.py")
    sha, base, head = ("a" * 40, "b" * 40, "c" * 40)
    event, expected, line = "pull_request", sha, f"{sha} {base} {head}"
    if case == "wrong-checkout": expected = "d" * 40
    elif case == "wrong-head": head = "d" * 40
    elif case == "wrong-base": base = "d" * 40
    elif case == "head-only": line = sha
    elif case == "manual-with-pr": event = "workflow_dispatch"
    else: base = ""
    with pytest.raises(ValueError):
        module.validate(event, expected, head, base, line)


def test_checkpoint_provenance_accepts_exact_merge_and_manual_checkout():
    module = _load("checkpoint_provenance", GIT_DIR / "checkpoint_provenance.py")
    sha, base, head = ("a" * 40, "b" * 40, "c" * 40)
    assert module.validate("pull_request", sha, head, base, f"{sha} {base} {head}") == sha
    assert module.validate("workflow_dispatch", sha, "", "", f"{sha} {base}") == sha


def test_gitflow_gate_binds_its_prerequisites_to_current_run_attempt():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "needs: [policy-compliance, worktree-isolation]" in text
    assert "CURRENT_RUN_ID: ${{ github.run_id }}" in text
    assert "CURRENT_RUN_ATTEMPT: ${{ github.run_attempt }}" in text
    assert "run_id: ownIdentity.run_id, attempt_number: ownIdentity.run_attempt" in text
    assert "assess(required, bindOwnChecks(required, runs, ownJobs, ownIdentity))" in text
    assert "ownLatest.run_attempt !== ownIdentity.run_attempt" in text
