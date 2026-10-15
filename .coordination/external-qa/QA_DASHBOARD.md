# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T073009Z |
| время сбора (UTC) | 2026-10-15T07:30:09Z |
| главная ветка (main) | e54de686627f7841df475265c8f7bf31485eb7b7 |
| ветка обмена (coord/external-qa) | efc120ac013898297adda020b0bd610f35445d3d |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 2 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Coordination channel isolation conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_17b85467` | default | running | sdlc-tester | 0 |  |
| `t_9dc415ec` | me | running | sdlc-developer | 0 |  |
- заблокировано: 12; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-SNAPSHOT-134801Z` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED` | — |
| `QA-RSP-20261014-SUBSTANCE-ROOT-CAUSE` | — |
| `QA-RSP-20261014-ARCHIVE-OVERWRITE` | — |
| `QA-RSP-20261014-P0A-REVIEW` | — |
| `QA-RSP-20261014-P2C-REVIEW` | — |
| `QA-RSP-20261014-P1-ARCHIVE-INDEX-INTEGRITY` | — |
- открытых QA-кейсов: 8

## task_counts
```json
{"triage": 0, "todo": 10, "scheduled": 0, "ready": 0, "running": 2, "blocked": 12, "review": 1, "done": 186, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T073009Z
- ветка обмена: efc120ac013898297adda020b0bd610f35445d3d
- publish_state: efc120ac0138
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
