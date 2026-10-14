# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T084755Z |
| время сбора (UTC) | 2026-10-14T08:47:55Z |
| главная ветка (main) | 419e3f004b88bb41efe498b4d34999f2b20fd104 |
| ветка обмена (coord/external-qa) | 419e3f004b88bb41efe498b4d34999f2b20fd104 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Quality Gate conclusion= |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
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
- источник: status/current.md @ UTC-20261014T084755Z
- ветка обмена: 419e3f004b88bb41efe498b4d34999f2b20fd104
- publish_state: 419e3f004b88
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
