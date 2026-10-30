# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261030T111504Z |
| время сбора (UTC) | 2026-10-30T11:15:04Z |
| главная ветка (main) | ef9d50fb98595036518e8772d1c371151a5d063a |
| ветка обмена (coord/external-qa) | d2f7c9b69c3c0ede7c1b1fbf91247fec9b8df70b |
| доски Kanban | default, boards, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Branch Cleanup Audit conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_1e1bed85` | me | running | sdlc-reviewer | 0 |  |
| `t_6f6e2d9f` | me | running | sdlc-security | 0 |  |
| `t_9746cd76` | me | running | sdlc-tester | 0 |  |
- заблокировано: 6; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_3f35ed67`, `t_17b85467`, `t_27805ca5`

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
{"triage": 0, "todo": 7, "scheduled": 3, "ready": 0, "running": 3, "blocked": 6, "review": 0, "done": 268, "archived": 9}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261030T111504Z
- ветка обмена: d2f7c9b69c3c0ede7c1b1fbf91247fec9b8df70b
- publish_state: d2f7c9b69c3c
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
