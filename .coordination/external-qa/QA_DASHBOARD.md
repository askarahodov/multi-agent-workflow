# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T093004Z |
| время сбора (UTC) | 2026-10-14T09:30:04Z |
| главная ветка (main) | 91568206d4a3c7048ec610f4d4e92526e3f68171 |
| ветка обмена (coord/external-qa) | 4211308e8ff4834798e6c3150015891f01fd7470 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 1 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Quality Gate conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- событий rate_limited с прошлого snapshot: 2.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_82572d91` | default | running | sdlc-developer | 0 | pid 1135182 exited rate-limited (quota wall) — requeued with |
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
{"triage": 0, "todo": 3, "scheduled": 0, "ready": 0, "running": 1, "blocked": 13, "review": 1, "done": 184, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T093004Z
- ветка обмена: 4211308e8ff4834798e6c3150015891f01fd7470
- publish_state: 50326cfa107e
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
