# Активные вопросы QA
- snapshot_id: UTC-20261013T144800Z
- generated_at_utc: 2026-10-13T14:48:00Z
- status_source: status/current.md @ UTC-20261013T144800Z
- main_sha: ca77e4565f071f95049541193ad655914677a9f7
- inbox_revision: e7727e7af9c95e1eeb722354460eff5176617017
- total_unanswered: 1
- total_open_cases: 5
- retention_version: 1

## Новые QA-запросы (только без независимого ответа)
| req_id | kind | in_reply_to | task_id | evidence_ref |
|---|---|---|---|---|
| QA-REQ-20261013-P0A | REVIEW_REQUEST | QA-RSP-20261013-P0-RETENTION-ACTION | `t_26938b85` (dir-workspace), эскалация dispatcher (локальны | - patch: локальный Hermes `hermes_cli/kanban_db.py`, `hermes_cli/kanban_db_dispa |

## Открытые вопросы/блокеры (не весь transcript)
| case_id | owner | task_id | verdict | next_action | evidence_ref |
|---|---|---|---|---|---|
| QA-CAS-20261013-HANDOFF-BLOCKED | @orchestrator | t_005a92be, t_2eaa57b1 | BLOCKED | publish REVIEW_REQUEST with diff/SHA/tests | responses.md#QA-RSP-20261013-HANDOFF-BLOCKED |
| QA-CAS-20261013-PAID-PROVIDER-RECOVERY | @orchestrator | t_005a92be, t_26938b85 | WORKERS | publish REVIEW_REQUEST with diff/SHA/tests | responses.md#QA-RSP-20261013-PAID-PROVIDER-RECOVERY |
| QA-CAS-20261013-SNAPSHOT-134801Z | @orchestrator | t_005a92be, t_26938b85 | CHANGES_REQUESTED | publish REVIEW_REQUEST with diff/SHA/tests | responses.md#QA-RSP-20261013-SNAPSHOT-134801Z |
| QA-CAS-20261013-CONTRACT-PROBE-001 | @orchestrator | NONE | CHANGES_REQUESTED | publish REVIEW_REQUEST with diff/SHA/tests | responses.md#QA-RSP-20261013-CONTRACT-PROBE-001 |
| QA-CAS-20261013-P0-RETENTION-ACTION | @orchestrator | t_26938b85 | ACTION_REQUIRED | publish REVIEW_REQUEST with diff/SHA/tests | responses.md#QA-RSP-20261013-P0-RETENTION-ACTION |

## Недавно решено
- см. `archive/requests-index.json` (immutable, только для ручного аудита)
