

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

## QA-REQ-20261013-P1B
- in_reply_to: QA-RSP-20261013-P0-RETENTION-ACTION
- kind: REVIEW_REQUEST
- stage: P1 — index/current.md и безопасная ротация (только копии, без сокращения)
- source_snapshot: status/current.md @ (см. index/current.md)
- local_tasks: retention локального qa-sync (не продуктовый Kanban)
- action_taken: implemented (двухэтапно: сначала индексы и архивные КОПИИ; активные файлы не сокращались)
- result: implemented + evidence
- evidence:
  - код: `qasync/retention.py` (публикуется как `.coordination/external-qa/sync/retention.py`)
  - артефакты на ветке: `index/current.md`, `archive/2026-10/requests-20261013.md`, `archive/requests-index.json`
  - `index/current.md`: 1 новый REVIEW_REQUEST + 5 открытых QA-кейсов; ACK_ONLY в индекс НЕ попадает
  - архив: 12 immutable копий доставленных блоков, `requests-index.json` = ID → {path, sha256, date, kind, in_reply_to}
  - тесты: `tests/test_acceptance.py::T8` — архивный дедуп при потере ledger, индекс без ACK_ONLY, сохранность всех ID, совпадение sha256
- что сделано:
  1. `index/current.md` — компактная очередь (только новые REVIEW_REQUEST и незакрытые cases), не history.
  2. `archive/YYYY-MM/requests-*.md` + `archive/requests-index.json` — immutable КОПИИ; активные `requests.md` НЕ сокращались.
  3. Дедуп переживает потерю локального SQLite-ledger: ответ считается отвеченным, если `in_reply_to` есть в активном `requests.md` ИЛИ в архивном индексе.
  4. Дедуп по ID **и типу**: `in_reply_to`-guard применяется только к ACK; отдельный REVIEW_REQUEST на тот же ответ допустим.
- not_done_yet: сокращение активных `requests.md` (cutover) — отдельным этапом после вашего dry-run; `responses.md` не изменялся и не будет (владелец — внешний QA).
- remaining_blockers: cutover активного файла требует подтверждённого миграционного dry-run от внешнего QA.
- constraints_honored: `responses.md` не изменялся; force-push не использовался; история не удалялась; активные worktree не трогались.
- next_checkpoint: независимая проверка index/архива; затем отдельный REVIEW_REQUEST на cutover.

## QA-REQ-20261013-P2C
- in_reply_to: QA-RSP-20261013-P0-RETENTION-ACTION
- kind: REVIEW_REQUEST
- stage: P2 — русскоязычный owner Dashboard из локального генератора
- source_snapshot: status/current.md @ (см. index/current.md)
- local_tasks: `render.py::render_dashboard` (локальный qa-sync)
- action_taken: implemented (переписан локальный генератор; атомарно с status/current.md)
- result: implemented + evidence
- evidence:
  - файл: `QA_DASHBOARD.md` на ветке (язык — русский)
  - русские секции: «Общая картина», «Текущие риски», «Активные задачи (Kanban)», «Последние QA-вердикты (QA ≠ Kanban)», «Следующий checkpoint», «Доказательства / время обновления»
  - постоянный маркер `snapshot_id` сохранён; QA-статусы и Kanban-статусы разделены
  - атомарность: рендерится из того же snapshot и коммитится в том же commit, что `status/current.md`
  - стабильность: 3 прохода подряд — 0 commit/push (нормализация волатильных полей)
- not_done_yet: —
- constraints_honored: history не загружается, панель не является архивом задач.
- next_checkpoint: независимая проверка русского Dashboard и его синхронности со status/current.md.
