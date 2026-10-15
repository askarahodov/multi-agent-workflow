# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261015T074853Z |
| время сбора (UTC) | 2026-10-15T07:48:53Z |
| главная ветка (main) | e54de686627f7841df475265c8f7bf31485eb7b7 |
| ветка обмена (coord/external-qa) | 86b4005bb74c8b229f6be82344908ba6e027c73d |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 3 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Coordination channel isolation conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_17b85467` | default | running | sdlc-tester | 1 | Iteration budget exhausted (60/60) — task could not complete |
| `t_a537ba5a` | default | running | sdlc-tester | 0 |  |
| `t_bc3bba05` | me | running | orchestrator | 0 |  |
- заблокировано: 12; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| — | — |
- открытых QA-кейсов: 0

## task_counts
```json
{"triage": 0, "todo": 11, "scheduled": 0, "ready": 0, "running": 3, "blocked": 12, "review": 1, "done": 187, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261015T074853Z
- ветка обмена: 86b4005bb74c8b229f6be82344908ba6e027c73d
- publish_state: 785cf5896b62
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
