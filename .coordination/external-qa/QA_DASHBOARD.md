# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T150008Z |
| время сбора (UTC) | 2026-10-15T15:00:08Z |
| главная ветка (main) | ed65a106b0101825a1b7171e8a185738a454a5e7 |
| ветка обмена (coord/external-qa) | 850df9dd320ec0eef3c31d802aa27e95c7d3f045 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Trusted gateway image preflight conclusion=success |

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
- источник: status/current.md @ UTC-20261015T150008Z
- ветка обмена: 850df9dd320ec0eef3c31d802aa27e95c7d3f045
- publish_state: 850df9dd320e
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
