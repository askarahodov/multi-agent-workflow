# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261013T144800Z |
| время сбора (UTC) | 2026-10-13T14:48:00Z |
| главная ветка (main) | ca77e4565f071f95049541193ad655914677a9f7 |
| ветка обмена (coord/external-qa) | e7727e7af9c95e1eeb722354460eff5176617017 |
| доски Kanban | default, boards, ct-gate, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | нет прогона на main в окне |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25ec9e17` | me | ready | sdlc-developer | 0 |  |
| `t_31363350` | me | ready | sdlc-fixer | 0 |  |
| `t_ad602ad8` | me | ready | sdlc-architect | 0 |  |
| `t_c75d4859` | me | ready | sdlc-reviewer | 0 |  |
| `t_f414c513` | me | ready | sdlc-security | 0 |  |
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 11; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-COMPOSE-GREEN` | — |
| `QA-RSP-20261013-HERMES-DISPATCHER-INCIDENT` | — |
| `QA-RSP-20261013-PAID-PROVIDER-RECOVERY` | — |
| `QA-RSP-20261013-DASHBOARD-AUTOMATION` | — |
| `QA-RSP-20261013-SNAPSHOT-134801Z` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED` | — |
| `QA-RSP-20261013-P0-RETENTION-ACTION` | — |
- открытых QA-кейсов: 5

## task_counts
```json
{"triage": 0, "todo": 2, "scheduled": 0, "ready": 5, "running": 0, "blocked": 11, "review": 1, "done": 175, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261013T144800Z
- ветка обмена: e7727e7af9c95e1eeb722354460eff5176617017
- publish_state: e7727e7af9c9
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
