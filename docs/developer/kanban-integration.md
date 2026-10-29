# Kanban Integration Guide

How to integrate with the Kanban system programmatically and via CLI.

## Overview

The Kanban system is the central coordination layer. All agent communication, task management, and workflow orchestration flow through it.

### Integration Points

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   External      │     │   Kanban API    │     │   Internal      │
│   Systems       │────►│   (REST/CLI)    │◄───►│   Agents        │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌─────────┐  ┌─────────┐  ┌─────────┐
              │ SQLite  │  │ Events  │  │Attachmnt│
              │  (DB)   │  │  (Log)  │  │ (Files) │
              └─────────┘  └─────────┘  └─────────┘
```

---

## CLI Integration

### Basic Commands

```bash
# Create task
TASK_ID=$(hermes-kanban create \
  --title "Build feature" \
  --assignee sdlc-developer \
  --output json | jq -r .id)

# Wait for completion
hermes-kanban wait --task-id $TASK_ID --timeout 300

# Get result
hermes-kanban show --task-id $TASK_ID --output json | jq .result
```

### Scripting with JSON Output

```bash
#!/bin/bash
# create-pipeline.sh

set -euo pipefail

BOARD="${1:-default}"

# Epic
EPIC=$(hermes-kanban create --board "$BOARD" \
  --title "EPIC: $2" \
  --assignee sdlc-planner \
  --output json | jq -r .id)

# Architecture
ARCH=$(hermes-kanban create --board "$BOARD" \
  --title "Architecture: $2" \
  --assignee sdlc-architect \
  --parents "$EPIC" \
  --output json | jq -r .id)

# Development
DEV=$(hermes-kanban create --board "$BOARD" \
  --title "Implementation: $2" \
  --assignee sdlc-developer \
  --parents "$ARCH" \
  --workspace-kind worktree \
  --project "$3" \
  --output json | jq -r .id)

# Review
REV=$(hermes-kanban create --board "$BOARD" \
  --title "Review: $2" \
  --assignee sdlc-reviewer \
  --parents "$DEV" \
  --output json | jq -r .id)

# Quality Gate
hermes-kanban create --board "$BOARD" \
  --title "Quality Gate: $2" \
  --assignee sdlc-tester \
  --parents "$REV" \
  --output json | jq -r .id

echo "Pipeline created: $EPIC → $ARCH → $DEV → $REV → QG"
```

### Monitoring Tasks

```bash
# Watch task progress
watch -n 3 'hermes-kanban show --task-id TASK_ID --output json | jq "{status, assignee, run_count, current_run_id, metadata}"'

# Tail task events
hermes-kanban show --task-id TASK_ID --output json | jq '.events[] | "\(.timestamp) \(.type): \(.message)"' -r
```

---

## REST API Integration

### Authentication

```python
import httpx

class KanbanClient:
    def __init__(self, base_url: str, api_key: str):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0
        )
    
    async def close(self):
        await self.client.aclose()
```

### Task Operations

```python
# Create task
async def create_task(self, board: str, title: str, assignee: str, **kwargs) -> dict:
    payload = {"title": title, "assignee": assignee, **kwargs}
    resp = await self.client.post(f"/boards/{board}/tasks", json=payload)
    resp.raise_for_status()
    return resp.json()

# Get task
async def get_task(self, task_id: str) -> dict:
    resp = await self.client.get(f"/tasks/{task_id}")
    resp.raise_for_status()
    return resp.json()

# Complete task
async def complete_task(self, task_id: str, summary: str, metadata: dict = None, artifacts: list = None):
    payload = {"summary": summary}
    if metadata:
        payload["metadata"] = metadata
    if artifacts:
        payload["artifacts"] = artifacts
    resp = await self.client.post(f"/tasks/{task_id}/complete", json=payload)
    resp.raise_for_status()
    return resp.json()

