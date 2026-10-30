# Evidence — github-kanban-sync E2E (Issue #192), 2026-10-30

Environment: real GitHub API (token from `gh auth token`, keyring), real local
Kanban board `~/.hermes/kanban/boards/me/kanban.db`, real card `t_02d18f3e`.
Command (from worktree root):

```
GKS_REPO_ROOT=$PWD GKS_SCRATCH=<scratch> GKS_E2E_WRITE=1 python3 gks_e2e.py
```

`GKS_SCRATCH` is a throwaway ledger DB; the board writes are real (a comment on
`t_02d18f3e`) and the GitHub write is one coordination comment on Issue #192.

## 1. GitHub → Kanban (real ingest, real delivery)

```
===== github issue #192 (live) =====
{"number": 192, "state": "open",
 "title": "[P1][Coordination] Двусторонняя синхронизация GitHub Issues/",
 "updated_at": "2026-10-30T09:08:47Z", "comments": 2}

===== ingest issues =====
{"feed": "issues", "new_events": 16, "not_modified": false, "cursor": "2026-10-16T09:15:53Z"}

===== ingest comments #192 =====
{"feed": "comments:192", "new_events": 2, "cursor": "2026-10-30T09:08:47Z"}

===== delivery journal (delivered) =====
[{"id": 18, "source_event_id": "askarahodov/multi-agent-workflow:issue_comment:192:6519142157",
  "channel": "kanban", "target": "t_02d18f3e", "status": "delivered", "attempts": 1,
  "correlation_id": "issue:192", "detail": "issue #192 -> t_02d18f3e"},
 {"id": 17, "source_event_id": "askarahodov/multi-agent-workflow:issue_comment:192:6519063860",
  "channel": "kanban", "target": "t_02d18f3e", "status": "delivered", "attempts": 1,
  "correlation_id": "issue:192", "detail": "issue #192 -> t_02d18f3e"}]
```

Both real comments on Issue #192 (including the `MIGRATION_182_HANDOFF`-style
ownership comment) were delivered to the owning card `t_02d18f3e`, each with a
delivery receipt and correlation id.

## 2. Kanban → GitHub (real publish to the linked Issue)

```
===== publish #192 (1st) =====
{"task_id": "t_02d18f3e", "status": "created", "issue": 192, "rev": 1, "comment_id": 6519184408}

---- published comment body (id 6519184408) ----
<!-- gks:v1 issue=192 channel=publish rev=2 -->
## Kanban → GitHub · статус синхронизирован

- **task**: `t_02d18f3e` (board `me`)
- **status**: `running`
- **assignee**: `sdlc-developer`
- **branch**: `wt/t_02d18f3e`
- **PR**: —
- **blocker**: —
- **changed_paths**: —
- **updated_at**: 2026-10-30T09:11:27Z

_synced from Kanban by_ `sdlc-developer`
```

Exactly **one** publish comment exists on Issue #192 (`total comments: 3`,
`publish comments: 1`) despite repeated publishes — the marker comment is
updated in place, never duplicated.

## 3. Idempotency + feedback-loop guard

```
===== publish (repeat, after content stabilised) =====
publish B (expect unchanged): {"task_id": "t_02d18f3e", "status": "unchanged", "issue": 192}

===== re-ingest after publish (expect 0 new) =====
{"feed": "comments:192", "new_events": 0}
```

Re-publishing unchanged content is a no-op (`unchanged`); the tool's own published
comment is ignored on re-ingest (no feedback loop).

## 4. Health

```
{"healthy": true, "pending_events": 0, "errors": 0,
 "counts": {"links": 1, "events": 18, "pending": 0, "deliveries": 19, "delivery_errors": 0}}
```
