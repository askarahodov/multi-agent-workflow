# Getting Started with Multi-Agent Workflow System

The Multi-Agent Workflow System is a production-ready platform for orchestrating autonomous AI agents that collaborate to solve complex software engineering tasks. This guide walks you through installation, configuration, and running your first workflow.

## Prerequisites

Before you begin, ensure you have:

- **Docker** 24.0+ and **Docker Compose** 2.20+
- **Node.js** 20+ (for frontend development)
- **Python** 3.11+ (for backend services)
- **Git** 2.40+
- **OpenRouter API key** (for LLM access) or local model endpoint

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/multi-agent-workflow.git
cd multi-agent-workflow
```

### 2. Configure Environment

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your OpenRouter API key and other settings
```

Required environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key | Yes |
| `DEFAULT_MODEL` | Default LLM model (e.g., `nvidia/nemotron-3-ultra-550b-a55b:free`) | Yes |
| `DATABASE_URL` | SQLite path (default: `sqlite:///data/kanban.db`) | No |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | No |

### 3. Start the Stack

```bash
docker compose up -d
```

This starts all services:
- **API Gateway** (port 8000) — REST API for task management
- **Frontend** (port 3000) — Web UI for monitoring and control
- **Kanban Database** — SQLite-backed task board
- **Worker Pool** — Autonomous agent workers

### 4. Verify Installation

```bash
# Check service health
curl http://localhost:8000/health
# Expected: {"status": "healthy"}

# Open the web UI
open http://localhost:3000
```

### 5. Create Your First Task

Via the web UI:
1. Navigate to **Boards** → **Create Board**
2. Click **New Task** → Fill in title, assignee (e.g., `sdlc-developer`), and description
3. Click **Create** — the dispatcher will spawn an agent to work on it

Via CLI:
```bash
# Install the CLI tool
pip install -e .

# Create a task
hermes-kanban create \
  --title "Implement Fibonacci function" \
  --assignee sdlc-developer \
  --body "Create src/fibonacci.py with iterative implementation and tests"
```

## Core Concepts

### Kanban Boards
Tasks are organized on Kanban boards with columns: `triage` → `todo` → `ready` → `running` → `review` → `done` / `blocked` / `archived`.

### Agents (Profiles)
Each agent runs with a specific **profile** that defines its capabilities:
- `sdlc-planner` — Task decomposition and planning
- `sdlc-architect` — Technical design and architecture decisions
- `sdlc-developer` — Code implementation and testing
- `sdlc-reviewer` — Code review and quality gates
- `sdlc-tester` — Test execution and validation
- `sdlc-release` — Release automation
- `sdlc-security` — Security scanning

### Task Lifecycle
1. **Created** — Task enters `triage` or `todo`
2. **Dispatched** — When dependencies met, moves to `ready` → `running`
3. **Executed** — Agent works in isolated workspace (git worktree or temp dir)
4. **Reviewed** — Moves to `review` for quality gates
5. **Completed** — Marked `done` with handoff metadata

### Workspaces
Each task runs in an isolated workspace:
- **Scratch** (default) — Temporary directory, cleaned on completion
- **Dir** — Shared directory for persistent state
- **Worktree** — Git worktree with dedicated branch

## Configuration Deep Dive

### Agent Profiles (`config/profiles/`)
Each profile defines:
- **Model** — LLM to use (provider + model name)
- **Tools** — Available toolsets (kanban, terminal, web, etc.)
- **Skills** — Pre-loaded procedural knowledge
- **Prompt** — System prompt with role instructions

Example (`config/profiles/sdlc-developer.yaml`):
```yaml
name: sdlc-developer
model:
  provider: openrouter
  name: nvidia/nemotron-3-ultra-550b-a55b:free
tools:
  - kanban
  - terminal
  - read_file
  - write_file
  - patch
  - search_files
skills:
  - python
  - test-driven-development
  - systematic-debugging
prompt: |
  You are DEVELOPER, a senior-level autonomous software engineering agent...
```

### Quality Gates (`quality-gates/`)
Automated checks that run at each stage:
- **Security Gate** — Dependency scan, secret detection, SAST
- **Review Gate** — Linting (ruff, mypy), formatting, diff review
- **Quality Gate** — Unit tests (≥80% coverage), integration tests

### Kanban Database
SQLite database at `data/kanban.db` with tables:
- `tasks` — Task metadata, status, assignee
- `dependencies` — Parent-child task relationships
- `events` — Audit log of all state transitions
- `attachments` — File artifacts linked to tasks

## Common Workflows

### Feature Development
```bash
# 1. Planner creates epic breakdown
hermes-kanban create --title "EPIC: User Auth" --assignee sdlc-planner

# 2. Architect designs solution
hermes-kanban create --title "Design Auth Architecture" --assignee sdlc-architect --parents <planner-task-id>

# 3. Developer implements
hermes-kanban create --title "Implement Auth Module" --assignee sdlc-developer --parents <architect-task-id>

# 4. Reviewer validates
hermes-kanban create --title "Review Auth Implementation" --assignee sdlc-reviewer --parents <developer-task-id>

# 5. Tester runs quality gate
hermes-kanban create --title "Quality Gate: Auth" --assignee sdlc-tester --parents <reviewer-task-id>
```

### Bug Fix
```bash
# Direct assignment to developer with triage
hermes-kanban create --title "Fix: Memory leak in worker pool" \
  --assignee sdlc-developer --initial-status triage
```

### Release Process
```bash
# Release agent creates RC tag
hermes-kanban create --title "Release v0.1.0-rc1" --assignee sdlc-release \
  --completion-contract OWNER/REPO
```

## Troubleshooting Quick Reference

| Issue | Solution |
|-------|----------|
| Services won't start | Check `docker compose logs`, verify ports 3000/8000 free |
| Agent fails to spawn | Check OpenRouter quota, verify model name in profile |
| Task stuck in `running` | Check worker logs: `docker compose logs worker-<id>` |
| Kanban DB locked | Ensure only one dispatcher process runs |
| Tests fail in workspace | Inspect workspace at `.worktrees/<task-id>/` |

## Next Steps

- Read [CLI Reference](cli-reference.md) for all commands
- See [Configuration](configuration.md) for advanced settings
- Review [Architecture Overview](architecture-overview.md) for system design
- Check [Troubleshooting](troubleshooting.md) for common issues

---

*Last updated: 2025-10-16 | Version: 0.1.0-rc1*