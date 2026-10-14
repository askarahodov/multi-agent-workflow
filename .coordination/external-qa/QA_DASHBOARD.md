# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261014T091512Z |
| время сбора (UTC) | 2026-10-14T09:15:12Z |
| главная ветка (main) | 91568206d4a3c7048ec610f4d4e92526e3f68171 |
| ветка обмена (coord/external-qa) | 355b4861aa6a21054597e7423d3358cdb12f4e58 |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 1 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | нет прогона на main в окне |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- событий rate_limited с прошлого snapshot: 4.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_82572d91` | default | ready | sdlc-developer | 0 | pid 1118825 exited rate-limited (quota wall) — requeued with |
| `t_d3e747d2` | me | ready | sdlc-developer | 0 |  |
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
| `t_44acc72b` | me | running | sdlc-tester | 0 |  |
- заблокировано: 11; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261013-DASHBOARD-AUTOMATION` | — |
| `QA-RSP-20261013-SNAPSHOT-134801Z` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001` | — |
| `QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED` | — |
| `QA-RSP-20261014-SUBSTANCE-ROOT-CAUSE` | — |
| `QA-RSP-20261014-ARCHIVE-OVERWRITE` | — |
| `QA-RSP-20261014-P0A-REVIEW` | — |
| `QA-RSP-20261014-P2C-REVIEW` | — |
- открытых QA-кейсов: 7

## task_counts
```json
{"triage": 0, "todo": 6, "scheduled": 0, "ready": 2, "running": 1, "blocked": 11, "review": 1, "done": 180, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261014T091512Z
- ветка обмена: 355b4861aa6a21054597e7423d3358cdb12f4e58
- publish_state: 355b4861aa6a
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=UNAVAILABLE
