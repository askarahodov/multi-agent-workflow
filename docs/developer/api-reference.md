# API Reference

Complete REST API reference for the Multi-Agent Workflow System.

## Base URL

```
Development:  http://localhost:8000
Production:   https://api.your-domain.com
```

## Authentication

### API Key (Recommended for Automation)
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8000/boards
```

### JWT Token (Web UI)
```bash
# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}'

# Response: {"access_token": "eyJ...", "token_type": "bearer"}

# Use token
curl -H "Authorization: Bearer eyJ..." \
  http://localhost:8000/boards
```

### Scopes
| Scope | Permissions |
|-------|-------------|
| `tasks:read` | List/view tasks |
| `tasks:write` | Create/update tasks |
| `tasks:admin` | Block/unblock, delete tasks |
| `boards:read` | List/view boards |
| `boards:write` | Create/update boards |
| `boards:admin` | Delete boards |
| `admin` | All permissions |

---

## Boards

### List Boards
```http
GET /boards
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `tenant` | string | - | Filter by tenant |
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |

**Response (200):**
```json
{
  "boards": [
    {
      "slug": "default",
      "name": "Default Board",
      "tenant": null,
      "task_count": 42,
      "created_at": "2025-01-15T10:30:00Z",
      "updated_at": "2025-10-16T11:36:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### Create Board
```http
POST /boards
Content-Type: application/json
```

**Request Body:**
```json
{
  "slug": "my-project",
  "name": "My Project Board",
  "tenant": "acme-corp"
}
```

**Response (201):**
```json
{
  "slug": "my-project",
  "name": "My Project Board",
  "tenant": "acme-corp",
  "task_count": 0,
  "created_at": "2025-10-16T12:00:00Z",
  "updated_at": "2025-10-16T12:00:00Z"
}
```

### Get Board
```http
GET /boards/{slug}
```

**Response (200):**
```json
{
  "slug": "my-project",
  "name": "My Project Board",
  "tenant": "acme-corp",
  "task_count": 15,
  "columns": ["triage", "todo", "ready", "running", "review", "done", "blocked", "archived"],
  "created_at": "2025-10-16T12:00:00Z",
  "updated_at": "2025-10-16T14:30:00Z"
}
```

### Delete Board
```http
DELETE /boards/{slug}
```

**Response (204):** No content

---

## Tasks

### List Tasks
```http
GET /boards/{slug}/tasks
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | - | Filter: triage,todo,ready,running,review,done,blocked,archived |
| `assignee` | string | - | Filter by assignee profile |
| `tenant` | string | - | Filter by tenant |
| `parent_id` | string | - | Filter by parent task |
| `include_archived` | bool | false | Include archived tasks |
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |
| `order` | string | priority | Sort: priority, created, updated |

**Response (200):**
```json
{
  "tasks": [
    {
      "id": "t_abc123",
      "title": "Implement user auth",
      "status": "running",
      "assignee": "sdlc-developer",
      "priority": 10,
      "parent_ids": ["t_parent1"],
      "child_ids": ["t_child1", "t_child2"],
      "tenant": "acme-corp",
      "created_at": "2025-10-16T10:00:00Z",
      "updated_at": "2025-10-16T10:05:00Z",
      "started_at": "2025-10-16T10:05:00Z",
      "completed_at": null,
      "run_count": 1,
      "current_run_id": 42
    }
  ],
  "total": 15,
  "limit": 50,
  "offset": 0
}
```

### Create Task
```http
POST /boards/{slug}/tasks
Content-Type: application/json
```

**Request Body:**
```json
{
  "title": "Implement user authentication",
  "assignee": "sdlc-developer",
  "body": "Create JWT-based auth with refresh tokens\n\nAcceptance criteria:\n- Login endpoint returns access + refresh token\n- Refresh endpoint rotates tokens\n- Tokens expire in 15min / 7 days",
  "parents": ["t_parent1", "t_parent2"],
  "tenant": "acme-corp",
  "priority": 5,
  "workspace_kind": "worktree",
  "workspace_path": null,
  "project": "my-project",
  "triage": false,
  "max_runtime_seconds": 3600,
  "skills": ["python", "fastapi"],
  "goal_mode": false,
  "goal_max_turns": 20,
  "completion_contract": "local-only",
  "model": "anthropic/claude-3.5-sonnet",
  "provider": "anthropic",
  "idempotency_key": "auth-impl-2025-10-16"
}
```

