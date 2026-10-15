# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T130008Z |
| время сбора (UTC) | 2026-10-15T13:00:08Z |
| главная ветка (main) | a8f7e4be33218dbba1e60f9c3756fcbaa7477621 |
| ветка обмена (coord/external-qa) | 49d9455e2ee899304ac98b3179a48730b7445ccd |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Quality Gate conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 15; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_17b85467`

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
{"triage": 0, "todo": 7, "scheduled": 0, "ready": 0, "running": 0, "blocked": 15, "review": 1, "done": 191, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T130008Z
- ветка обмена: 49d9455e2ee899304ac98b3179a48730b7445ccd
- publish_state: 49d9455e2ee8
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
