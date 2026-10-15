# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T124505Z |
| время сбора (UTC) | 2026-10-15T12:45:04Z |
| главная ветка (main) | a8f7e4be33218dbba1e60f9c3756fcbaa7477621 |
| ветка обмена (coord/external-qa) | 252c0a0398293ca0be899bdbb4c2b1beddd1854d |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Coordination channel isolation conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_b6d2958b` | me | ready | sdlc-release | 0 | pid 2015769 exited rate-limited (quota wall) — requeued with |
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 14; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_17b85467`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261015-SQLITE-FENCE-HANDOFF` | — |
| `QA-RSP-20261015-DURABLE-ATTEMPT-LEASE-HANDOFF` | — |
| `QA-RSP-20261015-HTTP-LEASE-RENEWAL-HANDOFF` | — |
| `QA-RSP-20261015-ATOMIC-LEASE-PR51-INDEPENDENT-REVIEW` | — |
| `QA-RSP-20261015-PR50-PR51-ALL-GATES-GREEN` | — |
| `QA-RSP-20261015-TRUSTED-FS-GATEWAY-HANDOFF` | — |
| `QA-RSP-20261015-LEASED-GATEWAY-ENDTOEND-HANDOFF` | — |
| `QA-RSP-20261015-LEASE-ISSUE-TTL-CONTENTION-FIX` | — |
- открытых QA-кейсов: 10

## task_counts
```json
{"triage": 0, "todo": 7, "scheduled": 0, "ready": 1, "running": 0, "blocked": 14, "review": 1, "done": 191, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T124505Z
- ветка обмена: 252c0a0398293ca0be899bdbb4c2b1beddd1854d
- publish_state: 252c0a039829
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
