# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T081127Z |
| время сбора (UTC) | 2026-10-14T08:11:27Z |
| главная ветка (main) | bd616de7bab27dc69e951dc2fa23181294290c67 |
| ветка обмена (coord/external-qa) | 41068bdfa328cfd1523f51297916ca8cb0742683 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 1 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | нет прогона на main в окне |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_44acc72b` | me | running | sdlc-tester | 1 | Iteration budget exhausted (60/60) — task could not complete |
- заблокировано: 11; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| — | — |
- открытых QA-кейсов: 0

## task_counts
```json
{"triage": 0, "todo": 1, "scheduled": 0, "ready": 0, "running": 1, "blocked": 11, "review": 1, "done": 180, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T081127Z
- ветка обмена: 41068bdfa328cfd1523f51297916ca8cb0742683
- publish_state: cf952511651b
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
