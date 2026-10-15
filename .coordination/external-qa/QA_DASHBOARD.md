# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T093005Z |
| время сбора (UTC) | 2026-10-15T09:30:05Z |
| главная ветка (main) | a8f7e4be33218dbba1e60f9c3756fcbaa7477621 |
| ветка обмена (coord/external-qa) | 87627541adf9bec2705e6f0f9a97ecea25396251 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | нет прогона на main в окне |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- событий rate_limited с прошлого snapshot: 2.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_b6d2958b` | me | ready | sdlc-release | 0 | pid 1948682 exited rate-limited (quota wall) — requeued with |
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 14; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_17b85467`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261014-ARCHIVE-OVERWRITE` | — |
| `QA-RSP-20261014-P0A-REVIEW` | — |
| `QA-RSP-20261014-P2C-REVIEW` | — |
| `QA-RSP-20261014-P1-ARCHIVE-INDEX-INTEGRITY` | — |
| `QA-RSP-20261015-REMOTE-MAIN-FRESHNESS` | — |
| `QA-RSP-20261015-LIVE-RECOVERY-FENCING` | — |
| `QA-RSP-20261015-PAID-LIMIT-OWNER-HANDOFF` | — |
| `QA-RSP-20261015-NATIVE-ATTEMPT-GUARD-HANDOFF` | — |
- открытых QA-кейсов: 10

## task_counts
```json
{"triage": 0, "todo": 7, "scheduled": 0, "ready": 1, "running": 0, "blocked": 14, "review": 1, "done": 191, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T093005Z
- ветка обмена: 87627541adf9bec2705e6f0f9a97ecea25396251
- publish_state: 1670d357a090
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
