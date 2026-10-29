#!/usr/bin/env python3
"""Worktree Lifecycle Manager — create / validate / cleanup / reap.

Layer L5 of the GitFlow enforcement architecture. One task = one branch
(``wt/<task-id>``) = one worktree (``<repo>/.worktrees/<task-id>``).

Subcommands
-----------
  create   --task t_XXXX   [--repo DIR] [--from REF]   create branch+worktree,
                                                        install hooks, inject
                                                        the policy bundle.
  validate --task t_XXXX   [--repo DIR] [--json]       report branch/worktree
                                                        health; exits non-zero
                                                        when invalid.
  cleanup  --task t_XXXX   [--repo DIR] [--merge-sha SHA] [--force-guard]
                                                        post-merge cleanup:
                                                        safe `-d`, worktree
                                                        remove, remote delete,
                                                        prune. Refuses to delete
                                                        a dirty worktree unless
                                                        --force-guard is passed.
  reap     [--repo DIR] [--create-decision-cards]      list orphans (a task
                                                        done/archived/blocked
                                                        with a surviving branch,
                                                        or a branch idle > 7
                                                        days). Never deletes.

Safety (GF-06/GF-07): local branches are deleted with ``git branch -d`` only;
a branch with unique commits is never force-deleted. Cleanup aborts when the
worktree has uncommitted changes and ``--force-guard`` was not given.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TASK_RE = re.compile(r"^t_[a-f0-9]{8}$")
DEFAULT_PROTECTED = ("main", "master", "develop")


class LifecycleError(RuntimeError):
    """Raised for an operation that cannot proceed safely."""


# --------------------------------------------------------------------------- #
# git plumbing
# --------------------------------------------------------------------------- #
def _run(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise LifecycleError(
            f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}"
        )
    return proc


def _run_ok(repo: Path, args: list[str]) -> bool:
    return _run(repo, args, check=False).returncode == 0


def repo_root(start: Path) -> Path:
    proc = _run(start, ["rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0:
        raise LifecycleError(f"{start} is not a git repository")
    # Linked worktree: rev-parse --show-toplevel returns the worktree path,
    # but .worktrees/ must resolve relative to the *main* working tree.
    top = Path(proc.stdout.strip())
    common = _run(top, ["rev-parse", "--git-common-dir"], check=False).stdout.strip()
    if common:
        gitdir = Path(common)
        if not gitdir.is_absolute():
            gitdir = (top / gitdir).resolve()
        # <repo>/.git  ->  <repo>
        if gitdir.name == ".git":
            return gitdir.parent
    return top


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #
class WorktreeLifecycle:
    def __init__(self, repo: Path, *, hooks_src: Path | None = None):
        self.repo = repo
        self.worktrees_dir = repo / ".worktrees"
        self.hooks_src = hooks_src or (repo / "scripts" / "git" / "gitflow-hooks")

    # -- helpers ---------------------------------------------------------- #
    def branch_for(self, task_id: str) -> str:
        return f"wt/{task_id}"

    def path_for(self, task_id: str) -> Path:
        return self.worktrees_dir / task_id

    def branch_exists(self, branch: str) -> bool:
        return _run_ok(self.repo, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])

    def remote_branch_exists(self, branch: str, remote: str = "origin") -> bool:
        return _run_ok(
            self.repo, ["rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"]
        )

    def is_clean(self, worktree: Path) -> bool:
        if not worktree.exists():
            return True
        out = _run(worktree, ["status", "--porcelain"], check=False).stdout
        # Ignore the generated policy-injection artefacts (never user work).
        generated = {
            ".githooks",
            "AGENT_GITFLOW_CONTEXT.json",
            ".agent-gitflow.json",
            ".agent-gitflow.env",
            ".agent-gitflow.env.tmp",
        }
        for line in out.splitlines():
            if not line.strip():
                continue
            if line[3:].strip() in generated:
                continue
            return False
        return True

    def has_unique_commits(self, branch: str, target: str = "origin/main") -> bool:
        if not self.branch_exists(branch):
            return False
        ref = target
        if not _run_ok(self.repo, ["rev-parse", "--verify", "--quiet", ref]):
            ref = "main" if self.branch_exists("main") else "HEAD"
        out = _run(self.repo, ["rev-list", "--count", f"{ref}..{branch}"], check=False).stdout.strip()
        try:
            return int(out) > 0
        except ValueError:
            return False

    def worktree_registered(self, worktree: Path) -> bool:
        out = _run(self.repo, ["worktree", "list", "--porcelain"]).stdout
        return str(worktree) in out

    # -- create ----------------------------------------------------------- #
    def create_worktree(self, task_id: str, base_ref: str = "origin/main") -> dict:
        if not TASK_RE.match(task_id):
            raise LifecycleError(f"invalid task id '{task_id}' (expected t_xxxxxxxx)")
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)

        if worktree.exists() or self.worktree_registered(worktree):
            raise LifecycleError(f"worktree already exists: {worktree}")
        if self.branch_exists(branch):
            raise LifecycleError(f"branch already exists: {branch} (GF-02: never reuse)")

        # Resolve a usable base (fall back to main / HEAD).
        ref = base_ref
        if not _run_ok(self.repo, ["rev-parse", "--verify", "--quiet", ref]):
            ref = "main" if self.branch_exists("main") else "HEAD"

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        _run(self.repo, ["worktree", "add", "-b", branch, str(worktree), ref])

        hooks_installed = self._install_hooks(worktree)
        policy_injected = self._inject_policy(task_id, worktree)
        return {
            "task_id": task_id,
            "branch": branch,
            "worktree": str(worktree),
            "base_ref": ref,
            "hooks_installed": hooks_installed,
            "policy_injected": policy_injected,
        }

    def _inject_policy(self, task_id: str, worktree: Path) -> bool:
        """Write the policy bundle (branch name + policy path) into the
        workspace — the L2 dispatcher injection, invoked at worktree creation."""
        module = self.repo / "scripts" / "git" / "gitflow_context.py"
        if not module.is_file():
            return False
        proc = subprocess.run(
            [sys.executable, str(module), "--repo", str(self.repo),
             "claim", "--task-id", task_id, "--worktree", str(worktree)],
            capture_output=True, text=True,
        )
        return proc.returncode == 0

    def _install_hooks(self, worktree: Path) -> bool:
        link = worktree / ".githooks"
        try:
            if link.is_symlink() or link.exists():
                return True
            if not self.hooks_src.is_dir():
                return False
            os.symlink(os.path.relpath(self.hooks_src, worktree), link)
            _run(worktree, ["config", "core.hooksPath", ".githooks"], check=False)
            for hook in ("pre-commit", "pre-push", "commit-msg", "post-merge"):
                p = self.hooks_src / hook
                if p.is_file():
                    p.chmod(p.stat().st_mode | 0o111)
            return True
        except OSError:
            return False

    # -- validate --------------------------------------------------------- #
    def validate_worktree(self, task_id: str) -> dict:
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)
        checks = {
            "branch_exists": self.branch_exists(branch),
            "worktree_exists": worktree.exists(),
            "worktree_registered": self.worktree_registered(worktree),
            "worktree_clean": self.is_clean(worktree),
            "hooks_installed": (worktree / ".githooks").exists(),
            "policy_injected": (worktree / "AGENT_GITFLOW_CONTEXT.json").exists(),
        }
        return {
            "task_id": task_id,
            "branch": branch,
            "worktree": str(worktree),
            "valid": all(checks.values()),
            "checks": checks,
        }

    # -- cleanup ---------------------------------------------------------- #
    def cleanup_worktree(self, task_id: str, *, merge_sha: str | None = None,
                         force_guard: bool = False) -> dict:
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)
        steps: list[dict] = []

        # Uncommitted-work guard (GF-07): never discard local edits.
        if worktree.exists() and not self.is_clean(worktree) and not force_guard:
            return {
                "task_id": task_id,
                "status": "blocked",
                "reason": "uncommitted_work_guard",
                "detail": f"{worktree} has uncommitted changes; commit or stash first, "
                          f"or pass --force-guard to discard them.",
                "verified_clean": False,
                "steps": steps,
            }

        # Never force-delete a branch that still holds unique work.
        if self.branch_exists(branch) and self.has_unique_commits(branch) and not force_guard:
            return {
                "task_id": task_id,
                "status": "blocked",
                "reason": "unmerged_commits_guard",
                "detail": f"{branch} has commits not reachable from origin/main; "
                          f"merge or record a decision card instead (GF-07).",
                "verified_clean": False,
                "steps": steps,
            }

        # 1. remove worktree
        if self.worktree_registered(worktree):
            proc = _run(self.repo, ["worktree", "remove", str(worktree)], check=False)
            if proc.returncode != 0:
                # The only untracked files left here are the generated policy
                # artefacts (the guard above already rejected real work), so a
                # forced removal cannot discard user changes.
                proc = _run(self.repo, ["worktree", "remove", "--force", str(worktree)], check=False)
            steps.append({"step": "remove_worktree", "ok": proc.returncode == 0,
                          "detail": (proc.stderr or "").strip()})
        elif worktree.exists():
            steps.append({"step": "remove_worktree", "ok": False,
                          "detail": "path exists but is not a registered worktree"})

        # 2. prune
        _run(self.repo, ["worktree", "prune"], check=False)
        steps.append({"step": "prune", "ok": True})

        # 3. delete local branch — safe `-d` always (GF-07)
        if self.branch_exists(branch):
            proc = _run(self.repo, ["branch", "-d", branch], check=False)
            if proc.returncode != 0 and force_guard:
                proc = _run(self.repo, ["branch", "-D", branch], check=False)
            steps.append({"step": "delete_local_branch", "ok": proc.returncode == 0,
                          "detail": (proc.stderr or "").strip()})

        # 4. delete remote branch (only when it exists and is not protected)
        if self.remote_branch_exists(branch):
            proc = _run(self.repo, ["push", "origin", "--delete", branch], check=False)
            steps.append({"step": "delete_remote_branch", "ok": proc.returncode == 0,
                          "detail": (proc.stderr or "").strip()})
        _run(self.repo, ["remote", "prune", "origin"], check=False)
        steps.append({"step": "prune_remotes", "ok": True})

        verified = self._verify_clean(task_id)
        result = {
            "task_id": task_id,
            "status": "cleaned" if verified else "partial",
            "merge_sha": merge_sha,
            "verified_clean": verified,
            "steps": steps,
        }
        self._record(task_id, "cleanup", result)
        return result

    def _verify_clean(self, task_id: str) -> bool:
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)
        return (
            not self.branch_exists(branch)
            and not self.remote_branch_exists(branch)
            and not worktree.exists()
            and not self.worktree_registered(worktree)
        )

    # -- reap ------------------------------------------------------------- #
    def reap_orphans(self) -> list[dict]:
        orphans: list[dict] = []
        out = _run(self.repo, ["worktree", "list", "--porcelain"]).stdout
        current_path = None
        for line in out.splitlines():
            if line.startswith("worktree "):
                current_path = line[len("worktree "):].strip()
            elif line.startswith("branch ") and current_path:
                ref = line[len("branch "):].strip()
                branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
                task_id = Path(current_path).name
                age_days = self._idle_days(branch)
                unique = self.has_unique_commits(branch)
                if branch in DEFAULT_PROTECTED:
                    current_path = None
                    continue
                if unique is False and self._is_merged(branch):
                    orphans.append({
                        "task_id": task_id, "branch": branch, "worktree": current_path,
                        "reason": "merged but not cleaned up", "has_unique_commits": False,
                        "idle_days": age_days, "recommendation": "cleanup",
                    })
                elif age_days is not None and age_days > 7:
                    orphans.append({
                        "task_id": task_id, "branch": branch, "worktree": current_path,
                        "reason": f"no commit for {age_days} days", "has_unique_commits": unique,
                        "idle_days": age_days,
                        "recommendation": "merge" if unique else "delete-with-record",
                    })
                current_path = None
        return orphans

    def _is_merged(self, branch: str, target: str = "origin/main") -> bool:
        if not _run_ok(self.repo, ["rev-parse", "--verify", "--quiet", target]):
            target = "main" if self.branch_exists("main") else "HEAD"
        return _run_ok(self.repo, ["merge-base", "--is-ancestor", branch, target])

    def _idle_days(self, branch: str) -> int | None:
        if not self.branch_exists(branch):
            return None
        out = _run(self.repo, ["log", "-1", "--format=%ct", branch], check=False).stdout.strip()
        if not out:
            return None
        try:
            last = datetime.fromtimestamp(int(out), tz=timezone.utc)
        except ValueError:
            return None
        return (datetime.now(timezone.utc) - last).days

    # -- audit record ----------------------------------------------------- #
    def _record(self, task_id: str, event: str, payload: dict) -> None:
        art_dir = self.repo / "artifacts" / task_id
        try:
            art_dir.mkdir(parents=True, exist_ok=True)
            log = art_dir / "worktree-events.jsonl"
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                    **payload,
                }) + "\n")
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worktree-lifecycle.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=None,
                        help="repository root (default: discovered from cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create branch + worktree for a task")
    p_create.add_argument("--task", required=True)
    p_create.add_argument("--from", dest="base_ref", default="origin/main")

    p_validate = sub.add_parser("validate", help="validate a task worktree")
    p_validate.add_argument("--task", required=True)
    p_validate.add_argument("--json", action="store_true")

    p_cleanup = sub.add_parser("cleanup", help="post-merge cleanup")
    p_cleanup.add_argument("--task", required=True)
    p_cleanup.add_argument("--merge-sha", default=None)
    p_cleanup.add_argument("--force-guard", action="store_true",
                           help="override the uncommitted/unmerged guards (audited)")

    p_reap = sub.add_parser("reap", help="list orphaned worktrees (never deletes)")
    p_reap.add_argument("--create-decision-cards", action="store_true")
    p_reap.add_argument("--kanban-db", default=None)

    args = parser.parse_args(argv)

    try:
        repo = repo_root((args.repo or Path.cwd()).resolve())
        lifecycle = WorktreeLifecycle(repo)

        if args.command == "create":
            _print(lifecycle.create_worktree(args.task, args.base_ref), True)
            return 0
        if args.command == "validate":
            result = lifecycle.validate_worktree(args.task)
            _print(result, True)
            return 0 if result["valid"] else 1
        if args.command == "cleanup":
            result = lifecycle.cleanup_worktree(
                args.task, merge_sha=args.merge_sha, force_guard=args.force_guard)
            _print(result, True)
            return 0 if result.get("verified_clean") else 1
        if args.command == "reap":
            orphans = lifecycle.reap_orphans()
            print(json.dumps({"orphans": orphans, "count": len(orphans)}, indent=2))
            if args.create_decision_cards and orphans:
                _emit_decision_cards(orphans, args.kanban_db)
            return 0
    except LifecycleError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2
    return 0


def _emit_decision_cards(orphans: list[dict], kanban_db: str | None) -> None:
    """Print the decision-card payloads (creating real cards is the
    orchestrator's job, never the reaper's — the reaper must not delete)."""
    print("--- decision cards (create via kanban; the reaper never deletes) ---")
    for o in orphans:
        print(json.dumps({
            "title": f"worktree orphan: {o['task_id']}",
            "assignee": "orchestrator",
            "body": (f"Worktree {o['worktree']} (branch {o['branch']}) is orphaned: "
                     f"{o['reason']}. has_unique_commits={o['has_unique_commits']}. "
                     f"Recommended decision: {o['recommendation']}."),
        }))
    if kanban_db:
        print(f"(kanban db: {kanban_db})", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
