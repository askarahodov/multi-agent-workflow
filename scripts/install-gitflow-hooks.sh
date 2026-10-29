#!/usr/bin/env bash
# install-gitflow-hooks.sh — install the GitFlow hooks into a worktree/repo.
#
# What it does (idempotent):
#   1. creates/refreshes the `.githooks` symlink at the repo root pointing to
#      scripts/git/gitflow-hooks/ (the single shared, versioned template);
#   2. sets `core.hooksPath=.githooks` for the repository;
#   3. marks every hook executable.
#
# Usage:
#   bash scripts/install-gitflow-hooks.sh [--repo DIR] [--uninstall]
#
# Rollback: `bash scripts/install-gitflow-hooks.sh --uninstall`.
set -euo pipefail

REPO=""
UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="${2:-}"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$REPO" ]; then
    REPO="$(git rev-parse --show-toplevel)"
fi
REPO="$(cd "$REPO" && pwd)"
HOOKS_SRC="$REPO/scripts/git/gitflow-hooks"
HOOKS_LINK="$REPO/.githooks"

if [ "$UNINSTALL" = "1" ]; then
    git -C "$REPO" config --unset core.hooksPath 2>/dev/null || true
    [ -L "$HOOKS_LINK" ] && rm -f "$HOOKS_LINK"
    echo "[gitflow] hooks uninstalled (core.hooksPath cleared)"
    exit 0
fi

if [ ! -d "$HOOKS_SRC" ]; then
    echo "[gitflow] error: hook template not found at $HOOKS_SRC" >&2
    exit 1
fi

# 1. symlink .githooks -> scripts/git/gitflow-hooks (relative so it is portable)
if [ -e "$HOOKS_LINK" ] && [ ! -L "$HOOKS_LINK" ]; then
    echo "[gitflow] error: $HOOKS_LINK exists and is not a symlink — refusing to overwrite" >&2
    exit 1
fi
ln -sfn scripts/git/gitflow-hooks "$HOOKS_LINK"

# 2. point git at it
git -C "$REPO" config core.hooksPath .githooks

# 3. make hooks executable
chmod +x "$HOOKS_SRC"/pre-commit "$HOOKS_SRC"/pre-push "$HOOKS_SRC"/commit-msg "$HOOKS_SRC"/post-merge 2>/dev/null || true

echo "[gitflow] hooks installed:"
echo "  hooksPath = $(git -C "$REPO" config core.hooksPath)"
echo "  .githooks -> $(readlink "$HOOKS_LINK")"
