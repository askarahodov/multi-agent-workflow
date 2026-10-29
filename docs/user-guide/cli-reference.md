# CLI Reference

The `hermes-kanban` CLI is the primary interface for managing tasks, boards, and the multi-agent workflow system.

## Installation

```bash
# From source (recommended for development)
pip install -e /path/to/multi-agent-workflow

# Or install globally
pip install hermes-kanban
```

## Global Options

```bash
hermes-kanban [OPTIONS] COMMAND [ARGS]...

Options:
  --board TEXT        Kanban board slug (default: from HERMES_KANBAN_BOARD env or 'default')
  --db-path PATH      Path to Kanban SQLite database (default: data/kanban.db)
  --config PATH       Path to config directory (default: config/)
  -v, --verbose       Enable verbose output
  -q, --quiet         Suppress non-error output
  --help              Show this message and exit
```

## Commands

### Board Management

#### `hermes-kanban board list`
List all boards.

```bash
hermes-kanban board list
```

#### `hermes-kanban board create`
Create a new board.

```bash
hermes-kanban board create --slug my-board --name "My Project Board"
```

#### `hermes-kanban board switch`
Switch active board (updates symlink).

```bash
hermes-kanban board switch --slug my-board
```

#### `hermes-kanban board current`
Show current active board.

```bash
hermes-kanban board current
```

### Task Management

#### `hermes-kanban create`
Create a new task.

```bash
hermes-kanban create [OPTIONS]

Options:
  --title TEXT           Task title (required)
  --assignee TEXT        Assignee profile name (required)
  --body TEXT            Task description/body
  --parents TEXT...      Parent task IDs (comma-separated or multiple)
  --tenant TEXT          Tenant/project namespace
  --priority INTEGER     Priority (default: 0, higher = sooner)
  --workspace-kind       Workspace type: scratch|dir|worktree (default: scratch)
  --workspace-path PATH  Absolute path for dir/worktree workspace
  --project TEXT         Project ID for git worktree
  --triage               Start in triage column (default: false)
  --max-runtime INTEGER  Max runtime seconds (default: no limit)
  --skills TEXT...       Skills to force-load
  --goal-mode            Enable goal loop (default: false)
  --goal-max-turns INT   Max turns for goal mode (default: 20)
  --completion-contract  Completion contract: local-only|OWNER/REPO|PR_URL
  --model TEXT           Override profile model
  --provider TEXT        Provider for overridden model
  --idempotency-key TEXT Prevent duplicate creation
```

**Examples:**
```bash
# Simple task
hermes-kanban create --title "Fix login bug" --assignee sdlc-developer

# Task with dependencies
hermes-kanban create --title "Write tests" --assignee sdlc-tester \
  --parents task-123,task-456

# Git worktree task for PR
hermes-kanban create --title "Feature: New API" --assignee sdlc-developer \
  --workspace-kind worktree --project my-project \
  --completion-contract my-org/my-repo
```

#### `hermes-kanban show`
Show full task details.

```bash
hermes-kanban show --task-id TASK_ID
```

#### `hermes-kanban list`
List tasks with filters.

```bash
hermes-kanban list [OPTIONS]

Options:
  --assignee TEXT      Filter by assignee
  --status TEXT        Filter by status (triage,todo,ready,running,blocked,review,done,archived)
  --tenant TEXT        Filter by tenant
  --include-archived   Include archived tasks
  --limit INTEGER      Max results (default: 50)
```

#### `hermes-kanban complete`
Mark task as done with handoff.

```bash
hermes-kanban complete --task-id TASK_ID [OPTIONS]

Options:
  --summary TEXT       Human-readable summary (1-3 sentences)
  --result TEXT        Short result log line
  --metadata JSON      Structured handoff facts (changed_files, tests_run, etc.)
  --created-cards TEXT Task IDs created during this run
  --artifacts PATH...  Deliverable file paths
```

#### `hermes-kanban request-review`
Hand off for review.

