# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T071246Z |
| время сбора (UTC) | 2026-10-14T07:12:46Z |
| главная ветка (main) | bd616de7bab27dc69e951dc2fa23181294290c67 |
| ветка обмена (coord/external-qa) | 8dfab5b76653d84949de6ebf3bf1f67fa9fc949a |
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
| `t_f414c513` | me | running | sdlc-security | 0 | worker exited cleanly (rc=0) without kanban_complete, kanban |
- заблокировано: 11; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-INDEPENDENT-DEVELOPMENT-CHECKPOINT` | — |
| `QA-RSP-20261013-COMPOSE-GREEN` | — |
| `QA-RSP-20261013-HERMES-DISPATCHER-INCIDENT` | — |
| `QA-RSP-20261013-PAID-PROVIDER-RECOVERY` | — |
| `QA-RSP-20261013-DASHBOARD-AUTOMATION` | — |
| `QA-RSP-20261013-SNAPSHOT-134801Z` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED` | — |
- открытых QA-кейсов: 4

## task_counts
```json
{"triage": 0, "todo": 3, "scheduled": 0, "ready": 0, "running": 1, "blocked": 11, "review": 1, "done": 179, "archived": 3}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T071246Z
- ветка обмена: 8dfab5b76653d84949de6ebf3bf1f67fa9fc949a
- publish_state: 5fa42d429b14
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