**Response (201):**
```json
{
  "id": "t_abc123",
  "title": "Implement user authentication",
  "status": "triage",
  "assignee": "sdlc-developer",
  "priority": 5,
  "parent_ids": ["t_parent1", "t_parent2"],
  "child_ids": [],
  "tenant": "acme-corp",
  "workspace_kind": "worktree",
  "project": "my-project",
  "created_at": "2025-10-16T12:00:00Z",
  "updated_at": "2025-10-16T12:00:00Z"
}
```

### Get Task
```http
GET /tasks/{id}
```

**Response (200):**
```json
{
  "id": "t_abc123",
  "title": "Implement user authentication",
  "body": "Create JWT-based auth...",
  "status": "running",
  "assignee": "sdlc-developer",
  "priority": 5,
  "parent_ids": ["t_parent1"],
  "child_ids": ["t_child1"],
  "tenant": "acme-corp",
  "workspace_kind": "worktree",
  "workspace_path": "/mnt/data/multi-agent-workflow/.worktrees/t_abc123",
  "project": "my-project",
  "triage": false,
  "max_runtime_seconds": 3600,
  "skills": ["python", "fastapi"],
  "goal_mode": false,
  "goal_max_turns": 20,
  "completion_contract": "local-only",
  "model": "anthropic/claude-3.5-sonnet",
  "provider": "anthropic",
  "created_at": "2025-10-16T12:00:00Z",
  "updated_at": "2025-10-16T12:05:00Z",
  "started_at": "2025-10-16T12:05:00Z",
  "completed_at": null,
  "run_count": 1,
  "current_run_id": 42,
  "metadata": {
    "changed_files": ["src/auth.py", "tests/test_auth.py"],
    "tests_run": 12,
    "coverage": 92.5
  },
  "result": "Implemented JWT auth with 92.5% coverage"
}
```

### Update Task
```http
PATCH /tasks/{id}
Content-Type: application/json
```

**Request Body (all fields optional):**
```json
{
  "title": "Updated title",
  "body": "Updated description",
  "assignee": "sdlc-reviewer",
  "priority": 10,
  "max_runtime_seconds": 7200
}
```

**Response (200):** Updated task object

### Complete Task
```http
POST /tasks/{id}/complete
Content-Type: application/json
```

**Request Body:**
```json
{
  "summary": "Implemented JWT authentication with access/refresh tokens. All tests pass (12 tests, 92.5% coverage).",
  "result": "Auth module complete with 92.5% coverage",
  "metadata": {
    "changed_files": ["src/auth.py", "tests/test_auth.py"],
    "tests_run": 12,
    "coverage": 92.5,
    "findings": []
  },
  "created_cards": ["t_child1", "t_child2"],
  "artifacts": [
    "/mnt/data/multi-agent-workflow/.worktrees/t_abc123/workspace/src/auth.py"
  ]
}
```

**Response (200):**
```json
{
  "id": "t_abc123",
  "status": "done",
  "completed_at": "2025-10-16T14:30:00Z",
  "metadata": { ... }
}
```

### Request Review
```http
POST /tasks/{id}/review
Content-Type: application/json
```

**Request Body:**
```json
{
  "summary": "Auth implementation complete. Ready for review.",
  "reviewer": "sdlc-reviewer",
  "metadata": {
    "changed_files": ["src/auth.py"],
    "tests_run": 12
  },
  "artifacts": ["/workspace/src/auth.py"]
}
```

**Response (200):** Task with status `review`

### Request Changes (Reviewer)
```http
POST /tasks/{id}/request-changes
Content-Type: application/json
```

