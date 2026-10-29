#!/usr/bin/env bash

# Agent spawn script for multi-agent orchestration
# Usage: scripts/spawn-agent.sh <task-id> <profile> <branch-name>

# Exit on any error

set -euo pipefail

# Validate arguments
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <task-id> <profile> <branch-name>" >&2
    exit 1
fi

TASK_ID="$1"
PROFILE="$2"
BRANCH_NAME="$3"

# Set up paths (overridable via environment; default to the repository root containing this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${ORCHESTRATION_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
WORKSPACES_ROOT="${WORKSPACES_ROOT:-$PROJECT_ROOT/.worktrees}"
PROJECT_SLUG="${ORCHESTRATION_PROJECT:-$(basename "$PROJECT_ROOT")}"

# Validate project exists
if [ ! -d "$PROJECT_ROOT" ]; then
    echo "Error: Project root not found at $PROJECT_ROOT" >&2
    exit 1
fi

# Create worktree directory
WORKTREE_PATH="$WORKSPACES_ROOT/$TASK_ID"
echo "Creating worktree at: $WORKTREE_PATH"
mkdir -p "$WORKTREE_PATH"

# Check if git is available
if ! command -v git &> /dev/null; then
    echo "Error: git command not found" >&2
    exit 1
fi

# Check if we can access the project git repository
if ! git -C "$PROJECT_ROOT" rev-parse --git-dir > /dev/null 2>&1; then
    echo "Error: Not a git repository at $PROJECT_ROOT" >&2
    exit 1
fi

# Create worktree
if git -C "$PROJECT_ROOT" worktree add "$WORKTREE_PATH" "$PROJECT_SLUG/$TASK_ID" 2>/dev/null; then
    echo "Worktree created successfully"
else
    # If worktree with this task-id already exists, try to use existing one
    echo "Worktree may already exist, checking..."
    if [ ! -d "$WORKTREE_PATH" ]; then
        echo "Error: Could not create worktree and no existing worktree found" >&2
        exit 1
    fi
    echo "Using existing worktree"
fi

# Verify worktree path
if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Error: Worktree path does not exist: $WORKTREE_PATH" >&2
    exit 1
fi

# Create tmux session for agent
tmux_session="agent-$TASK_ID-$BRANCH_NAME"
echo "Creating tmux session: $tmux_session"

# Kill existing session if it exists
if tmux has-session -t "$tmux_session" 2>/dev/null; then
    echo "Killing existing tmux session: $tmux_session"
    tmux kill-session -t "$tmux_session" 2>/dev/null || true
fi

# Create new tmux session with agent process
SESSION_CMD="hermes -p $PROFILE --cli --accept-hooks chat -q \"work kanban task $TASK_ID\""
echo "Starting agent with command: $SESSION_CMD"

echo "$SESSION_CMD" | tmux new-session -d -s "$tmux_session" bash

# Wait a moment for the session to start
sleep 2

# Verify session is running
if tmux has-session -t "$tmux_session" 2>/dev/null; then
    echo "Successfully created tmux session: $tmux_session"
    echo "Worktree path: $WORKTREE_PATH"
    echo "Session command: $SESSION_CMD"
else
    echo "Error: Failed to create tmux session $tmux_session" >&2
    exit 1
fi

# Register worktree path in kanban task metadata (placeholder for now)
# In a real implementation, this would update the kanban task metadata
# with the worktree path for later reference

# --- GitFlow policy injection (L2) -----------------------------------------
# On task claim the dispatcher writes the branch name + policy path into the
# agent workspace and installs the shared hooks. Non-fatal: a failure is logged
# but must not silently disable the task.
if [ -x "$PROJECT_ROOT/scripts/git/dispatcher-policy-hook.sh" ]; then
    "$PROJECT_ROOT/scripts/git/dispatcher-policy-hook.sh" "$TASK_ID" "$WORKTREE_PATH" \
        || echo "WARNING: GitFlow policy injection failed for $TASK_ID" >&2
fi

echo "Agent spawned successfully:"
echo "  Task ID: $TASK_ID"
echo "  Profile: $PROFILE"
echo "  Branch: $BRANCH_NAME"
echo "  Tmux Session: $tmux_session"
echo "  Worktree Path: $WORKTREE_PATH"

echo "To attach to the agent, run:"
echo "  tmux attach-session -t $tmux_session"

echo "To kill the agent, run:"
echo "  tmux kill-session -t $tmux_session"