# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T110008Z |
| время сбора (UTC) | 2026-10-15T11:00:08Z |
| главная ветка (main) | a8f7e4be33218dbba1e60f9c3756fcbaa7477621 |
| ветка обмена (coord/external-qa) | cacd8956acaa9933940c527f46608d89ca52e590 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | нет прогона на main в окне |

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
| `QA-RSP-20261014-P1-ARCHIVE-INDEX-INTEGRITY` | — |
| `QA-RSP-20261015-REMOTE-MAIN-FRESHNESS` | — |
| `QA-RSP-20261015-LIVE-RECOVERY-FENCING` | — |
| `QA-RSP-20261015-PAID-LIMIT-OWNER-HANDOFF` | — |
| `QA-RSP-20261015-NATIVE-ATTEMPT-GUARD-HANDOFF` | — |
| `QA-RSP-20261015-SQLITE-FENCE-HANDOFF` | — |
| `QA-RSP-20261015-DURABLE-ATTEMPT-LEASE-HANDOFF` | — |
| `QA-RSP-20261015-HTTP-LEASE-RENEWAL-HANDOFF` | — |
- открытых QA-кейсов: 10

## task_counts
```json
{"triage": 0, "todo": 7, "scheduled": 0, "ready": 1, "running": 0, "blocked": 14, "review": 1, "done": 191, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T110008Z
- ветка обмена: cacd8956acaa9933940c527f46608d89ca52e590
- publish_state: 513d89db12f8
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