**Request Body:**
```json
{
  "reason": "Missing token revocation on logout. Add /auth/revoke endpoint."
}
```

**Response (200):** Task returned to assignee with status `todo`

### Block Task
```http
POST /tasks/{id}/block
Content-Type: application/json
```

**Request Body:**
```json
{
  "reason": "Waiting for security team approval on crypto library",
  "kind": "needs_input"
}
```

**Response (200):** Task with status `blocked`

### Unblock Task
```http
POST /tasks/{id}/unblock
```

**Response (200):** Task moves to `ready` (if parents done) or `todo`

### Add Comment
```http
POST /tasks/{id}/comments
Content-Type: application/json
```

**Request Body:**
```json
{
  "body": "This looks good. Minor nit: add docstring to `create_token` function."
}
```

**Response (201):**
```json
{
  "id": "c_123",
  "task_id": "t_abc123",
  "author": "sdlc-reviewer",
  "body": "This looks good...",
  "created_at": "2025-10-16T14:35:00Z"
}
```

### List Comments
```http
GET /tasks/{id}/comments
```

**Response (200):**
```json
{
  "comments": [...],
  "total": 5
}
```

### Task Events (Audit Log)
```http
GET /tasks/{id}/events
```

**Response (200):**
```json
{
  "events": [
    {
      "id": 1,
      "task_id": "t_abc123",
      "type": "created",
      "message": "Task created by sdlc-planner",
      "author": "sdlc-planner",
      "metadata": {},
      "timestamp": "2025-10-16T12:00:00Z"
    },
    {
      "id": 2,
      "task_id": "t_abc123",
      "type": "status_changed",
      "message": "Status changed: triage → todo",
      "author": "dispatcher",
      "metadata": {"from": "triage", "to": "todo"},
      "timestamp": "2025-10-16T12:00:01Z"
    }
  ],
  "total": 15
}
```

---

## Task Dependencies

### Link Tasks (Parent → Child)
```http
POST /tasks/{parent_id}/dependencies
Content-Type: application/json
```

**Request Body:**
```json
{
  "child_id": "t_child1"
}
```

**Response (201):**
```json
{
  "parent_id": "t_parent1",
  "child_id": "t_child1",
  "created_at": "2025-10-16T12:00:00Z"
}
```

### List Dependencies
```http
GET /tasks/{id}/dependencies
```

**Response (200):**
```json
{
  "parents": ["t_parent1"],
  "children": ["t_child1", "t_child2"]
}
```

### Remove Dependency
```http
DELETE /tasks/{parent_id}/dependencies/{child_id}
```

**Response (204):** No content

---

## Attachments

### Upload Attachment
```http
POST /tasks/{id}/attachments
Content-Type: multipart/form-data
```

**Form Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | File to upload |
| `filename` | string | No | Custom filename |

**Response (201):**
```json
{
  "id": "att_123",
  "task_id": "t_abc123",
  "filename": "report.pdf",
  "content_type": "application/pdf",
  "size": 102400,
  "uploaded_by": "sdlc-developer",
  "path": "/mnt/data/multi-agent-workflow/attachments/t_abc123/report.pdf",
  "created_at": "2025-10-16T14:30:00Z"
}
```

### List Attachments
```http
GET /tasks/{id}/attachments
```

**Response (200):**
```json
{
  "attachments": [...],
  "total": 3
}
```

### Download Attachment
```http
GET /attachments/{attachment_id}
```

**Response:** File stream with `Content-Disposition: attachment`

### Delete Attachment
```http
DELETE /attachments/{attachment_id}
```

**Response (204):** No content

---

## Dispatcher

### Get Status
```http
GET /dispatcher/status
```

**Response (200):**
```json
{
  "running": true,
  "board": "default",
  "workers": {
    "total": 3,
    "idle": 1,
    "busy": 2,
    "profiles": {
      "sdlc-developer": 2,
      "sdlc-tester": 1
    }
  },
  "queue": {
    "ready": 5,
    "running": 2,
    "blocked": 1
  },
  "uptime_seconds": 3600,
  "last_poll": "2025-10-16T14:30:00Z"
}
```

