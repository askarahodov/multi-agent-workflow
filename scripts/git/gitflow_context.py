#!/usr/bin/env python3
"""Hermes dispatcher integration — inject the GitFlow policy into a task
workspace at claim time (architecture layer L2).

On task claim the dispatcher calls::

    python scripts/git/gitflow_context.py claim --task-id t_xxxx --worktree .worktrees/t_xxxx

which, for the freshly created worktree:

  1. builds a policy bundle from ``AGENT_GITFLOW_RULES.md`` (YAML front-matter)
     and ``gitflow-policy.schema.json``;
  2. writes ``AGENT_GITFLOW_CONTEXT.json`` and ``.agent-gitflow.json`` into the
     workspace — the latter carries the **branch name + policy path** the card
     asks for, so an agent can discover them without the dispatcher env;
  3. installs the ``.githooks`` symlink and sets ``core.hooksPath``;
  4. prints the (shell-sourceable) environment exports:
     ``AGENT_GITFLOW_CONTEXT``, ``AGENT_GITFLOW_RULES_PATH``,
     ``AGENT_GITFLOW_SCHEMA_PATH``.

The subcommand is idempotent and safe to run on a worktree that already has the
bundle; ``--check`` reports whether a workspace is compliant without writing.

``verify`` reports whether the hooks are actually LIVE for the repository root
(or a given worktree): ``core.hooksPath`` must resolve to an existing ``.githooks``
directory. This catches the configured-but-inert state — ``core.hooksPath`` set
to ``.githooks`` while the directory is absent, which makes git silently run no
hooks at all (the exact failure mode in the primary repo, where direct commits
to ``main`` happen).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROTECTED_BRANCHES = ["main", "master", "develop"]
PROTECTED_PREFIXES = ["release/", "hotfix/"]
BRANCH_PATTERN = r"^(wt/t_[a-f0-9]{8}|(feat|fix|docs|chore|refactor|perf|test|security)/[a-z0-9][a-z0-9._-]*|(release|hotfix)/v[0-9]+\.[0-9]+\.[0-9]+)$"
COMMIT_PATTERN = r"^(feat|fix|docs|chore|refactor|perf|test|security|build|ci|revert)(\([^)]+\)): [a-z].{1,71}$"
DEFAULT_VERSION = "1.0"


# --------------------------------------------------------------------------- #
# rules parsing
# --------------------------------------------------------------------------- #
def parse_front_matter(text: str) -> dict:
    """Parse the YAML front-matter of AGENT_GITFLOW_RULES.md.

    Uses PyYAML when available; otherwise a small purpose-built parser good
    enough for the document's flat/list structure. Never raises.
    """
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    body = m.group(1)
    try:  # preferred path
        import yaml  # type: ignore

        data = yaml.safe_load(body)
        if isinstance(data, dict):
            return data
    except Exception:  # pragma: no cover - fallback path
        pass
    return _fallback_parse(body)


def _fallback_parse(body: str) -> dict:
    out: dict = {}
    version = re.search(r"^\s*version:\s*['\"]?([\w.\-]+)['\"]?\s*$", body, re.MULTILINE)
    if version:
        out["version"] = version.group(1)
    rules: list[dict] = []
    rule_iter = re.finditer(
        r"-\s*id:\s*(GF-\d{2})\s*\n\s*description:\s*(.*?)\n\s*enforcement:\s*([\w\-]+)",
        body,
        re.MULTILINE,
    )
    for m in rule_iter:
        rules.append({
            "id": m.group(1),
            "description": m.group(2).strip().strip("'\""),
            "enforcement": m.group(3).strip(),
        })
    if rules:
        out["rules"] = rules
    return out


# --------------------------------------------------------------------------- #
# bundle
# --------------------------------------------------------------------------- #
def repo_root(start: Path) -> Path:
    proc = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{start} is not a git repository")
    top = Path(proc.stdout.strip())
    common = subprocess.run(["git", "-C", str(top), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    if common:
        gitdir = Path(common)
        if not gitdir.is_absolute():
            gitdir = (top / gitdir).resolve()
        if gitdir.name == ".git":
            return gitdir.parent
    return top


def _realpath_within(child: Path, root: Path) -> bool:
    """True when ``child`` resolves to ``root`` or a path inside it.

    SEC-011: policy-bundle paths are consumed by downstream tooling; a symlink
    or ``..`` in any of them must not let a read/write escape the repo/worktree.
    """
    try:
        resolved = child.resolve()
    except OSError:
        return False
    root = root.resolve()
    return resolved == root or root in resolved.parents


def _guard_write_target(path: Path, root: Path) -> None:
    """Refuse to write through a symlink or outside ``root`` (SEC-011)."""
    if path.is_symlink():
        raise RuntimeError(f"SEC-011: refusing to write through symlink {path}")
    if not _realpath_within(path.parent, root):
        raise RuntimeError(f"SEC-011: refusing to write outside {root}: {path}")


def build_policy_bundle(repo: Path, task_id: str, worktree: Path) -> dict:
    rules_path = repo / "AGENT_GITFLOW_RULES.md"
    schema_path = repo / "gitflow-policy.schema.json"

    # SEC-011: the bundle must only ever reference files that resolve inside
    # the repository root, even if either path was replaced by a symlink.
    for label, candidate in (("rules", rules_path), ("schema", schema_path)):
        if candidate.is_symlink() and not _realpath_within(candidate, repo):
            raise RuntimeError(f"policy {label} path escapes the repository root: {candidate}")

    version = DEFAULT_VERSION
    rules: list = []
    if rules_path.is_file():
        parsed = parse_front_matter(rules_path.read_text(encoding="utf-8"))
        version = str(parsed.get("version", version))
        rules = parsed.get("rules", [])

    schema = None
    if schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            schema = None

    return {
        "version": version,
        "rules": rules,
        "schema": schema,
        "task_id": task_id,
        "branch_name": f"wt/{task_id}",
        "worktree_path": str(worktree),
        "protected_branches": PROTECTED_BRANCHES,
        "protected_prefixes": PROTECTED_PREFIXES,
        "commit_pattern": COMMIT_PATTERN,
        "branch_pattern": BRANCH_PATTERN,
        "rules_path": str(rules_path),
        "schema_path": str(schema_path),
    }


def _set_hooks_path(worktree: Path) -> bool:
    """Set core.hooksPath=.githooks and verify the read-back (SEC-010/SEC-002)."""
    subprocess.run(["git", "-C", str(worktree), "config", "core.hooksPath", ".githooks"],
                   capture_output=True)
    got = subprocess.run(["git", "-C", str(worktree), "config", "core.hooksPath"],
                         capture_output=True, text=True).stdout.strip()
    return got == ".githooks"


def _install_hooks(repo: Path, worktree: Path) -> bool:
    hooks_src = repo / "scripts" / "git" / "gitflow-hooks"
    link = worktree / ".githooks"
    # SEC-004: link to the canonical, resolved template and refuse an
    # out-of-tree or pre-existing divergent link.
    target = hooks_src.resolve()
    if not target.is_dir():
        return False
    if link.is_symlink():
        try:
            if link.resolve() != target:
                return False
        except OSError:
            return False
    elif link.exists():
        return False
    else:
        try:
            os.symlink(str(target), link)  # absolute target (SEC-004)
        except OSError:
            return False
    if not _set_hooks_path(worktree):
        return False
    for hook in ("pre-commit", "pre-push", "commit-msg", "post-merge"):
        p = target / hook
        if p.is_file():
            p.chmod(p.stat().st_mode | 0o111)
    return True


def write_workspace_policy(repo: Path, task_id: str, worktree: Path) -> dict:
    if not worktree.is_dir():
        raise RuntimeError(f"worktree does not exist: {worktree}")

    bundle = build_policy_bundle(repo, task_id, worktree)
    context_file = worktree / "AGENT_GITFLOW_CONTEXT.json"
    # SEC-011: never follow a symlink planted in the workspace; keep the write
    # inside the worktree.
    _guard_write_target(context_file, worktree)
    context_file.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

    # The card asks specifically for "branch name + policy path" in the
    # workspace; this compact file carries exactly that.
    pointer = {
        "task_id": task_id,
        "branch_name": bundle["branch_name"],
        "policy_path": bundle["rules_path"],
        "schema_path": bundle["schema_path"],
        "context_path": str(context_file),
        "policy_version": bundle["version"],
    }
    pointer_file = worktree / ".agent-gitflow.json"
    _guard_write_target(pointer_file, worktree)
    pointer_file.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")

    hooks = _install_hooks(repo, worktree)
    return {"bundle": bundle, "pointer": pointer, "hooks_installed": hooks}


def hooks_activation(repo: Path, worktree: Path | None = None) -> dict:
    """Report whether the GitFlow hooks are actually LIVE for ``worktree``.

    Checks ``worktree`` when given, otherwise the repository root — the tree
    where direct commits to a protected branch happen and where a
    configured-but-inert ``core.hooksPath`` is most dangerous. Returns a dict
    with ``active`` True only when ``core.hooksPath`` is the canonical
    ``.githooks`` AND that path resolves to a directory carrying the hooks.

    Git silently runs nothing when ``core.hooksPath`` points at a missing
    directory, so a bare ``git config --get core.hooksPath`` is not enough:
    the target must exist.
    """
    root = worktree if worktree is not None else repo
    configured = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
        capture_output=True, text=True,
    ).stdout.strip()
    target = (root / configured) if configured else None
    checks = {
        "hooks_path_configured": configured == ".githooks",
        "hooks_dir_present": bool(target is not None and target.is_dir()),
        "pre_commit_present": bool(
            target is not None and (target / "pre-commit").is_file()),
    }
    return {
        "root": str(root),
        "hooks_path": configured or None,
        "resolved_target": str(target) if target is not None else None,
        "active": all(checks.values()),
        "checks": checks,
    }


def check_workspace(repo: Path, task_id: str, worktree: Path) -> dict:
    rules_path = repo / "AGENT_GITFLOW_RULES.md"
    hooks = hooks_activation(repo, worktree)
    checks = {
        "worktree_exists": worktree.is_dir(),
        "context_written": (worktree / "AGENT_GITFLOW_CONTEXT.json").is_file(),
        "pointer_written": (worktree / ".agent-gitflow.json").is_file(),
        "hooks_installed": hooks["checks"]["hooks_dir_present"],
        "hooks_active": hooks["active"],
        "rules_path_exists": rules_path.is_file(),
    }
    return {"task_id": task_id, "worktree": str(worktree),
            "compliant": all(checks.values()), "checks": checks, "hooks": hooks}


def _env_exports(bundle: dict) -> str:
    return (
        f"export AGENT_GITFLOW_CONTEXT='{json.dumps(bundle)}'\n"
        f"export AGENT_GITFLOW_RULES_PATH='{bundle['rules_path']}'\n"
        f"export AGENT_GITFLOW_SCHEMA_PATH='{bundle['schema_path']}'\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gitflow_context.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=None, help="repository root")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_claim = sub.add_parser("claim", help="inject the policy into a claimed workspace")
    p_claim.add_argument("--task-id", required=True)
    p_claim.add_argument("--worktree", type=Path, required=True)
    p_claim.add_argument("--emit-env", action="store_true",
                         help="print shell exports instead of JSON")

    p_check = sub.add_parser("check", help="verify a workspace has the policy")
    p_check.add_argument("--task-id", required=True)
    p_check.add_argument("--worktree", type=Path, required=True)

    p_show = sub.add_parser("show", help="print the policy bundle for a task")
    p_show.add_argument("--task-id", required=True)
    p_show.add_argument("--worktree", type=Path, default=None)

    p_verify = sub.add_parser(
        "verify", help="verify the GitFlow hooks are live (repo root by default)")
    p_verify.add_argument("--worktree", type=Path, default=None,
                          help="verify this worktree instead of the repository root")

    args = parser.parse_args(argv)
    try:
        repo = repo_root(args.repo or Path.cwd())
        if args.command == "claim":
            result = write_workspace_policy(repo, args.task_id, args.worktree.resolve())
            if args.emit_env:
                print(_env_exports(result["bundle"]))
            else:
                print(json.dumps(result, indent=2))
            return 0 if result["hooks_installed"] else 1
        if args.command == "check":
            result = check_workspace(repo, args.task_id, args.worktree.resolve())
            print(json.dumps(result, indent=2))
            return 0 if result["compliant"] else 1
        if args.command == "show":
            wt = args.worktree.resolve() if args.worktree else repo / ".worktrees" / args.task_id
            print(json.dumps(build_policy_bundle(repo, args.task_id, wt), indent=2))
            return 0
        if args.command == "verify":
            wt = args.worktree.resolve() if args.worktree else repo
            result = hooks_activation(repo, wt)
            print(json.dumps(result, indent=2))
            return 0 if result["active"] else 1
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
