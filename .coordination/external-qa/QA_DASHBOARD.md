# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261030T091504Z |
| время сбора (UTC) | 2026-10-30T09:15:04Z |
| главная ветка (main) | b4200533646542768f2b78e0e7d45b0bf49275a1 |
| ветка обмена (coord/external-qa) | 7d9fd5efe1c72948b980cdc8d90567aa2d038f63 |
| доски Kanban | default, boards, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | GitFlow Policy conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_4ba4cb15` | me | ready | sdlc-release | 0 |  |
| `t_7c06b0da` | me | ready | sdlc-release | 0 |  |
| `t_0596c672` | me | running | sdlc-tester | 0 |  |
| `t_ebef342b` | me | running | sdlc-developer | 0 |  |
- заблокировано: 5; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_3f35ed67`, `t_17b85467`

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
{"triage": 0, "todo": 1, "scheduled": 3, "ready": 2, "running": 2, "blocked": 5, "review": 0, "done": 252, "archived": 9}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261030T091504Z
- ветка обмена: 7d9fd5efe1c72948b980cdc8d90567aa2d038f63
- publish_state: 7d9fd5efe1c7
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
