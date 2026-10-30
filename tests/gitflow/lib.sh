#!/usr/bin/env bash
# lib.sh — hermetic test harness for the GitFlow enforcement suite.
#
# Every test builds a throwaway repository under $TMPDIR and copies the pieces
# of this repository it needs (hooks template, policy registry, lifecycle
# scripts) into it. Nothing under the real working tree is modified, and no
# network access is required, so the suite runs identically on a developer
# machine and in CI.
#
# Usage from a test script:
#   source "$(dirname "$0")/lib.sh"
#   repo="$(new_tmp_repo)"          # git repo on main with one seed commit
#   seed_project_repo "$repo"       # add hooks template + policy registry
#   install_hooks "$repo"           # activate .githooks in $repo
#
# shellcheck shell=bash

set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TEST_DIR/../.." && pwd)"
HOOKS_SRC="$REPO_ROOT/scripts/git/gitflow-hooks"
LOG_DIR="${GITFLOW_TEST_LOGS:-$TEST_DIR/logs}"
mkdir -p "$LOG_DIR"

_TMP_DIRS=()
_cleanup_tmp() {
    local d
    for d in "${_TMP_DIRS[@]:-}"; do
        [ -n "$d" ] && [ -d "$d" ] && rm -rf "$d"
    done
}
trap _cleanup_tmp EXIT

TEST_LOG=""

begin_test() {  # begin_test <name>
    TEST_LOG="$LOG_DIR/$1.log"
    mkdir -p "$LOG_DIR"
    : >"$TEST_LOG"
    echo "TEST: $1" | tee -a "$TEST_LOG"
}

pass() {
    echo "PASS: $*" | tee -a "$TEST_LOG"
}

fail() {
    echo "FAIL: $*" | tee -a "$TEST_LOG" >&2
    exit 1
}

# record <cmd...> — run a command, tee its output into the log, return its code.
record() {
    "$@" 2>&1 | tee -a "$TEST_LOG"
    return "${PIPESTATUS[0]}"
}

new_tmp_repo() {
    local d
    d="$(mktemp -d "${TMPDIR:-/tmp}/gitflow-test.XXXXXX")"
    _TMP_DIRS+=("$d")
    git -C "$d" init -q -b main
    git -C "$d" config user.name "gitflow-test"
    git -C "$d" config user.email "gitflow-test@example.invalid"
    git -C "$d" config commit.gpgsign false
    printf 'seed\n' >"$d/seed.txt"
    git -C "$d" add seed.txt
    git -C "$d" commit -q -m "chore(test): seed commit"
    printf '%s\n' "$d"
}

# seed_project_repo <repo> — copy the real hooks template and policy registry
# into the throwaway repo so lifecycle/context scripts run self-contained.
seed_project_repo() {
    local repo="$1"
    mkdir -p "$repo/scripts/git"
    cp -a "$HOOKS_SRC" "$repo/scripts/git/gitflow-hooks"
    cp -a "$REPO_ROOT/scripts/git/worktree-lifecycle.py" "$repo/scripts/git/"
    cp -a "$REPO_ROOT/scripts/git/gitflow_context.py" "$repo/scripts/git/"
    cp -a "$REPO_ROOT/AGENT_GITFLOW_RULES.md" "$repo/"
    cp -a "$REPO_ROOT/gitflow-policy.schema.json" "$repo/"
}

install_hooks() {
    local repo="$1"
    ln -sfn "$HOOKS_SRC" "$repo/.githooks"
    git -C "$repo" config core.hooksPath .githooks
}

new_bare_remote() {
    local d
    d="$(mktemp -d "${TMPDIR:-/tmp}/gitflow-remote.XXXXXX")"
    _TMP_DIRS+=("$d")
    git -C "$d" init -q --bare
    printf '%s\n' "$d"
}

assert_contains() {  # assert_contains <file-or-string> <needle> <label> <haystack-is-file:0|1>
    local needle="$2" label="$3"
    if [ "${4:-0}" = "1" ]; then
        grep -q -- "$needle" "$1" || fail "$label (expected '$needle' in $1)"
    else
        case "$1" in
            *"$needle"*) ;;
            *) fail "$label (expected '$needle' in output)" ;;
        esac
    fi
}
