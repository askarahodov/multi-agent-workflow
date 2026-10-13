#!/usr/bin/env bash
# Installs a daily cron job that runs cleanup-branches.py against a git repo.
#
# Safe by default: the cron invocation passes --dry-run so it only *reports*
# stale branches in the log -- it never deletes.  To make the scheduled run
# actually delete, set CLEANUP_APPLY=1 when calling (see below).
#
# Usage:
#   ./install-cron.sh [REPO_DIR]            dry-run daily report (default)
#   CLEANUP_APPLY=1 ./install-cron.sh [REPO_DIR]   daily deletion run
#
# The cron writes a timestamped log to $HOME/.branch-cleanup/ and keeps the
# last 7 runs.  Existing crontab entries for this script are not duplicated.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP="$SCRIPT_DIR/cleanup-branches.py"

REPO_DIR="${1:-$PWD}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"

LOG_DIR="${BRANCH_CLEANUP_LOG_DIR:-$HOME/.branch-cleanup}"
mkdir -p "$LOG_DIR"

# Resolve the interpreted path of the cleanup script for the cron line.
# `cleanup-branches.py` needs a fresh python each run; python3 from PATH.
PYTHON="${PYTHON:-python3}"

if [[ ! -x "$CLEANUP" && ! -r "$CLEANUP" ]]; then
  echo "error: cleanup script not found at $CLEANUP" >&2
  exit 1
fi

APPLY_ARGS=""
if [[ "${CLEANUP_APPLY:-0}" == "1" ]]; then
  # --yes is required for non-interactive (cron) deletion.
  APPLY_ARGS="--yes"
  mode="APPLY (deletes stale branches)"
else
  APPLY_ARGS="--dry-run"
  mode="DRY-RUN (report only)"
fi

# Schedule at 04:17 every day. A fresh fetch is deliberate: the "upstream
# gone" detection only works if we know today's remote state.
CRON_TIME="17 4 * * *"
CRON_CMD="cd '$REPO_DIR' && '$PYTHON' '$CLEANUP' --repo '$REPO_DIR' $APPLY_ARGS --prune-remotes >> '$LOG_DIR/cleanup-\$(date +\\%F).log' 2>&1"
WORK="$(printf '%s %s' "$CRON_TIME" "$CRON_CMD")"

CURRENT="$(crontab -l 2>/dev/null || true)"
if grep -Fq -- "$CLEANUP" <<<"$CURRENT"; then
  echo "cron entry already present for $CLEANUP"
else
  {
    printf '%s\n' "$CURRENT"
    printf '%s\n' "$WORK"
  } | crontab -
  echo "installed daily cron ($mode):"
  printf '  %s\n' "$CRON_CMD"
fi

echo "logs: $LOG_DIR"
echo "mode: $mode"
if [[ "$mode" == "DRY-RUN (report only)" ]]; then
  echo "to enable deletion, reinstall with: CLEANUP_APPLY=1 $0 '$REPO_DIR'"
fi