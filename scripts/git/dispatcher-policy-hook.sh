#!/usr/bin/env bash
# dispatcher-policy-hook.sh — entry point the Hermes task dispatcher calls on
# task claim, after the worktree exists.
#
# Usage (from the dispatcher spawn path):
#   scripts/git/dispatcher-policy-hook.sh <task-id> <worktree-path>
#
# It injects the GitFlow policy bundle (env + files) into the workspace and
# installs the hooks. Non-fatal by design: a policy-injection failure must be
# visible in the worker log, not silently disable the task.
set -u

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <task-id> <worktree-path>" >&2
    exit 2
fi

TASK_ID="$1"
WORKTREE="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$WORKTREE" rev-parse --show-toplevel 2>/dev/null || git -C "$SCRIPT_DIR/../.." rev-parse --show-toplevel)"

echo "[gitflow] injecting policy for $TASK_ID into $WORKTREE"
python3 "$REPO_ROOT/scripts/git/gitflow_context.py" \
    --repo "$REPO_ROOT" \
    claim --task-id "$TASK_ID" --worktree "$WORKTREE" --emit-env > "$WORKTREE/.agent-gitflow.env.tmp" \
  && mv "$WORKTREE/.agent-gitflow.env.tmp" "$WORKTREE/.agent-gitflow.env" \
  && echo "[gitflow] policy injected (source $WORKTREE/.agent-gitflow.env)" \
  || { echo "[gitflow] WARNING: policy injection failed for $TASK_ID" >&2; exit 1; }
