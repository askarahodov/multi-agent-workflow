# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T084504Z |
| время сбора (UTC) | 2026-10-15T08:45:04Z |
| главная ветка (main) | a8f7e4be33218dbba1e60f9c3756fcbaa7477621 |
| ветка обмена (coord/external-qa) | 6d2f702ca69f2368d3ce36b74ceb5117564abfa5 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 1 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Native agent cross-service E2E conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_6772fb31` | me | running | sdlc-tester | 0 |  |
- заблокировано: 14; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_17b85467`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED` | — |
| `QA-RSP-20261014-SUBSTANCE-ROOT-CAUSE` | — |
| `QA-RSP-20261014-ARCHIVE-OVERWRITE` | — |
| `QA-RSP-20261014-P0A-REVIEW` | — |
| `QA-RSP-20261014-P2C-REVIEW` | — |
| `QA-RSP-20261014-P1-ARCHIVE-INDEX-INTEGRITY` | — |
| `QA-RSP-20261015-REMOTE-MAIN-FRESHNESS` | — |
| `QA-RSP-20261015-LIVE-RECOVERY-FENCING` | — |
- открытых QA-кейсов: 10

## task_counts
```json
{"triage": 0, "todo": 8, "scheduled": 0, "ready": 0, "running": 1, "blocked": 14, "review": 1, "done": 190, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T084504Z
- ветка обмена: 6d2f702ca69f2368d3ce36b74ceb5117564abfa5
- publish_state: dbf4b470011d
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
