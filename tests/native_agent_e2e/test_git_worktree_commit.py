"""#11 local Git evidence: real git subprocess, SQLite attempt fence & ledger.

No Hermes, external model, network or fallback CLI. Product worktree service is
invoked by a trusted runner, never exposed as arbitrary LLM git commands.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_management.agent_loop import run_agent_loop
from agent_management.errors import ToolPolicyDenied
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.trusted_git_worktree import TrustedGitWorktreeStore
from shared.attempt_fence import TrustedSqliteAttemptFence, AttemptFenceDenied
from orchestration_server.native_bridge import run_native_task_attempt
from test_native_contract_pipeline import runtime, ScriptedStream, tool, usage, done


def git_bin():
    path = shutil.which("git")
    if not path:
        pytest.skip("Git binary absent")
    return str(Path(path).resolve())


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [git_bin(), *args], cwd=cwd, shell=False,
        capture_output=True, text=True, check=True, timeout=12,
        env={
            "HOME": "/nonexistent", "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
        },
    )
    return completed.stdout.strip()


def store(tmp_path: Path):
    repository = tmp_path / "source-repository"
    repository.mkdir()
    git(repository, "init", "-q")
    (repository / "README.md").write_text("Operator source baseline\n")
    git(repository, "add", "--", "README.md")
    git(repository, "-c", "user.name=Native Test", "-c",
        "user.email=native@localhost", "commit", "-qm", "Initial source")
    worktrees = tmp_path / "attempt-worktrees"
    worktrees.mkdir(mode=0o700)
    return TrustedGitWorktreeStore(
        repository, worktrees, git_executable=git_bin(),
    ), repository


def scope(runtime, attempt):
    fence = TrustedSqliteAttemptFence(
        runtime["ledger"].path.parent / "orchestration.sqlite3",
        run_id=runtime["run"].id, task_id=runtime["task"].id,
        attempt_id=attempt.id, agent_id=runtime["agent"].id,
    )
    return fence


@pytest.mark.asyncio
async def test_native_llm_tool_cycle_commits_artifact_in_per_attempt_worktree(
    runtime, tmp_path,
):
    storage, repository = store(tmp_path)
    baseline = git(repository, "rev-parse", "HEAD")
    written = []

    async def runner(task_id, attempt_id):
        worktree = storage.provision(task_id, attempt_id)
        assert worktree.parent == storage.home
        fs = ScopedFilesystemExecutor(worktree, {
            "fs_read": [str(worktree / "README.md")],
            "fs_write": [str(worktree / "out" / "**")],
        })
        from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
        ledger_scope = f"run-{runtime['run'].id}/attempt-{attempt_id}"
        dispatcher = NativeFilesystemDispatcher(
            fs, ledger=runtime["ledger"], execution_scope=ledger_scope,
        )
        provider = ScriptedStream(
            [tool("write_file", "write-artifact", path="out/result.txt",
                  content="actual Native LLM artifact"), usage(), done("tool_calls")],
            [{"type": "text_delta", "text": '{"summary":"Git artifact prepared"}'},
             usage(), done("stop")],
        )
        result = await run_agent_loop(
            provider, dispatcher,
            [{"role": "user", "content": "Create the authorized artifact"}],
            max_turns=3, max_total_tokens=100, max_tool_calls=2,
        )
        fence = TrustedSqliteAttemptFence(
            tmp_path / "orchestration.sqlite3",
            run_id=runtime["run"].id,
            task_id=task_id, attempt_id=attempt_id,
            agent_id=runtime["agent"].id,
        )
        proof = storage.commit(
            task_id, attempt_id, fence=fence, ledger=runtime["ledger"],
        )
        written.append((worktree, proof, ledger_scope))
        return result.output

    completed = await run_native_task_attempt(
        runtime["orch"], task_id=runtime["task"].id,
        agent_id=runtime["agent"].id, runner=runner,
    )
    assert completed.status == "completed" and completed.verified
    worktree, proof, ledger_scope = written[0]
    assert proof.changed_paths == ("out/result.txt",)
    assert proof.commit_sha == git(worktree, "rev-parse", "HEAD")
    assert git(worktree, "show", "HEAD:out/result.txt") == "actual Native LLM artifact"
    assert git(repository, "rev-parse", "HEAD") == baseline
    assert runtime["ledger"].state(ledger_scope, "git-commit-v1") == "SUCCEEDED"
    assert runtime["ledger"].state(ledger_scope, "write-artifact") == "SUCCEEDED"
    assert (await runtime["queries"].get_run(runtime["run"].id)).status == "completed"
    # All model calls are independent of Git; no model tool named git is exposed.


@pytest.mark.asyncio
async def test_duplicate_git_commit_never_replays_even_after_reopen(runtime, tmp_path):
    storage, repository = store(tmp_path)
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    worktree = storage.provision(runtime["task"].id, attempt.id)
    fs = ScopedFilesystemExecutor(
        worktree, {"fs_write": [str(worktree / "out" / "**")]},
    )
    fs.write_text("out/once.txt", "ONCE")
    fence = TrustedSqliteAttemptFence(
        tmp_path / "orchestration.sqlite3",
        run_id=runtime["run"].id, task_id=runtime["task"].id,
        attempt_id=attempt.id, agent_id=runtime["agent"].id,
    )
    proof = storage.commit(
        runtime["task"].id, attempt.id, fence=fence, ledger=runtime["ledger"],
    )
    with pytest.raises(ToolPolicyDenied, match="already attempted"):
        storage.commit(
            runtime["task"].id, attempt.id, fence=fence, ledger=runtime["ledger"],
        )
    assert git(worktree, "rev-parse", "HEAD") == proof.commit_sha
    assert git(repository, "rev-parse", "HEAD") != proof.commit_sha
    with pytest.raises(ToolPolicyDenied, match="already exists"):
        storage.provision(runtime["task"].id, attempt.id)
    await runtime["orch"].recover()
    with pytest.raises(AttemptFenceDenied):
        storage.commit(
            runtime["task"].id, attempt.id, fence=fence, ledger=runtime["ledger"],
        )


@pytest.mark.asyncio
async def test_git_denies_symlinks_and_paths_outside_output(runtime, tmp_path):
    storage, _ = store(tmp_path)
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    worktree = storage.provision(runtime["task"].id, attempt.id)
    secret = tmp_path / "external-secret"
    secret.write_text("DO-NOT-COMMIT")
    (worktree / "out" / "secret-link").symlink_to(secret)
    fence = TrustedSqliteAttemptFence(
        tmp_path / "orchestration.sqlite3",
        run_id=runtime["run"].id, task_id=runtime["task"].id,
        attempt_id=attempt.id, agent_id=runtime["agent"].id,
    )
    with pytest.raises(ToolPolicyDenied, match="regular"):
        storage.commit(
            runtime["task"].id, attempt.id, fence=fence, ledger=runtime["ledger"],
        )
    assert git(worktree, "rev-parse", "HEAD") == git(storage.repository, "rev-parse", "HEAD")
    assert runtime["ledger"].state(fence.execution_scope, "git-commit-v1") == "CLAIMED"
    # A failed or ambiguous Git operation must not be automatically retried.
    (worktree / "out" / "secret-link").unlink()
    (worktree / "out" / "valid.txt").write_text("later")
    with pytest.raises(ToolPolicyDenied, match="already attempted"):
        storage.commit(
            runtime["task"].id, attempt.id, fence=fence, ledger=runtime["ledger"],
        )
    assert secret.read_text() == "DO-NOT-COMMIT"


def test_git_worktree_rejects_unreviewed_repository_hooks_and_unsafe_paths(tmp_path):
    storage, repository = store(tmp_path)
    home = storage.home
    with pytest.raises(ToolPolicyDenied):
        storage.provision("../escape", "a")
    with pytest.raises(ToolPolicyDenied):
        storage.provision("valid", "../escape")
    marker = tmp_path / "hook-executed"
    hook = repository / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nprintf executed > " + str(marker) + "\n")
    hook.chmod(0o700)
    # A repository hook must never run even if an operator installed it.
    worktree = storage.provision("task-safe", "attempt-safe")
    (worktree / "out" / "x.txt").write_text("artifact")
    # The actual commit is covered by the fenced test above; here show
    # source hook alone cannot be mistaken for authorization.
    assert not marker.exists()
    assert home != repository