```bash
hermes-kanban request-review --task-id TASK_ID [OPTIONS]

Options:
  --summary TEXT       What was implemented and verified
  --reviewer TEXT      Reviewer profile to assign
  --metadata JSON      Structured facts for reviewer
  --artifacts PATH...  Deliverable files for review
```

#### `hermes-kanban request-changes`
Reviewer requests changes (returns to implementer).

```bash
hermes-kanban request-changes --task-id TASK_ID --reason TEXT
```

#### `hermes-kanban block`
Block a task with reason.

```bash
hermes-kanban block --task-id TASK_ID --reason TEXT --kind dependency|needs_input|capability|transient
```

#### `hermes-kanban unblock`
Unblock a task (orchestrator only).

```bash
hermes-kanban unblock --task-id TASK_ID
```

#### `hermes-kanban comment`
Add comment to task.

```bash
hermes-kanban comment --task-id TASK_ID --body TEXT
```

#### `hermes-kanban heartbeat`
Signal liveness during long operations.

```bash
hermes-kanban heartbeat --task-id TASK_ID [--note TEXT]
```

### Dependency Management

#### `hermes-kanban link`
Add parent→child dependency.

```bash
hermes-kanban link --parent-id PARENT_ID --child-id CHILD_ID
```

### Attachments

#### `hermes-kanban attach`
Attach file to task (base64).

```bash
hermes-kanban attach --task-id TASK_ID --filename FILE --content-base64 BASE64 [--content-type TYPE]
```

#### `hermes-kanban attach-url`
Attach file by URL.

```bash
hermes-kanban attach-url --task-id TASK_ID --url URL [--filename FILE]
```

#### `hermes-kanban attachments`
List task attachments.

```bash
hermes-kanban attachments --task-id TASK_ID
```

### Dispatcher Control

#### `hermes-kanban dispatch start`
Start the dispatcher daemon.

```bash
hermes-kanban dispatch start [--config CONFIG] [--board BOARD]
```

#### `hermes-kanban dispatch stop`
Stop the dispatcher.

```bash
hermes-kanban dispatch stop
```

#### `hermes-kanban dispatch status`
Show dispatcher status.

```bash
hermes-kanban dispatch status
```

### Utilities

#### `hermes-kanban schedule`
Park task in scheduled state.

```bash
hermes-kanban schedule --task-id TASK_ID --until TIMESTAMP
```

#### `hermes-kanban export`
Export board/tasks to JSON.

```bash
hermes-kanban export --board BOARD --output FILE.json
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HERMES_KANBAN_DB` | Database path | `data/kanban.db` |
| `HERMES_KANBAN_BOARD` | Default board slug | `default` |
| `HERMES_TENANT` | Default tenant | (none) |
| `HERMES_CONFIG_DIR` | Config directory | `config/` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Task not found |
| 4 | Permission denied |
| 5 | Database error |
| 6 | Dispatcher not running |

## Examples

### Full Feature Pipeline
```bash
# Create epic
EPIC=$(hermes-kanban create --title "EPIC: Payment Integration" --assignee sdlc-planner --output json | jq -r .id)

# Architect task depends on epic
ARCH=$(hermes-kanban create --title "Design Payment Architecture" --assignee sdlc-architect --parents $EPIC --output json | jq -r .id)

# Developer task depends on architect
DEV=$(hermes-kanban create --title "Implement Payment Module" --assignee sdlc-developer --parents $ARCH --workspace-kind worktree --project payment --output json | jq -r .id)

# Review depends on developer
REV=$(hermes-kanban create --title "Review Payment Implementation" --assignee sdlc-reviewer --parents $DEV --output json | jq -r .id)

# Quality gate depends on review
hermes-kanban create --title "Quality Gate: Payment" --assignee sdlc-tester --parents $REV
```

### Monitor Task Progress
```bash
# Watch task status
watch -n 5 'hermes-kanban show --task-id TASK_ID | head -30'

# Or use the web UI at http://localhost:3000
```

---

*See also: [Getting Started](getting-started.md) | [Configuration](configuration.md) | [Troubleshooting](troubleshooting.md)*