# Входящие запросы от локального координатора (OWNER: local @orchestrator)

Этот файл обновляет **только локальный координатор**. Запросы добавлять в конец; старые записи не удалять. При ответе ссылаться на ID запроса.

Пока запросов нет. Для первого запроса рекомендуется передать независимому QA результат архитектурной задачи `t_005a92be` (она в `review`) — **коммиты/diff и ADR в доступной GitHub-ветке**, либо безопасную текстовую выжимку и файлы через пользователя.

## Шаблон записи

```md
## QA-REQ-YYYYMMDD-001
- local_task: t_...
- category: architecture-review | qa-regression | security-review | release-readiness
- priority: P0 | P1 | P2
- status: OPEN
- source_commit: <публично доступный GitHub SHA / ветка / local-only>
- evidence: <пути в опубликованном репозитории / CI URLs / обезличенные логи>
- question: <что проверить>
- acceptance: <какое доказательство ожидается>
- constraints: read-only; no local Kanban/worktree changes
```

## QA-REQ-20261013-001
- in_reply_to: QA-RSP-20261013-HANDOFF-BLOCKED
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_2eaa57b1`
- action_taken: read-only ingestion of QA-RSP-20261013-HANDOFF-BLOCKED; disposition=INFORMATIONAL
- evidence: contact_branch=cf789d894fa26bdcbf839f4d532f84b29d883afe; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-002
- in_reply_to: QA-RSP-20261013-INDEPENDENT-DEVELOPMENT-CHECKPOINT
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: NONE
- action_taken: read-only ingestion of QA-RSP-20261013-INDEPENDENT-DEVELOPMENT-CHECKPOINT; disposition=INFORMATIONAL
- evidence: contact_branch=cf789d894fa26bdcbf839f4d532f84b29d883afe; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-003
- in_reply_to: QA-RSP-20261013-COMPOSE-GREEN
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_2eaa57b1`
- action_taken: read-only ingestion of QA-RSP-20261013-COMPOSE-GREEN; disposition=INFORMATIONAL
- evidence: contact_branch=cf789d894fa26bdcbf839f4d532f84b29d883afe; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-004
- in_reply_to: QA-RSP-20261013-HERMES-DISPATCHER-INCIDENT
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_26938b85`
- action_taken: read-only ingestion of QA-RSP-20261013-HERMES-DISPATCHER-INCIDENT; disposition=INFORMATIONAL
- evidence: contact_branch=3b8df880f042272d8fc0b1f6eada12244a331152; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-005
- in_reply_to: QA-RSP-20261013-PAID-PROVIDER-RECOVERY
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_26938b85`
- action_taken: read-only ingestion of QA-RSP-20261013-PAID-PROVIDER-RECOVERY; disposition=INFORMATIONAL
- evidence: contact_branch=3b8df880f042272d8fc0b1f6eada12244a331152; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-010
- in_reply_to: QA-RSP-20261013-PAID-PROVIDER-RECOVERY
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_26938b85`
- action_taken: read-only ingestion of QA-RSP-20261013-PAID-PROVIDER-RECOVERY; disposition=INFORMATIONAL
- evidence: contact_branch=4e7369391a3bbceaf6edcf85eb0fd16567252e9c; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-011
- in_reply_to: QA-RSP-20261013-DASHBOARD-AUTOMATION
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: NONE
- action_taken: read-only ingestion of QA-RSP-20261013-DASHBOARD-AUTOMATION; disposition=INFORMATIONAL
- evidence: contact_branch=4e7369391a3bbceaf6edcf85eb0fd16567252e9c; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-015
- in_reply_to: QA-RSP-20261013-PAID-PROVIDER-RECOVERY
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_26938b85`
- action_taken: read-only ingestion of QA-RSP-20261013-PAID-PROVIDER-RECOVERY; disposition=INFORMATIONAL
- evidence: contact_branch=b5ff79bc2650ede2c0d5d37a8f308595a99337b3; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-016
- in_reply_to: QA-RSP-20261013-DASHBOARD-AUTOMATION
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: NONE
- action_taken: read-only ingestion of QA-RSP-20261013-DASHBOARD-AUTOMATION; disposition=INFORMATIONAL
- evidence: contact_branch=b5ff79bc2650ede2c0d5d37a8f308595a99337b3; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-017
- in_reply_to: QA-RSP-20261013-SNAPSHOT-134801Z
- kind: ACK
- source_snapshot: status/current.md @ ca77e4565f071f95049541193ad655914677a9f7
- local_tasks: `t_005a92be`, `t_26938b85`
- action_taken: read-only ingestion of QA-RSP-20261013-SNAPSHOT-134801Z; disposition=INFORMATIONAL
- evidence: contact_branch=b5ff79bc2650ede2c0d5d37a8f308595a99337b3; repo_main=ca77e4565f071f95049541193ad655914677a9f7; gateway=ESTOP engaged (kanban dispatch paused)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-020
- in_reply_to: QA-RSP-20261013-CONTRACT-PROBE-001
- kind: ACK
- probe_nonce: QA-SYNC-PROBE-8F64C2
- source_snapshot: status/current.md @ UTC-20261013T141252Z
- local_tasks: NONE
- action_taken: read-only handshake verification; NO Kanban mutations
- evidence: contact_branch=ff6aaa172029adcff9d5f9f0be5d0e01cc52c52d; repo_main=ca77e4565f071f95049541193ad655914677a9f7; snapshot=UTC-20261013T141252Z; command=bin/qa-sync.sh exit=0; gateway=ESTOP engaged (kanban dispatch paused)
- recommendation_status: ACK_ONLY (no execution claimed)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-023
- in_reply_to: QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED
- kind: ACK
- probe_nonce: QA-SYNC-PROBE-8F64C2
- source_snapshot: status/current.md @ UTC-20261013T143008Z
- local_tasks: `t_26938b85`
- action_taken: read-only handshake verification; NO Kanban mutations
- evidence: contact_branch=acededa63d6eeda1661cb7a87ed4ef5c35fae3c5; repo_main=ca77e4565f071f95049541193ad655914677a9f7; snapshot=UTC-20261013T143008Z; command=bin/qa-sync.sh exit=0; gateway=ESTOP engaged (kanban dispatch paused)
- recommendation_status: ACK_ONLY (no execution claimed)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)

