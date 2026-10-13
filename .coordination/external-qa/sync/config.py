"""Configuration for the local Kanban <-> external QA synchronizer."""
import os
from pathlib import Path

# --- Filesystem / repo ---
HERMES_ROOT = Path("/home/askarahodov/.hermes")
REPO = Path("/mnt/data/multi-agent-workflow")
# Overridable for acceptance tests so the real branch/responses.md stay untouched.
BRANCH = os.environ.get("QASYNC_BRANCH", "coord/external-qa")
CONTACT_REL = ".coordination/external-qa"

SERVICE_DIR = Path("/home/askarahodov/.hermes/qa-sync")
STATE_DB = SERVICE_DIR / "state.db"
LOG_DIR = SERVICE_DIR / "logs"
# Dedicated temporary publish worktree, OUTSIDE the repo tree so it never
# collides with active agent worktrees. Never reuse wt/t_*.
PUBLISH_WT = SERVICE_DIR / "publish-wt"
LOCK_FILE = SERVICE_DIR / "sync.lock"

# Explicit agent identity for synchronization commits (operator identity is a human).
GIT_NAME = "Hermes QA Sync"
GIT_EMAIL = "qa-sync@hermes.local"

# --- Kanban sources ---
KANBAN_TOP = HERMES_ROOT / "kanban.db"              # board "default"
KANBAN_BOARDS_DIR = HERMES_ROOT / "kanban" / "boards"
GATEWAY_LOG = HERMES_ROOT / "logs" / "gateway.log"

# --- Behaviour ---
LOCK_TTL_SECONDS = 1800          # steal a stale lock after 30 min
PUSH_RETRIES = 3                 # bounded non-fast-forward retries
MAX_REQ_PER_PASS = 3             # never flood requests.md in one pass
GITHUB_REPO = "askarahodov/multi-agent-workflow"
