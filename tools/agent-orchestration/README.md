# Multi-Agent Orchestration Tooling

Tooling that helps run autonomous multi-agent development workflows on this
repository: per-task git worktree isolation, Kanban-backed coordination, and
hotspot/collision detection so parallel agents do not clobber each other's work.

## Components

### 1. Agent Spawn Script (`scripts/spawn-agent.sh`)
Creates an isolated git worktree per task and spawns an agent process in a
tmux session `<agent-<task-id>-<branch>`.

- Takes `<task-id> <profile> <branch-name>` as arguments.
- Creates worktrees under `.worktrees/<task-id>`.
- Spawns `hermes -p <profile> --cli --accept-hooks chat -q "work kanban task <task-id>"`.
- Validates project structure and git repository access, then reports status.

### 2. Workspace Manager (`orchestration_tools/agent_workspace.py`)
Python module that manages git worktree lifecycles for agent tasks.

- `create_worktree(task_id, branch=None)`: creates an isolated git worktree
  (default branch `{PROJECT_SLUG}/{task_id}`).
- `cleanup_worktree(task_id)`: removes a worktree and its directory.
- `get_agent_status(task_id)`: tmux session, last heartbeat and git status.
- `scan_overlapping_modifications(worktree_paths)`: detects files modified in
  more than one worktree.
- `get_all_worktrees()` / `cleanup_all_worktrees()`: registry helpers.

### 3. Kanban Integration Helpers (`orchestration_tools/kanban_tools.py`)
Python module wrapping the Hermes Kanban CLI for task lifecycle management.

- `create_child_tasks(parent_id, task_specs)`: batch-creates linked child tasks.
- `attach_artifacts(task_id, paths)`: attaches deliverables to a task.
- `get_task_graph(task_id)`: dependency graph for a task.
- `promote_to_ready(task_id, reason)`: moves a task to ready.
- `create_task_with_parents(title, assignee, parent_ids, ...)`: task creation
  with parent dependencies.
- `get_kanaban_task_info(task_id)`: detailed task information.

### 4. Hotspot Detector (`scripts/detect-hotspots.py`)
Scans recent Kanban completions for `metadata.hotspot` flags and cross-checks
them against per-worktree git changes to surface file collisions.

- `load_recent_completions()`: loads recent completions within the scan window.
- `scan_worktrees_for_changes()`: collects modified files per worktree.
- `detect_collisions(...)`: matches hotspot flags against worktree changes.
- `generate_report(...)` / `output_report(...)`: JSON, text or summary output.

## Configuration

Paths and the project slug are no longer hardcoded; they are read from
environment variables and default to the repository that contains this tooling:

| Variable | Purpose | Default |
| --- | --- | --- |
| `ORCHESTRATION_PROJECT_ROOT` | Path to the target repository root | The repo containing this `tools/` tree |
| `ORCHESTRATION_PROJECT` | Project slug used for kanban `--project` and worktree branch prefix | Name (basename) of the project root |
| `ORCHESTRATION_TENANT` | Optional kanban tenant; omitted by default | unset |

`WORKSPACES_ROOT` (for `spawn-agent.sh`) defaults to
`$PROJECT_ROOT/.worktrees` and can be overridden via the environment.

## Usage Examples

**Create a worktree and spawn an agent:**
```bash
./scripts/spawn-agent.sh t_12345 sdlc-developer agents/t_12345
```

**Detect potential file conflicts:**
```bash
./scripts/detect-hotspots.py
```

**Use the workspace manager programmatically:**
```python
from orchestration_tools.agent_workspace import create_worktree, get_agent_status

task_path = create_worktree("t_12345")
status = get_agent_status("t_12345")
```

**Use the Kanban integration helpers:**
```python
from orchestration_tools.kanban_tools import create_child_tasks, attach_artifacts

task_specs = [
    {"title": "Implement backend", "assignee": "sdlc-developer"},
    {"title": "Write tests", "assignee": "sdlc-tester"},
]
child_tasks = create_child_tasks("t_parent", task_specs)

attach_artifacts("t_12345", ["/path/to/report.pdf", "/path/to/analysis.json"])
```

## Directory Structure

```
tools/agent-orchestration/
├── orchestration_tools/
│   ├── __init__.py
│   ├── agent_workspace.py        # Worktree lifecycle + conflict detection
│   └── kanban_tools.py            # Kanban CLI integration helpers
├── scripts/
│   ├── spawn-agent.sh             # Agent spawning (executable)
│   └── detect-hotspots.py         # Hotspot / collision detection (executable)
├── demo_orchestration.py          # Implementation demonstration
└── test_orchestration.py          # Validation tests
```

## Testing

```bash
python tools/agent-orchestration/test_orchestration.py
# or
pytest tools/agent-orchestration/
```

## Status

✅ COMPLETED — all four components implemented and validated.