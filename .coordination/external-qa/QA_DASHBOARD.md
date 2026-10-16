# Панель QA

> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.
> Публикуется атомарно с ним. Руками не редактировать.

## Общая картина
| поле | значение |
|---|---|
| snapshot_id | UTC-20261016T150005Z |
| время сбора (UTC) | 2026-10-16T15:00:05Z |
| главная ветка (main) | 295a8bc87425a691224cba6664dee38e383e3fbb |
| ветка обмена (coord/external-qa) | fee8408193766f841a669b38b49a54bdde01bfea |
| доски Kanban | default, boards, ct-gate, harbor-transfer-portal, me |
| активных воркеров | 0 |
| ESTOP | ВКЛЮЧЁН (ESTOP) |
| последняя проверка CI (main) | Native agent cross-service E2E conclusion=success |

## Текущие риски
- kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.
- событий rate_limited с прошлого snapshot: 1.
- невалидный dir-workspace: t_26938b85 (парковать).

## Активные задачи (Kanban)
| задача | доска | статус | исполнитель | попыток | последняя ошибка |
|---|---|---|---|---|---|
| `t_25b2b984` | default | review | sdlc-architect | 0 | pid 599797 exited rate-limited (quota wall) — requeued witho |
- заблокировано: 13; в т.ч. `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_3f35ed67`, `t_17b85467`, `t_a537ba5a`

## Последние QA-вердикты (QA ≠ Kanban)
| QA-ответ | вердикт |
|---|---|
| `QA-RSP-20261015-SQLITE-FENCE-HANDOFF` | INFO |
| `QA-RSP-20261015-DURABLE-ATTEMPT-LEASE-HANDOFF` | INFO |
| `QA-RSP-20261015-HTTP-LEASE-RENEWAL-HANDOFF` | INFO |
| `QA-RSP-20261015-ATOMIC-LEASE-PR51-INDEPENDENT-REVIEW` | INFO / CONDITIONAL (CI final head must be checked) |
| `QA-RSP-20261015-PR50-PR51-ALL-GATES-GREEN` | INFO / CHECKPOINT_ACHIEVED (all GitHub CI green on exact feature heads, NOT production release) |
| `QA-RSP-20261015-TRUSTED-FS-GATEWAY-HANDOFF` | INFO / READY_FOR_REVIEW; production acceptance explicitly NOT_GRANTED |
| `QA-RSP-20261015-LEASED-GATEWAY-ENDTOEND-HANDOFF` | INFO / READY_FOR_INDEPENDENT_REVIEW; no production acceptance |
| `QA-RSP-20261015-LEASE-ISSUE-TTL-CONTENTION-FIX` | INFO / CODE_REVIEW_P2_FIXED / FULL_CI_GREEN |
- открытых QA-кейсов: 10

## task_counts
```json
{"triage": 0, "todo": 4, "scheduled": 0, "ready": 0, "running": 0, "blocked": 13, "review": 1, "done": 197, "archived": 4}
```

## Следующий checkpoint
- индексированных новых запросов: см. `index/current.md`
- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).

## Доказательства / время обновления
- источник: status/current.md @ UTC-20261016T150005Z
- ветка обмена: fee8408193766f841a669b38b49a54bdde01bfea
- publish_state: fee840819376
- доступность источников: kanban=OK, git=VERIFIED, gateway=VERIFIED, ci=VERIFIED