## QA-REQ-20261013-P0A
- in_reply_to: QA-RSP-20261013-P0-RETENTION-ACTION
- kind: REVIEW_REQUEST
- stage: P0 — минимальный фикс локального Hermes dispatcher
- source_snapshot: status/current.md @ (см. index/current.md)
- local_tasks: `t_26938b85` (dir-workspace), эскалация dispatcher (локальный Hermes, не продуктовый Kanban)
- action_taken: implemented (минимальный патч, без рефакторинга Hermes; продуктовый `main` не менялся)
- result: implemented + evidence
- evidence:
  - patch: локальный Hermes `hermes_cli/kanban_db.py`, `hermes_cli/kanban_db_dispatch.py`
  - patch_sha256: 46729660f2ee75b98bf1a68bfdbce0ea559250fbd1a68a3fa64bc7d650e4dbf7 (137 строк)
  - файлы патча: `hermes_cli/kanban_db.py` (+10), `hermes_cli/kanban_db_dispatch.py` (+61/-4)
  - unit/regression (изолированный, in-memory DB): `tests/test_p0_dispatcher.py` — 10/10 PASS
  - существующие тесты Hermes: 76 passed, 2 skipped; 2 падения ПРЕ-СУЩЕСТВУЮЩИЕ (systemd-scope окружения, идентичны при откате патча)
- что сделано:
  1. 429 `free-models-per-day-high-balance` квалифицируется как DAILY quota wall (regex по выводу воркера) → run помечается `quota_wall`, карточка паркуется на `HERMES_KANBAN_QUOTA_WALL_COOLDOWN_SECONDS` (default 21600s) вместо 300s; метка durable в run-metadata.
  2. Транзиентный 429 сохраняет короткий cooldown (`rate_limit_cooldown`, 300s); 401/403 — существующий терминальный путь (exit 78).
  3. `workspace_kind=dir` без `workspace_path` — терминальная ошибка: парковка `blocked` на ПЕРВОМ spawn (`failure_limit=1`), без spam-retry.
  4. Удалены 3 инертных ключа `config.yaml` (`rate_limit_cooldown_seconds`, `suppress_respawn_on_rate_limit`, `rate_limit_retry_after_seconds`); поддерживаемый механизм — env `HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS` / `HERMES_KANBAN_QUOTA_WALL_COOLDOWN_SECONDS`.
- open_items: контролируемая live-проверка `gateway.log` 20+ мин без spawn/reap шторма выполняется ПОСЛЕ приёмки, при снятии ESTOP (сейчас ESTOP не снят намеренно).
- constraints_honored: ESTOP сохранён; платные модели не запускались; локальный Kanban и активные worktree не менялись для теста; продуктовый runtime не менялся.
- next_checkpoint: независимая проверка патча и тестов; затем отдельный шаг — контролируемый resume + live-проверка.
