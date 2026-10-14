# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T084741Z |
| время сбора (UTC) | 2026-10-14T08:47:41Z |
| главная ветка (main) | bd616de7bab27dc69e951dc2fa23181294290c67 |
| ветка обмена (coord/external-qa) | bd616de7bab27dc69e951dc2fa23181294290c67 |
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
| `t_82572d91` | default | ready | sdlc-developer | 0 | pid 1049201 exited rate-limited (quota wall) — requeued with |
| `t_d3e747d2` | me | ready | sdlc-developer | 0 | pid 1053225 exited rate-limited (quota wall) — requeued with |
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 12; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-BOOTSTRAP` | — |
| `QA-RSP-20261013-HANDOFF-BLOCKED` | — |
- открытых QA-кейсов: 1

## task_counts
```json
{"triage": 0, "todo": 6, "scheduled": 0, "ready": 2, "running": 0, "blocked": 12, "review": 1, "done": 180, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T084741Z
- ветка обмена: bd616de7bab27dc69e951dc2fa23181294290c67
- publish_state: 15d765a49fee
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
