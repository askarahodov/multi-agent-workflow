# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T063021Z |
| время сбора (UTC) | 2026-10-14T06:30:21Z |
| главная ветка (main) | bd616de7bab27dc69e951dc2fa23181294290c67 |
| ветка обмена (coord/external-qa) | f88ccb238b047051845f408de343a84027f2ca1c |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 2 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Quality Gate conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_ad602ad8` | me | running | sdlc-architect | 0 |  |
| `t_f414c513` | me | running | sdlc-security | 0 |  |
- заблокировано: 11; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-BOOTSTRAP` | — |
| `QA-RSP-20261013-HANDOFF-BLOCKED` | — |
- открытых QA-кейсов: 1

## task_counts
```json
{"triage": 0, "todo": 2, "scheduled": 0, "ready": 0, "running": 2, "blocked": 11, "review": 1, "done": 178, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T063021Z
- ветка обмена: f88ccb238b047051845f408de343a84027f2ca1c
- publish_state: f88ccb238b04
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