# Wait for task completion
async def wait_for_task(self, task_id: str, timeout: int = 300, poll: int = 5) -> dict:
    import asyncio
    start = time.time()
    while time.time() - start < timeout:
        task = await self.get_task(task_id)
        if task["status"] in ("done", "blocked", "archived"):
            return task
        await asyncio.sleep(poll)
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")
```

### Webhook Integration

```python
# Receive webhook events
from fastapi import FastAPI, Request, Header, HTTPException
import hmac
import hashlib

app = FastAPI()

WEBHOOK_SECRET = "your-webhook-secret"

@app.post("/webhooks/hermes")
async def hermes_webhook(
    request: Request,
    x_hermes_signature: str = Header(None)
):
    body = await request.body()
    
    # Verify signature
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(f"sha256={expected}", x_hermes_signature or ""):
        raise HTTPException(401, "Invalid signature")
    
    event = await request.json()
    
    # Handle event
    event_type = event["event"]
    task = event["task"]
    
    if event_type == "task.completed":
        await handle_completion(task)
    elif event_type == "task.blocked":
        await handle_blocked(task)
    
    return {"received": True}
```

### Webhook Payload Format

```json
{
  "event": "task.completed",
  "timestamp": "2025-10-16T14:30:00Z",
  "task": {
    "id": "t_abc123",
    "title": "Implement feature",
    "status": "done",
    "assignee": "sdlc-developer",
    "board": "default",
    "metadata": {
      "changed_files": ["src/feature.py"],
      "tests_run": 15,
      "coverage": 94.2
    },
    "result": "Feature implemented with 94.2% coverage"
  }
}
```

---

## Python SDK (Internal)

### Direct Database Access

```python
import aiosqlite
from pathlib import Path

DB_PATH = Path("data/kanban.db")

async def get_task_raw(task_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_tasks_by_status(status: str, board: str = "default"):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE status = ? AND board = ?",
            (status, board)
        )
        return [dict(row) for row in await cursor.fetchall()]
```

### Event Subscription (Polling)

```python
import asyncio

async def watch_tasks(poll_interval: int = 5):
    last_event_id = 0
    
    while True:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM events WHERE id > ? ORDER BY id",
                (last_event_id,)
            )
            events = await cursor.fetchall()
            
            for event in events:
                last_event_id = event["id"]
                yield dict(event)
        
        await asyncio.sleep(poll_interval)
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/kanban-task.yml
name: Kanban Task Automation

on:
  workflow_dispatch:
    inputs:
      task_title:
        description: 'Task title'
        required: true
      assignee:
        description: 'Assignee profile'
        required: true
        type: choice
        options: [sdlc-planner, sdlc-architect, sdlc-developer, sdlc-reviewer, sdlc-tester]

