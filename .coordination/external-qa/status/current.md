```yaml
snapshot_id: UTC-20261014T084741Z
collected_at_utc: 2026-10-14T08:47:41Z
source: local-hermes-kanban+git+gateway+ci
source_status: VERIFIED
project: multi-agent-workflow
repo_main_sha: bd616de7bab27dc69e951dc2fa23181294290c67
local_branch: main
local_head_sha: bd616de
contact_branch_sha: bd616de7bab27dc69e951dc2fa23181294290c67
active_provider_profiles: ["hermes-dev:openrouter", "openrouter", "orchestrator:openrouter", "processauto-check:openrouter", "sdlc-architect:openrouter", "sdlc-developer:openrouter", "sdlc-fixer:openrouter", "sdlc-planner:openrouter", "sdlc-release:openrouter", "sdlc-researcher:openrouter", "sdlc-reviewer:openrouter", "sdlc-security:openrouter", "sdlc-tester:openrouter"]
cost_budget: UNKNOWN
active_workers: 0 running
rate_limited_events_since_last: 2
spawn_failures_since_last: 0
kanban_boards: ["default", "boards", "ct-gate", "harbor-transfer-portal", "me"]
task_counts: {"triage": 0, "todo": 6, "scheduled": 0, "ready": 2, "running": 0, "blocked": 12, "review": 1, "done": 180, "archived": 4}
ci_latest: UNKNOWN (no CI run on main in window)
last_qa_response_processed: NONE
publish_state: 15d765a49fee
```

## 1. Изменилось с прошлого snapshot
- `t_82572d91` (default): running → ready
- `t_d3e747d2` (me): running → ready

## 2. Текущий приоритет и dependency order
- BLOCKED `t_4fbeb3bc` (default): no reason recorded
- BLOCKED `t_26938b85` (default): workspace: task t_26938b85 has workspace_kind=dir but no workspace_path
- BLOCKED `t_106a49d2` (default): no reason recorded
- BLOCKED `t_0fc1b5f5` (default): Iteration budget exhausted (30/30) — task could not complete within the allowed iterations
- BLOCKED `t_3f35ed67` (default): Iteration budget exhausted (40/40) — task could not complete within the allowed iterations
- BLOCKED `t_701b701a` (ct-gate): no reason recorded
- BLOCKED `t_c5280101` (ct-gate): no reason recorded
- BLOCKED `t_dd148f2c` (ct-gate): no reason recorded
- BLOCKED `t_da17c2d5` (ct-gate): no reason recorded
- BLOCKED `t_03f8b46d` (ct-gate): no reason recorded
- BLOCKED `t_d3755c32` (ct-gate): no reason recorded
- BLOCKED `t_44acc72b` (me): Iteration budget exhausted (60/60) — task could not complete within the allowed iterations

## 3. Активные и недавно изменённые задачи
| task | board | status | owner | fails | last error | workspace |
|---|---|---|---|---|---|---|
| `t_03f8b46d` | ct-gate | blocked | sdlc-tester | 0 |  | scratch |
| `t_701b701a` | ct-gate | blocked | sdlc-tester | 0 |  | scratch |
| `t_c5280101` | ct-gate | blocked | sdlc-tester | 0 |  | scratch |
| `t_d3755c32` | ct-gate | blocked | sdlc-tester | 0 |  | /tmp |
| `t_da17c2d5` | ct-gate | blocked | sdlc-tester | 0 |  | scratch |
| `t_dd148f2c` | ct-gate | blocked | sdlc-tester | 0 |  | scratch |
| `t_0fc1b5f5` | default | blocked | sdlc-release | 2 | Iteration budget exhausted (30/30) — task could not complete | /mnt/data/app/sdlc-demo |
| `t_106a49d2` | default | blocked | default | 0 |  | /home/askarahodov/.hermes/kanban/workspaces/t_106a49d2 |
| `t_26938b85` | default | blocked | default | 2 | workspace: task t_26938b85 has workspace_kind=dir but no wor | dir |
| `t_3f35ed67` | default | blocked | sdlc-planner | 2 | Iteration budget exhausted (40/40) — task could not complete | /home/askarahodov/.hermes/kanban/workspaces/t_3f35ed67 |
| `t_4fbeb3bc` | default | blocked | default | 0 |  | /home/askarahodov/.hermes/kanban/workspaces/t_4fbeb3bc |
| `t_44acc72b` | me | blocked | sdlc-tester | 2 | Iteration budget exhausted (60/60) — task could not complete | /mnt/data/multi-agent-workflow/.worktrees/t_44acc72b |
| `t_82572d91` | default | ready | sdlc-developer | 0 | pid 1049201 exited rate-limited (quota wall) — requeued with | /mnt/data/multi-agent-workflow/.worktrees/t_44acc72b_1 |
| `t_d3e747d2` | me | ready | sdlc-developer | 0 | pid 1053225 exited rate-limited (quota wall) — requeued with | /mnt/data/multi-agent-workflow/.worktrees/t_d3e747d2 |
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho | /home/askarahodov/.hermes/kanban/workspaces/t_25b2b984 |

## 4. Последние завершённые задачи
- `t_f414c513` (me) — Implement security gate for agent actions @ 2026-10-14 10:50 MSK
- `t_ad602ad8` (me) — ARCH-INTEGRATE: unify ARCH-FIX (1d34780) with ADR-017..020 (4194181) i @ 2026-10-14 09:36 MSK
- `t_c75d4859` (me) — Implement code review gate for agent-generated changes @ 2026-10-14 09:27 MSK
- `t_31363350` (me) — Fix broken workflows on coord/external-qa (invalid ci.yml + corrupted  @ 2026-10-14 09:13 MSK
- `t_25ec9e17` (me) — Integrate and refresh docs/ci-guide.md on main @ 2026-10-14 09:11 MSK
- `t_662e8363` (me) — Decide agent-profile persistence: typed AgentDefinition columns vs exi @ 2026-10-13 16:47 MSK
- `t_f3036e10` (me) — дополнительно github actions @ 2026-10-13 16:29 MSK
- `t_8e8f3315` (me) — Fix broken GitHub Actions workflows (ci.yml invalid, quality-gate.yml  @ 2026-10-13 16:28 MSK
- `t_fe456686` (me) — Architecture review: platform architecture & component contracts (t_00 @ 2026-10-13 16:26 MSK
- `t_2c5d2472` (me) — Implement core agent runtime and orchestration services @ 2026-10-13 16:25 MSK
- `t_f77ede67` (me) — ARCH-DECISION: agent profile entity model + MVP storage/executor/API-v @ 2026-10-13 16:25 MSK
- `t_00f3304c` (me) — ARCH-FIX: apply review defects AR-1..AR-6 to PLATFORM-ARCHITECTURE.md  @ 2026-10-13 16:24 MSK

## 5. QA-ответы
- Обработанных в этом проходе нет.

## 6. Риски и известные ограничения
- Gemini/kanban dispatch PAUSED by global emergency stop (ESTOP).
- rate_limited events since last snapshot: 2
- invalid dir-workspace tasks: t_26938b85

## 7. Отчёт о доступности источников
- kanban: VERIFIED
- git: VERIFIED
- gateway log: VERIFIED
- CI (gh): VERIFIED
- worktrees: 18 visible
