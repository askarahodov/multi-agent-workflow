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
                                                        safe `-d`, worktree removal and
                                                        verified remote absence.
                                                        Never bypasses guards.
  reap     [--repo DIR] [--create-decision-cards]      list orphans (a task
                                                        done/archived/blocked
                                                        with a surviving branch,
                                                        or a branch idle > 7
                                                        days). Never deletes.

Safety (GF-06/GF-07): local branches are deleted with ``git branch -d`` only;
a branch with unique commits is never force-deleted. Cleanup aborts when the worktree has uncommitted changes.
The legacy ``--force-guard`` option never overrides safety.
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

    def _generated_policy_files(self, worktree: Path) -> list[Path] | None:
        """Return only recognized generated untracked metadata; fail closed.

        Tracked changes, ignored user data, foreign symlinks, malformed policy
        metadata, and failed status queries are not disposable.
        """
        proc = _run(worktree, ["status", "--porcelain=v1", "-z",
                               "--untracked-files=all", "--ignored=matching"], check=False)
        if proc.returncode != 0:
            return None
        generated = []
        task_id = worktree.name
        for entry in proc.stdout.split("\0"):
            if not entry:
                continue
            if not entry.startswith(("?? ", "!! ")):
                return None
            name = entry[3:]
            path = worktree / name
            if name == ".githooks":
                if not path.is_symlink() or path.resolve() != self.hooks_src.resolve():
                    return None
            elif name == ".agent-gitflow.env":
                # Dispatcher writes _env_exports(bundle) followed by print's
                # newline. Compare exact text to saved policy metadata; never
                # source or execute the file, nor accept unknown exports.
                context_file = worktree / "AGENT_GITFLOW_CONTEXT.json"
                if (path.is_symlink() or not path.is_file()
                        or context_file.is_symlink() or not context_file.is_file()):
                    return None
                try:
                    bundle = json.loads(context_file.read_text(encoding="utf-8"))
                    if (not isinstance(bundle, dict)
                            or bundle.get("task_id") != task_id
                            or bundle.get("branch_name") != self.branch_for(task_id)
                            or bundle.get("worktree_path") != str(worktree.resolve())
                            or bundle.get("rules_path") != str(self.repo / "AGENT_GITFLOW_RULES.md")
                            or bundle.get("schema_path") != str(self.repo / "gitflow-policy.schema.json")):
                        return None
                    expected = (
                        f"export AGENT_GITFLOW_CONTEXT='{json.dumps(bundle)}'\n"
                        f"export AGENT_GITFLOW_RULES_PATH='{bundle['rules_path']}'\n"
                        f"export AGENT_GITFLOW_SCHEMA_PATH='{bundle['schema_path']}'\n\n"
                    )
                    if path.read_bytes() != expected.encode("utf-8"):
                        return None
                except (OSError, ValueError, KeyError):
                    return None
            elif name in ("AGENT_GITFLOW_CONTEXT.json", ".agent-gitflow.json"):
                if path.is_symlink() or not path.is_file():
                    return None
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None
                if (not isinstance(data, dict) or data.get("task_id") != task_id
                        or data.get("branch_name") != self.branch_for(task_id)):
                    return None
            else:
                return None
            generated.append(path)
        return generated

    def is_clean(self, worktree: Path) -> bool:
        if not worktree.exists():
            return True
        return self._generated_policy_files(worktree) is not None

    def _has_origin(self) -> bool:
        return "origin" in _run(self.repo, ["remote"]).stdout.splitlines()

    def _cleanup_target(self) -> str:
        # A configured origin must be freshly fetched and have a published main.
        # Local-only repositories can use their local main; never fall back to
        # HEAD or an unpublished local merge when origin is configured.
        if self._has_origin():
            _run(self.repo, ["fetch", "--prune", "origin"])
            target = "refs/remotes/origin/main"
        else:
            target = "refs/heads/main"
        if not _run_ok(self.repo, ["rev-parse", "--verify", "--quiet", target]):
            raise LifecycleError(f"cleanup target is unavailable: {target}")
        return target

    def _published_branch(self, branch: str) -> str | None:
        if not self._has_origin():
            return None
        ref = f"refs/heads/{branch}"
        proc = _run(self.repo, ["ls-remote", "--exit-code", "--heads", "origin", ref], check=False)
        if proc.returncode == 2:
            return None
        if proc.returncode != 0:
            raise LifecycleError("could not verify remote branch; cleanup blocked")
        rows = [line.split() for line in proc.stdout.splitlines() if line]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
            raise LifecycleError("unexpected remote branch response")
        return rows[0][0]

    def has_unique_commits(self, branch: str, target: str = "origin/main") -> bool:
        if not self.branch_exists(branch):
            return False
        ref = target
        if not _run_ok(self.repo, ["rev-parse", "--verify", "--quiet", ref]):
            if self._has_origin() or not self.branch_exists("main"):
                return True
            ref = "main"
        return not _run_ok(self.repo, ["merge-base", "--is-ancestor", branch, ref])

    def worktree_registered(self, worktree: Path) -> bool:
        out = _run(self.repo, ["worktree", "list", "--porcelain"]).stdout
        return f"worktree {worktree}" in out.splitlines()

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
            # SEC-004: the symlink target must resolve to the canonical
            # `scripts/git/gitflow-hooks` template. `resolve()` follows any
            # symlink in hooks_src, so an out-of-tree or attacker-controlled
            # target is refused instead of being linked into the worktree.
            hooks_root = (self.repo / "scripts" / "git" / "gitflow-hooks").resolve()
            target = self.hooks_src.resolve()
            if target != hooks_root and hooks_root not in target.parents:
                return False
            if link.is_symlink():
                # A pre-existing link is trusted only when it already points at
                # the contained template (never re-link blindly).
                if link.resolve() != target:
                    return False
            elif link.exists():
                return False
            if not target.is_dir():
                return False
            if not link.exists():
                # Absolute target so the link cannot be re-pointed by cwd tricks.
                os.symlink(str(target), link)
            if not self._set_hooks_path(worktree):
                return False
            for hook in ("pre-commit", "pre-push", "commit-msg", "post-merge"):
                p = target / hook
                if p.is_file():
                    p.chmod(p.stat().st_mode | 0o111)
            return True
        except OSError:
            return False

    def _set_hooks_path(self, worktree: Path) -> bool:
        """Set core.hooksPath and read it back (SEC-010/SEC-002).

        A silent write failure (or a pre-existing overriding value) would
        disable enforcement, so the value is verified before trusting it.
        """
        _run(worktree, ["config", "core.hooksPath", ".githooks"], check=False)
        got = _run(worktree, ["config", "core.hooksPath"], check=False).stdout.strip()
        return got == ".githooks"

    # -- validate --------------------------------------------------------- #
    def validate_worktree(self, task_id: str) -> dict:
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)
        hooks_path = ""
        if worktree.exists():
            hooks_path = _run(worktree, ["config", "core.hooksPath"], check=False).stdout.strip()
        checks = {
            "branch_exists": self.branch_exists(branch),
            "worktree_exists": worktree.exists(),
            "worktree_registered": self.worktree_registered(worktree),
            "worktree_clean": self.is_clean(worktree),
            "hooks_installed": (worktree / ".githooks").exists(),
            # SEC-010/SEC-002: the read-back must still be the canonical value.
            "hooks_path_valid": hooks_path == ".githooks",
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
        if not TASK_RE.fullmatch(task_id):
            raise LifecycleError("invalid task id")
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)
        steps: list[dict] = []

        def blocked(reason: str, detail: str) -> dict:
            result = {"task_id": task_id, "status": "blocked", "reason": reason,
                      "detail": detail, "verified_clean": False, "steps": steps}
            self._record(task_id, "cleanup", result)
            return result

        # Legacy --force-guard is deliberately powerless. Neither a hook nor
        # a CLI flag may waive GF-07. Worktree paths must belong to this task.
        if worktree.is_symlink() or self.worktrees_dir.is_symlink():
            return blocked("worktree_path_guard", "symlinked worktree path")
        if worktree.exists():
            if not self.worktree_registered(worktree):
                return blocked("worktree_path_guard", "unregistered worktree path")
            actual = _run(worktree, ["symbolic-ref", "--quiet", "HEAD"], check=False)
            if actual.returncode != 0 or actual.stdout.strip() != f"refs/heads/{branch}":
                return blocked("worktree_path_guard", "worktree is not on the task branch")
            if not self.is_clean(worktree):
                return blocked("uncommitted_work_guard", "uncommitted or unknown work; preserve and review")
        try:
            target = self._cleanup_target()
            if merge_sha and (not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", merge_sha)
                              or not _run_ok(self.repo, ["merge-base", "--is-ancestor", merge_sha, target])):
                return blocked("merge_receipt_guard", "merge SHA is not reachable from the verified target")
            if self.branch_exists(branch) and self.has_unique_commits(branch, target):
                return blocked("unmerged_commits_guard", "unique work or unverified squash receipt; retain")
            remote_tip = self._published_branch(branch)
        except LifecycleError as exc:
            return blocked("remote_verification_guard", str(exc))

        # GitHub normally deletes merged heads itself. A surviving remote ref
        # may be a stacked PR base or have concurrent new work. This host
        # cannot prove PR dependency/merge evidence, so never push --delete
        # from a post-merge hook. Preserve the local copy pending remote audit.
        if remote_tip is not None:
            return blocked("remote_branch_pending_cleanup",
                           f"remote {branch} still exists at {remote_tip}; verify PRs and cleanup separately")

        if worktree.exists():
            generated = self._generated_policy_files(worktree)
            if generated is None:
                return blocked("uncommitted_work_guard", "worktree changed during cleanup")
            # Remove only task-generated metadata recognized above. Do not
            # use worktree remove --force, even for an apparently clean tree.
            for path in generated:
                try:
                    path.unlink()
                except OSError as exc:
                    return blocked("metadata_cleanup_guard", str(exc))
            proc = _run(self.repo, ["worktree", "remove", str(worktree)], check=False)
            steps.append({"step": "remove_worktree", "ok": proc.returncode == 0,
                          "detail": (proc.stderr or "").strip()})
            if proc.returncode != 0:
                return blocked("worktree_remove_guard", "safe worktree removal refused")
        elif self.worktree_registered(worktree):
            return blocked("worktree_path_guard", "registered worktree is missing; manual triage required")

        if self.branch_exists(branch):
            # Re-evaluate ancestry immediately before safe -d.
            if self.has_unique_commits(branch, target):
                return blocked("unmerged_commits_guard", "branch changed during cleanup")
            proc = _run(self.repo, ["branch", "-d", "--", branch], check=False)
            steps.append({"step": "delete_local_branch", "ok": proc.returncode == 0,
                          "detail": (proc.stderr or "").strip()})
            if proc.returncode != 0:
                return blocked("local_branch_remove_guard", "safe branch removal refused")
        if self._has_origin():
            proc = _run(self.repo, ["remote", "prune", "origin"], check=False)
            steps.append({"step": "prune_remotes", "ok": proc.returncode == 0,
                          "detail": (proc.stderr or "").strip()})
            if proc.returncode != 0:
                return blocked("remote_verification_guard", "remote prune failed")
        try:
            verified = self._verify_clean(task_id)
        except LifecycleError as exc:
            return blocked("remote_verification_guard", str(exc))
        result = {"task_id": task_id, "status": "cleaned" if verified else "partial",
                  "merge_sha": merge_sha, "verified_clean": verified, "steps": steps}
        self._record(task_id, "cleanup", result)
        return result

    def _verify_clean(self, task_id: str) -> bool:
        branch = self.branch_for(task_id)
        worktree = self.path_for(task_id)
        return (
            not self.branch_exists(branch)
            and self._published_branch(branch) is None
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
                           help="deprecated compatibility option; never bypasses cleanup guards")

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
