# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261029T100004Z |
| время сбора (UTC) | 2026-10-29T10:00:04Z |
| главная ветка (main) | af661f2dc7dfa7350c14c6cb3863c1c46416ec40 |
| ветка обмена (coord/external-qa) | ca375d6ac3d95f93de458528d2f05c270b0a0cde |
| доски Kanban | default, boards, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Dependabot Updates conclusion= |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- событий rate_limited с прошлого snapshot: 1.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_36996789` | me | running | sdlc-reviewer | 0 |  |
| `t_9f95cc27` | me | running | sdlc-reviewer | 0 | pid 52490 exited rate-limited (quota wall) — requeued withou |
| `t_e72b7d4f` | me | running | sdlc-architect | 1 | pid 2461023 not alive [owner admission settled interrupted]  |
- заблокировано: 8; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_3f35ed67`, `t_17b85467`, `t_7b9e485d`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261015-SQLITE-FENCE-HANDOFF` | INFO |
| `QA-RSP-20261015-DURABLE-ATTEMPT-LEASE-HANDOFF` | INFO |
| `QA-RSP-20261015-HTTP-LEASE-RENEWAL-HANDOFF` | INFO |
| `QA-RSP-20261015-ATOMIC-LEASE-PR51-INDEPENDENT-REVIEW` | INFO / CONDITIONAL (CI final head must be checked) |
| `QA-RSP-20261015-PR50-PR51-ALL-GATES-GREEN` | INFO / CHECKPOINT_ACHIEVED (all GitHub CI green on exact feature heads, NOT production release) |
| `QA-RSP-20261015-TRUSTED-FS-GATEWAY-HANDOFF` | INFO / READY_FOR_REVIEW; production acceptance explicitly NOT_GRANTED |
| `QA-RSP-20261015-LEASED-GATEWAY-ENDTOEND-HANDOFF` | INFO / READY_FOR_INDEPENDENT_REVIEW; no production acceptance |
| `QA-RSP-20261015-LEASE-ISSUE-TTL-CONTENTION-FIX` | INFO / CODE_REVIEW_P2_FIXED / FULL_CI_GREEN |
- открытых QA-кейсов: 10

## task_counts
```json
{"triage": 0, "todo": 13, "scheduled": 3, "ready": 0, "running": 3, "blocked": 8, "review": 0, "done": 201, "archived": 5}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261029T100004Z
- ветка обмена: ca375d6ac3d95f93de458528d2f05c270b0a0cde
- publish_state: ca375d6ac3d9
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
