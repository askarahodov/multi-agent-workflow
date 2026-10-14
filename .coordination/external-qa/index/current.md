# Активные вопросы QA
- snapshot_id: UTC-20261014T084805Z
- generated_at_utc: 2026-10-14T08:48:05Z
- status_source: status/current.md @ UTC-20261014T084805Z
- main_sha: 546f64da2d1f38b30432befd83200f28c808f34b
- inbox_revision: 546f64da2d1f38b30432befd83200f28c808f34b
- total_unanswered: 3
- total_open_cases: 1
- retention_version: 1

## Новые QA-запросы (только без независимого ответа)
| req_id | kind | in_reply_to | task_id | evidence_ref |
|---|---|---|---|---|
| QA-REQ-20261013-P0A | REVIEW_REQUEST | QA-RSP-20261013-P0-RETENTION-ACTION | `t_26938b85` (dir-workspace), эскалация dispatcher (локальны | - patch: локальный Hermes `hermes_cli/kanban_db.py`, `hermes_cli/kanban_db_dispa |
| QA-REQ-20261013-P1B | REVIEW_REQUEST | QA-RSP-20261013-P0-RETENTION-ACTION | retention локального qa-sync (не продуктовый Kanban) | - код: `qasync/retention.py` (публикуется как `.coordination/external-qa/sync/re |
| QA-REQ-20261013-P2C | REVIEW_REQUEST | QA-RSP-20261013-P0-RETENTION-ACTION | `render.py::render_dashboard` (локальный qa-sync) | - файл: `QA_DASHBOARD.md` на ветке (язык — русский) |

## Открытые вопросы/блокеры (не весь transcript)
| case_id | owner | task_id | verdict | next_action | evidence_ref |
|---|---|---|---|---|---|
| QA-CAS-20261013-HANDOFF-BLOCKED | @orchestrator | t_005a92be, t_2eaa57b1 | BLOCKED | publish REVIEW_REQUEST with diff/SHA/tests | responses.md#QA-RSP-20261013-HANDOFF-BLOCKED |

## Недавно решено
- см. `archive/requests-index.json` (immutable, только для ручного аудита)
