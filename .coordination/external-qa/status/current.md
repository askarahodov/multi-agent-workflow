```yaml
snapshot_id: UTC-20261030T101504Z
collected_at_utc: 2026-10-30T10:15:04Z
source: local-hermes-kanban+git+gateway+ci
source_status: VERIFIED
project: multi-agent-workflow
repo_main_sha: ef9d50fb98595036518e8772d1c371151a5d063a
local_branch: main
local_head_sha: c94245f
contact_branch_sha: 8588c91b47bf7ddfec5ab4c11f655eb7159a3d6c
active_provider_profiles: ["hermes-dev:openrouter", "openrouter", "orchestrator:openrouter", "sdlc-architect:openrouter", "sdlc-developer:openrouter", "sdlc-fixer:openrouter", "sdlc-planner:openrouter", "sdlc-release:openrouter", "sdlc-researcher:openrouter", "sdlc-reviewer:openrouter", "sdlc-security:openrouter", "sdlc-tester:openrouter"]
cost_budget: UNKNOWN
active_workers: 0 running
rate_limited_events_since_last: 0
spawn_failures_since_last: 0
kanban_boards: ["default", "boards", "harbor-transfer-portal", "me"]
task_counts: {"triage": 0, "todo": 6, "scheduled": 3, "ready": 0, "running": 0, "blocked": 6, "review": 0, "done": 262, "archived": 9}
ci_latest: UNKNOWN (no CI run on main in window)
last_qa_response_processed: NONE
publish_state: 8588c91b47bf
```

## 1. Изменилось с прошлого snapshot
- (нет изменений статусов задач)

## 2. Текущий приоритет и dependency order
- BLOCKED `t_4fbeb3bc` (default): no reason recorded
- BLOCKED `t_26938b85` (default): workspace: task t_26938b85 has workspace_kind=dir but no workspace_path
- BLOCKED `t_106a49d2` (default): no reason recorded
- BLOCKED `t_3f35ed67` (default): pid 1989509 exited with code 1 [managed worker lost: managed_worker_failed] Worker's last output: "uter didn't respond i
- BLOCKED `t_17b85467` (default): pid 1989505 exited with code 1 [managed worker lost: managed_worker_failed] Worker's last output: "uter didn't respond i
- BLOCKED `t_27805ca5` (me): no reason recorded

## 3. Активные и недавно изменённые задачи
| task | board | status | owner | fails | last error | workspace |
|---|---|---|---|---|---|---|
| `t_106a49d2` | default | blocked | default | 0 |  | /home/askarahodov/.hermes/kanban/workspaces/t_106a49d2 |
| `t_17b85467` | default | blocked | sdlc-tester | 1 | pid 1989505 exited with code 1 [managed worker lost: managed | /mnt/data/multi-agent-workflow/.worktrees/t_17b85467 |
| `t_26938b85` | default | blocked | default | 2 | workspace: task t_26938b85 has workspace_kind=dir but no wor | dir |
| `t_3f35ed67` | default | blocked | sdlc-planner | 1 | pid 1989509 exited with code 1 [managed worker lost: managed | /home/askarahodov/.hermes/kanban/workspaces/t_3f35ed67 |
| `t_4fbeb3bc` | default | blocked | default | 0 |  | /home/askarahodov/.hermes/kanban/workspaces/t_4fbeb3bc |
| `t_27805ca5` | me | blocked | sdlc-release | 0 |  | /mnt/data/multi-agent-workflow/.worktrees/t_27805ca5 |

## 4. Последние завершённые задачи
- `t_7db0e3c2` (me) — Generate RELEASE_NOTES.md from merged PRs @ 2026-10-30 12:59 MSK
- `t_dcdfc19c` (me) — Интеграция autostart #192: push wt/t_46fa19d5 → расширить PR #193 (или @ 2026-10-30 12:58 MSK
- `t_ba201967` (me) — Verify #192 autostart (НЕЗАВИСИМО): автоматический обмен без ручных ша @ 2026-10-30 12:54 MSK
- `t_7c06b0da` (me) — Authorized merge + cleanup: PR #189 and ROLLOUT_PLAN.md landing @ 2026-10-30 12:53 MSK
- `t_46fa19d5` (me) — Issue #192 — автозапуск моста GitHub↔Kanban: scheduler/daemon (cursor/ @ 2026-10-30 12:44 MSK
- `t_da6316c3` (me) — Issue #192 — интеграция: PR wt/t_02d18f3e → main + зелёный required CI @ 2026-10-30 12:35 MSK
- `t_ea367721` (me) — Re-verify Issue #192 (НЕЗАВИСИМО) после rework t_29dd8858: board-level @ 2026-10-30 12:27 MSK
- `t_29dd8858` (me) — Rework Issue #192: board-level idempotency for ingest + clean duplicat @ 2026-10-30 12:24 MSK
- `t_ebef342b` (me) — FIX: create-time валидация полей карточки (model_override по allow-lis @ 2026-10-30 12:22 MSK
- `t_0596c672` (me) — Verify Issue #192 (НЕЗАВИСИМО): реальный двусторонний обмен + отсутств @ 2026-10-30 12:18 MSK
- `t_02d18f3e` (me) — Issue #192: двусторонняя синхронизация GitHub ↔ локальный Kanban (ЕДИН @ 2026-10-30 12:13 MSK
- `t_4e87c3bc` (me) — FIX: create-time валидация skills по каталогу профиля (union) @ 2026-10-30 12:01 MSK

## 5. QA-ответы
- Обработанных в этом проходе нет.

## 6. Риски и известные ограничения
- Gemini/kanban dispatch PAUSED by global emergency stop (ESTOP).
- invalid dir-workspace tasks: t_26938b85

## 7. Отчёт о доступности источников
- kanban: VERIFIED
- git: VERIFIED
- gateway log: VERIFIED
- CI (gh): VERIFIED
- worktrees: 77 visible
