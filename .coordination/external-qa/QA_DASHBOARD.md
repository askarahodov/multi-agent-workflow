# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T110012Z |
| время сбора (UTC) | 2026-10-14T11:00:12Z |
| главная ветка (main) | d1f621646bcfefb88277a57660c004d648f2a0f4 |
| ветка обмена (coord/external-qa) | d1ba0ff311044d46ac29880aec47378dc678ba88 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | CI conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 13; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

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
{"triage": 0, "todo": 2, "scheduled": 0, "ready": 0, "running": 0, "blocked": 13, "review": 1, "done": 186, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T110012Z
- ветка обмена: d1ba0ff311044d46ac29880aec47378dc678ba88
- publish_state: d1ba0ff31104
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
