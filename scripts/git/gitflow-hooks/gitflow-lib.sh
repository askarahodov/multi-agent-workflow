#!/usr/bin/env bash
# gitflow-lib.sh — shared helpers for the GitFlow enforcement hooks.
#
# Source this file from a hook (pre-commit, pre-push, post-merge, commit-msg).
# It is intentionally dependency-free (POSIX-ish bash + git) so it runs in any
# worktree without the repository's Python environment.
#
# Policy source of truth: AGENT_GITFLOW_RULES.md (YAML front-matter) and
# gitflow-policy.schema.json. The constants below mirror those artefacts; the
# CI job `gitflow-policy.yml` validates that they stay in sync.
#
# shellcheck shell=bash

# --- constants -------------------------------------------------------------

# Branches that must never receive a direct push / commit (GF-05).
GITFLOW_PROTECTED_BRANCHES='main master develop'
GITFLOW_PROTECTED_PREFIXES='release/ hotfix/'

# Agent task branches: wt/<task-id> where task-id is t_ + 8 hex chars (GF-02).
GITFLOW_AGENT_BRANCH_RE='^wt/t_[a-f0-9]{8}$'

# Human / explicitly directed branches (AGENT_GITFLOW_RULES.md §1.2).
GITFLOW_HUMAN_BRANCH_RE='^(feat|fix|docs|chore|refactor|perf|test|security)/[a-z0-9][a-z0-9._-]*$'
GITFLOW_RELEASE_BRANCH_RE='^(release|hotfix)/v[0-9]+\.[0-9]+\.[0-9]+$'

# Conventional Commits with a mandatory task/subsystem scope (GF-04).
GITFLOW_COMMIT_RE='^(feat|fix|docs|chore|refactor|perf|test|security|build|ci|revert)(\([^)]+\)): [a-z].{1,71}$'
GITFLOW_COMMIT_TYPES='feat fix docs chore refactor perf test security build ci revert'
GITFLOW_COMMIT_MAX=72

GITFLOW_BRANCH_HINT="Agent branch: wt/t_XXXXXXXX (task id). Human branch: feat/|fix/|docs/|chore/|refactor/|perf/|test/|security/<scope>, release/vX.Y.Z, hotfix/vX.Y.Z."
GITFLOW_COMMIT_HINT="<type>(<scope>): <imperative summary>  (types: ${GITFLOW_COMMIT_TYPES}; summary lower-case, no trailing period, <= ${GITFLOW_COMMIT_MAX} chars). Example: feat(t_5ba84eb3): add gitflow hooks"

# --- output helpers --------------------------------------------------------

gf_error() { printf '\033[31m[gitflow]\033[0m %s\n' "$*" >&2; }
gf_warn()  { printf '\033[33m[gitflow]\033[0m %s\n' "$*" >&2; }
gf_info()  { printf '\033[36m[gitflow]\033[0m %s\n' "$*" >&2; }

# --- predicate helpers -----------------------------------------------------

# is_protected_branch <branch-or-ref>
# Accepts a short branch name ("main") or a full ref ("refs/heads/main").
is_protected_branch() {
    local branch="${1:-}"
    branch="${branch#refs/heads/}"
    local b
    for b in $GITFLOW_PROTECTED_BRANCHES; do
        [ "$branch" = "$b" ] && return 0
    done
    local p
    for p in $GITFLOW_PROTECTED_PREFIXES; do
        case "$branch" in
            "$p"*) return 0 ;;
        esac
    done
    return 1
}

# validate_branch_name <branch>
# Returns 0 when the branch name is policy-compliant, 1 otherwise.
validate_branch_name() {
    local branch="${1:-}"
    branch="${branch#refs/heads/}"
    [ -z "$branch" ] && return 1
    if is_protected_branch "$branch"; then
        # Protected branches are valid *ref names*; callers decide separately
        # whether committing/pushing to them is allowed.
        return 0
    fi
    [[ "$branch" =~ $GITFLOW_AGENT_BRANCH_RE ]] && return 0
    [[ "$branch" =~ $GITFLOW_HUMAN_BRANCH_RE ]] && return 0
    [[ "$branch" =~ $GITFLOW_RELEASE_BRANCH_RE ]] && return 0
    return 1
}

# validate_commit_message <message>
# Returns 0 when the subject line is a valid Conventional Commit.
validate_commit_message() {
    local subject="${1%%$'\n'*}"
    [[ "$subject" =~ $GITFLOW_COMMIT_RE ]] && return 0
    return 1
}

# get_task_id_from_branch <branch>
# Echoes the task id (t_xxxxxxxx) when the branch is an agent branch.
get_task_id_from_branch() {
    local branch="${1:-}"
    branch="${branch#refs/heads/}"
    if [[ "$branch" =~ ^wt/(t_[a-f0-9]{8})$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

# gitflow_current_branch — short symbolic branch name, empty when detached.
gitflow_current_branch() {
    git symbolic-ref --quiet --short HEAD 2>/dev/null || true
}

# gitflow_repo_root — top level of the worktree the hook is running in.
gitflow_repo_root() {
    git rev-parse --show-toplevel 2>/dev/null || true
}

# trigger_cleanup <task-id> [merge-sha]
# Best-effort cleanup invocation used by post-merge. Never fatal.
trigger_cleanup() {
    local task_id="${1:-}"
    local merge_sha="${2:-}"
    [ -z "$task_id" ] && return 0
    local root
    root="$(gitflow_repo_root)"
    local mgr="$root/scripts/git/worktree-lifecycle.py"
    if [ -f "$mgr" ]; then
        gf_info "triggering post-merge cleanup for $task_id"
        python3 "$mgr" cleanup --task "$task_id" ${merge_sha:+--merge-sha "$merge_sha"} --force-guard 2>&1 || \
            gf_warn "post-merge cleanup for $task_id did not complete; run 'make gitflow-reap' to triage"
    fi
}