### Start Dispatcher
```http
POST /dispatcher/start
Content-Type: application/json
```

**Request Body:**
```json
{
  "board": "default",
  "config": {}
}
```

**Response (200):**
```json
{
  "started": true,
  "pid": 12345
}
```

### Stop Dispatcher
```http
POST /dispatcher/stop
```

**Response (200):**
```json
{
  "stopped": true
}
```

---

## Webhooks

### Register Webhook
```http
POST /webhooks
Content-Type: application/json
```

**Request Body:**
```json
{
  "url": "https://your-app.com/webhooks/hermes",
  "events": ["task.created", "task.completed", "task.blocked"],
  "secret": "webhook-secret-key",
  "active": true
}
```

**Events:**
- `task.created`
- `task.updated`
- `task.status_changed`
- `task.completed`
- `task.blocked`
- `task.unblocked`
- `task.review_requested`
- `task.changes_requested`
- `comment.added`
- `attachment.uploaded`

### List Webhooks
```http
GET /webhooks
```

### Delete Webhook
```http
DELETE /webhooks/{id}
```

---

## Health & Metrics

### Health Check
```http
GET /health
```

**Response (200):**
```json
{
  "status": "healthy",
  "version": "0.1.0-rc1",
  "database": "connected",
  "dispatcher": "running",
  "workers": 3,
  "timestamp": "2025-10-16T14:30:00Z"
}
```

### Metrics (Prometheus)
```http
GET /metrics
```

**Response:** Prometheus text format

---

## Error Responses

### Standard Error Format
```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task t_abc123 not found",
    "details": {}
  }
}
```

### Error Codes
| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Invalid request body |
| `UNAUTHORIZED` | 401 | Missing/invalid auth |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `CONFLICT` | 409 | Duplicate idempotency key |
| `TASK_NOT_FOUND` | 404 | Task ID not found |
| `BOARD_NOT_FOUND` | 404 | Board slug not found |
| `PARENT_NOT_DONE` | 409 | Parent task not completed |
| `DATABASE_ERROR` | 500 | Database operation failed |
| `DISPATCHER_NOT_RUNNING` | 503 | Dispatcher not started |
| `WORKER_SPAWN_FAILED` | 500 | Failed to spawn worker |
| `RATE_LIMITED` | 429 | Too many requests |

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `/health` | 1000/min |
| `GET /boards/*` | 200/min |
| `POST /boards/*/tasks` | 50/min |
| `PATCH /tasks/*` | 100/min |
| `POST /tasks/*/complete` | 30/min |
| Webhooks | 1000/min |

Headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1708092000
```

---

## SDK Examples

### Python
```python
import httpx

client = httpx.Client(
    base_url="http://localhost:8000",
    headers={"Authorization": "Bearer YOUR_TOKEN"}
)

# Create task
task = client.post("/boards/default/tasks", json={
    "title": "New feature",
    "assignee": "sdlc-developer"
}).json()

# Wait for completion
import time
while True:
    status = client.get(f"/tasks/{task['id']}").json()["status"]
    if status in ("done", "blocked"):
        break
    time.sleep(5)

print(client.get(f"/tasks/{task['id']}").json()["result"])
```

### JavaScript/TypeScript
```typescript
const api = axios.create({
  baseURL: 'http://localhost:8000',
  headers: { Authorization: `Bearer ${token}` }
});

// Create task with dependencies
const parent = await api.post('/boards/default/tasks', {
  title: 'Design API',
  assignee: 'sdlc-architect'
});

const child = await api.post('/boards/default/tasks', {
  title: 'Implement API',
  assignee: 'sdlc-developer',
  parents: [parent.data.id]
});
```

---

*See also: [Agent Development](agent-development.md) | [Kanban Integration](kanban-integration.md) | [Quality Gates](quality-gates.md)*