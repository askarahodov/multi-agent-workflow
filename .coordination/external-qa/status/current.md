```yaml
snapshot_id: UTC-20261030T150004Z
collected_at_utc: 2026-10-30T15:00:03Z
source: local-hermes-kanban+git+gateway+ci
source_status: VERIFIED
project: multi-agent-workflow
repo_main_sha: 5c6c630ac66d0ab0ac9d8d47837276b3fb7f5422
local_branch: docs/manifest-refresh
local_head_sha: 8fc08aa
contact_branch_sha: c4382459ce09d4d196d01687a878b8a411c81139
active_provider_profiles: ["hermes-dev:openrouter", "openrouter", "orchestrator:openrouter", "sdlc-architect:openrouter", "sdlc-developer:openrouter", "sdlc-fixer:openrouter", "sdlc-planner:openrouter", "sdlc-release:openrouter", "sdlc-researcher:openrouter", "sdlc-reviewer:openrouter", "sdlc-security:openrouter", "sdlc-tester:openrouter"]
cost_budget: UNKNOWN
active_workers: 0 running
rate_limited_events_since_last: 0
spawn_failures_since_last: 0
kanban_boards: ["default", "boards", "harbor-transfer-portal", "me"]
task_counts: {"triage": 0, "todo": 0, "scheduled": 3, "ready": 0, "running": 0, "blocked": 6, "review": 0, "done": 306, "archived": 11}
ci_latest: UNKNOWN (no CI run on main in window)
last_qa_response_processed: NONE
publish_state: c4382459ce09
```

## 1. Изменилось с прошлого snapshot
- (нет изменений статусов задач)

## 2. Текущий приоритет и dependency order
- BLOCKED `t_4fbeb3bc` (default): no reason recorded
- BLOCKED `t_26938b85` (default): workspace: task t_26938b85 has workspace_kind=dir but no workspace_path
- BLOCKED `t_106a49d2` (default): no reason recorded
- BLOCKED `t_3f35ed67` (default): pid 1989509 exited with code 1 [managed worker lost: managed_worker_failed] Worker's last output: "uter didn't respond i
- BLOCKED `t_17b85467` (default): pid 1989505 exited with code 1 [managed worker lost: managed_worker_failed] Worker's last output: "uter didn't respond i
- BLOCKED `t_fef82014` (me): no reason recorded

## 3. Активные и недавно изменённые задачи
| task | board | status | owner | fails | last error | workspace |
|---|---|---|---|---|---|---|
| `t_106a49d2` | default | blocked | default | 0 |  | /home/askarahodov/.hermes/kanban/workspaces/t_106a49d2 |
| `t_17b85467` | default | blocked | sdlc-tester | 1 | pid 1989505 exited with code 1 [managed worker lost: managed | /mnt/data/multi-agent-workflow/.worktrees/t_17b85467 |
| `t_26938b85` | default | blocked | default | 2 | workspace: task t_26938b85 has workspace_kind=dir but no wor | dir |
| `t_3f35ed67` | default | blocked | sdlc-planner | 1 | pid 1989509 exited with code 1 [managed worker lost: managed | /home/askarahodov/.hermes/kanban/workspaces/t_3f35ed67 |
| `t_4fbeb3bc` | default | blocked | default | 0 |  | /home/askarahodov/.hermes/kanban/workspaces/t_4fbeb3bc |
| `t_fef82014` | me | blocked | orchestrator | 0 |  | /mnt/data/multi-agent-workflow/.worktrees/t_fef82014 |

## 4. Последние завершённые задачи
- `t_531f4b91` (me) — GATE-TESTER rc.2 — кандидат origin/main @ 5c6c630 (после PR #204) @ 2026-10-30 17:44 MSK
- `t_0c168474` (me) — GATE-REVIEWER rc.2 — кандидат origin/main @ 5c6c630 (после PR #204) @ 2026-10-30 17:27 MSK
- `t_8b164259` (me) — FIX SEC-RC2-001: api_key в query-строке утекает в access-логи uvicorn  @ 2026-10-30 17:27 MSK
- `t_c6d2dc95` (me) — GATE-SECURITY rc.2 — кандидат origin/main @ 5c6c630 (после PR #204) @ 2026-10-30 17:21 MSK
- `t_13b54a77` (me) — Re-review P1 live-updates fix (B1/B2) — independent gate @ 2026-10-30 17:10 MSK
- `t_4cf984fb` (me) — Fix P1 live-updates B1/B2 (+N1/N2) on wt/t_ff8817c5 and open PR @ 2026-10-30 17:01 MSK
- `t_71b54993` (me) — E2E: independent QA of PR #194 at the exact delivered SHA (GKS review_ @ 2026-10-30 16:50 MSK
- `t_dc380f99` (me) — E2E guard harness #2: active_pr freeze → review_requested lift → auto- @ 2026-10-30 16:49 MSK
- `t_ab9b9ac2` (me) — Fix Release CI: validate-release missing artifact download + regenerat @ 2026-10-30 16:42 MSK
- `t_d852d4c9` (me) — Finalize v0.1.0-rc1 docs: land refresh 22f60c2 + version-bound RELEASE @ 2026-10-30 16:28 MSK
- `t_ed5a462c` (me) — Independent QA: re-verify PR #194 (Issue #182 migration) at reworked h @ 2026-10-30 16:22 MSK
- `t_d270d2e6` (me) — Integration plan: land gated platform branches onto main and re-cut RC @ 2026-10-30 16:18 MSK

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
- worktrees: 98 visible
