#!/usr/bin/env bash
# install-gitflow-hooks.sh — install/verify the GitFlow hooks in a worktree/repo.
#
# What it does (idempotent):
#   1. creates/refreshes the `.githooks` symlink at the repo root pointing to
#      scripts/git/gitflow-hooks/ (the single shared, versioned template);
#   2. sets `core.hooksPath=.githooks` for the repository;
#   3. marks every hook executable;
#   4. verifies the result — `core.hooksPath` must resolve to an existing hook
#      directory, otherwise the hooks are configured-but-inert (git silently
#      runs nothing when `core.hooksPath` points into the void).
#
# Usage:
#   bash scripts/install-gitflow-hooks.sh [--repo DIR] [--uninstall|--check]
#
#   --check       verify only; never writes. Exits non-zero when the hooks are
#                 not live (missing/void `core.hooksPath` target).
#   --uninstall   clear `core.hooksPath` and remove the `.githooks` symlink.
#
# Rollback: `bash scripts/install-gitflow-hooks.sh --uninstall`.
set -euo pipefail

REPO=""
UNINSTALL=0
CHECK=0
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="${2:-}"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        --check|--verify) CHECK=1; shift ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$REPO" ]; then
    REPO="$(git rev-parse --show-toplevel)"
fi
REPO="$(cd "$REPO" && pwd)"
HOOKS_SRC="$REPO/scripts/git/gitflow-hooks"
HOOKS_LINK="$REPO/.githooks"
REQUIRED_HOOKS="pre-commit pre-push commit-msg post-merge"

# verify_hooks — report whether the hooks are actually LIVE for $REPO.
# Returns 0 only when core.hooksPath is the canonical '.githooks' AND that path
# resolves to a directory that carries the hook scripts. This is the guard
# against the configured-but-inert state (hooksPath pointing into the void).
verify_hooks() {
    local fail=0
    local configured
    configured="$(git -C "$REPO" config --get core.hooksPath 2>/dev/null || true)"
    if [ "$configured" != ".githooks" ]; then
        echo "[gitflow] not active: core.hooksPath='${configured:-<unset>}' (expected '.githooks')" >&2
        fail=1
    fi
    if [ ! -e "$HOOKS_LINK" ]; then
        echo "[gitflow] not active: $HOOKS_LINK is missing — core.hooksPath points into the void" >&2
        fail=1
    elif [ ! -d "$HOOKS_LINK" ]; then
        echo "[gitflow] not active: $HOOKS_LINK does not resolve to a directory" >&2
        fail=1
    else
        local hook
        for hook in $REQUIRED_HOOKS; do
            if [ ! -f "$HOOKS_LINK/$hook" ]; then
                echo "[gitflow] not active: $HOOKS_LINK/$hook is missing" >&2
                fail=1
            fi
        done
    fi
    if [ "$fail" -eq 0 ]; then
        echo "[gitflow] hooks active in $REPO (hooksPath=$configured -> $HOOKS_LINK)"
    fi
    return "$fail"
}

if [ "$CHECK" = "1" ]; then
    verify_hooks
    exit $?
fi

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

# 4. verify the install actually took (never leave core.hooksPath pointing nowhere)
verify_hooks