jobs:
  create-task:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install hermes-kanban
        run: pip install hermes-kanban
      
      - name: Create task
        env:
          HERMES_KANBAN_DB: ${{ secrets.KANBAN_DB_URL }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: |
          TASK_ID=$(hermes-kanban create \
            --title "${{ github.event.inputs.task_title }}" \
            --assignee "${{ github.event.inputs.assignee }}" \
            --output json | jq -r .id)
          echo "TASK_ID=$TASK_ID" >> $GITHUB_OUTPUT
      
      - name: Wait for completion
        run: |
          hermes-kanban wait --task-id ${{ steps.create-task.outputs.TASK_ID }} --timeout 1800
      
      - name: Get results
        run: |
          hermes-kanban show --task-id ${{ steps.create-task.outputs.TASK_ID }} --output json
```

### GitLab CI Example

```yaml
# .gitlab-ci.yml
kanban_task:
  stage: deploy
  image: python:3.11
  variables:
    HERMES_KANBAN_DB: $KANBAN_DB_URL
  script:
    - pip install hermes-kanban
    - |
      TASK_ID=$(hermes-kanban create \
        --title "Deploy $CI_COMMIT_REF_NAME" \
        --assignee sdlc-release \
        --output json | jq -r .id)
    - hermes-kanban wait --task-id $TASK_ID --timeout 600
  only:
    - tags
```

---

## Event-Driven Architecture

### Event Types

| Event | Trigger | Payload |
|-------|---------|---------|
| `task.created` | Task created | Task object |
| `task.status_changed` | Status transition | `{from, to, task}` |
| `task.completed` | Task marked done | Task + metadata |
| `task.blocked` | Task blocked | Task + reason + kind |
| `task.unblocked` | Task unblocked | Task |
| `task.review_requested` | Review requested | Task + reviewer |
| `task.changes_requested` | Reviewer requests changes | Task + reason |
| `comment.added` | Comment posted | Comment + task |
| `attachment.uploaded` | File attached | Attachment + task |

### Consuming Events

```python
# Via WebSocket (real-time)
import websockets

async def listen_events():
    async with websockets.connect("ws://localhost:8000/ws/events") as ws:
        async for message in ws:
            event = json.loads(message)
            print(f"{event['event']}: {event['task']['title']}")

# Via Server-Sent Events (HTTP)
import httpx

async def listen_sse():
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", "http://localhost:8000/events") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    print(event)
```

---

## Multi-Tenant Isolation

### Tenant Concept

Tenants provide logical isolation for multi-project environments.

```bash
# Create task in tenant
hermes-kanban create --title "Task" --assignee sdlc-developer --tenant acme-corp

# List tasks for tenant
hermes-kanban list --tenant acme-corp

# Board per tenant
hermes-kanban board create --slug acme-board --tenant acme-corp
```

### API with Tenant

```http
GET /boards?tenant=acme-corp
POST /boards/acme-board/tasks
  { "title": "...", "assignee": "...", "tenant": "acme-corp" }
```

---

## Advanced Patterns

### Dynamic Task Generation

```python
async def generate_subtasks(parent_id: str, spec: dict):
    """Break down a spec into parallel subtasks."""
    tasks = []
    for component in spec["components"]:
        task = await kanban.create_task({
            "title": f"Implement {component['name']}",
            "assignee": "sdlc-developer",
            "parents": [parent_id],
            "metadata": {"component": component}
        })
        tasks.append(task)
    return tasks
```

### Conditional Dependencies

```python
# Task B depends on Task A, but only if A succeeds
# (Automatic - child only promotes to ready when all parents are done)

# For optional dependencies, use metadata
await kanban.create_task({
    "title": "Optional enhancement",
    "assignee": "sdlc-developer",
    "parents": ["t_main"],
    "metadata": {"optional": True, "condition": "main_coverage > 90"}
})
```

### Task Templates

```yaml
# templates/feature-task.yaml
title: "Implement {{feature_name}}"
assignee: sdlc-developer
body: |
  Implement {{feature_name}} per spec:
  {{spec}}
  
  Acceptance criteria:
  {{#each criteria}}
  - {{this}}
  {{/each}}
parents: ["{{arch_task_id}}"]
workspace_kind: worktree
project: "{{project_slug}}"
skills:
  - python
  - test-driven-development
```

```python
# Render template
from jinja2 import Template

template = Template(open("templates/feature-task.yaml").read())
task_spec = template.render(
    feature_name="User Dashboard",
    spec="...",
    criteria=["Loads in <2s", "Responsive", "Accessible"],
    arch_task_id="t_arch123",
    project_slug="my-app"
)

task = yaml.safe_load(task_spec)
await kanban.create_task(task)
```

---

## Troubleshooting Integration

### Common Issues

| Issue | Solution |
|-------|----------|
| `401 Unauthorized` | Check API key / JWT token |
| `404 Board not found` | Verify board slug, check tenant |
| `409 Parent not done` | Wait for parent tasks to complete |
| `429 Rate limited` | Implement exponential backoff |
| `Database locked` | Ensure single dispatcher instance |

### Debugging

```bash
# Enable API debug logging
LOG_LEVEL=DEBUG docker compose restart api

# Inspect raw database
sqlite3 data/kanban.db "SELECT * FROM tasks WHERE id='t_abc123';"

# Trace API calls
curl -v http://localhost:8000/tasks/t_abc123
```

---

*See also: [API Reference](api-reference.md) | [Agent Development](agent-development.md) | [Quality Gates](quality-gates.md)*