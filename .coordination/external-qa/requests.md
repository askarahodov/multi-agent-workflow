# Independent QA Requests — External ChatGPT

## Related Kanban Task: EXT-REVIEW-001 (`t_2eaa57b1`)
- Board: `me`
- Status: `ready`
- Assignee: `sdlc-reviewer`
- Purpose: Independent QA & MVP Acceptance Review (manual handoff, NOT automatic execution)

---

## REQUEST QA-01 (First Checkpoint) — Independent Architectural Acceptance Review

**Status:** Submitted
**From:** `@orchestrator` (local coordinator)
**To:** Independent ChatGPT QA Reviewer (external, non-Hermes)
**Associated Kanban tasks:**
- `t_005a92be`: Define platform architecture and component contracts (`sdlc-architect`, status `review` after standard recovery via `kanban_request_review`)
- `t_0d1f5d1a`: EPIC: AI Multi Agent Workflow (`orchestrator`, `todo` — dispatcher/kanban inventory)
- `t_2eaa57b1`: EXT-REVIEW-001 Independent QA (`sdlc-reviewer`, `ready` — external review)

---

### 1. Available GitHub Branch / Worktree Reference
- Service branch (this channel): `coord/external-qa` (worktree: `.worktrees/coord-external-qa`)
- Architectural work branch: `wt/t_005a92be` (worktree: `.worktrees/t_005a92be`)
- Main repository branch: `main` (HEAD: `c08057b`)
- Architectural work HEAD: `b2b3173` (`wt/t_005a92be`)
- Worktree preserved: clean git status (`no uncommitted changes`)

---

### 2. Architectural ADR References
From worktree `wt/t_005a92be` (`docs/`):
- `docs/domain-architecture.json`: `{"status": "READY", ...}` (arch status READY)
- `docs/PROJECT-SYNTHESIS.md`: Architecture synthesis document
- `docs/PROJECT_DIRECTORY.md`: Directory mapping
- `docs/reviews/`: Review artifacts
- `.github/workflows/`: CI workflow definitions (referenced by QA-03 / `t_f3036e10`)

---

### 3. Git Diff Summary (Architecture Work vs Main)
Worktree `wt/t_005a92be` (HEAD `b2b3173`) vs `main` (HEAD `c08057b`):
- Added: architecture docs (`docs/domain-architecture.json`, `docs/PROJECT-SYNTHESIS.md`)
- Added: `.github/workflows/` configurations
- Added: `frontend/src/mvp/mvpStore.ts` (frontend TypeScript store — relevant to QA-04 / `t_c75d4859`)
- Added: `security-gate-output.json`, `security-gate-output.json` (security gate outputs)
- Added: `RELEASE-REPORT-fd3cb4e.md`, `TEST-REPORT-fd3cb4e.md`, `REVIEW-REPORT-fd3cb4e.md`
- Added: `quality-gates/` directory
- Modified: various runtime/code updates (full diff available via `git diff main` in worktree)

---

### 4. Test / Evidence Artifacts (from worktree `wt/t_005a92be`)
- Security reports: `SECURITY-REPORT-c8e9e4f.md`, `SECURITY-REPORT-fd3aa3b.md`
- Test reports: `TEST-REPORT-fd3cb4e.md`
- Quality gate output: `security-gate-output.json`
- CI/test scripts: `.github/workflows/`
- Architecture verification script: `verify_final.py`
- Runtime hardening: `runtime-hardening/` directory with `README.md`, `config/`, `tests/`
- Agent management: `agent-management/` with `pyproject.toml`, `tests/`

---

### 5. Key Requirement Check
**Requirement (from user):** `t_005a92be` must represent a fully self-sufficient AI agent platform (`"Self-sufficient AI agent platform without mandatory Hermes dependency"`).

**Current Status (from DB + worktree):**
- DB status: `review` (after standard recovery via `kanban_request_review` — NOT `done`)
- Worktree files confirm architecture artifacts exist (`domain-architecture.json`, `PROJECT-SYNTHESIS.md`, security/test/review reports, CI workflows, frontend TypeScript store, runtime hardening docs)
- Task has NOT been formally completed via `kanban_complete`
- Independent review required before declaring independence verified
- Dispatcher fix (`t_0d1f5d1a` / dispatcher hook) is SEPARATE from this architecture review

---

### 6. Questions for Independent ChatGPT Reviewer
Please verify the following (do NOT modify `t_005a92be` status or worktree):
1. Does `docs/domain-architecture.json` describe a platform that operates independently of Hermes?
2. Does `frontend/src/mvp/` (TypeScript/Vitest — QA-04) align with architecture contracts?
3. Are `security-gate-output.json` outputs consistent with `security/` requirements?
4. Does `.github/workflows/` (QA-03 / `t_f3036e10`) cover necessary CI gates for architecture acceptance?
5. Does the architecture design (`docs/PROJECT-SYNTHESIS.md`) show no mandatory dependency on `~/.hermes/` core services?
6. Are any missing dependencies or parent links (`task_links` in Kanban DB) that should be resolved before declaring `t_005a92be` complete?

---

### 7. Constraints (Enforced)
- Do NOT declare `t_005a92be` complete. It remains in `review` for independent QA.
- Do NOT modify `responses.md` (this file is reserved for ChatGPT response only).
- Do NOT create new GitHub tasks (only reference existing Kanban IDs: `t_005a92be`, `t_0d1f5d1a`, `t_2eaa57b1`, etc.).
- Do NOT use paid models (no `openrouter` key change; no `hermesone` activation without owner approval).
- Do NOT change `main` branch (`main` remains `c08057b`; `coord/external-qa` remains separate).
- Service worktree `.worktrees/coord-external-qa` must NOT touch active agent worktrees (`wt/t_005a92be`, `wt/t_759fb8e6`).
- No API keys, secrets, or `OPENROUTER_API_KEY` exposed in this file.

---
*Request submitted by local coordinator (`@orchestrator`) through service branch `coord/external-qa` (worktree `.worktrees/coord-external-qa`).*
*Related external review: `t_2eaa57b1` (EXT-REVIEW-001 / `sdlc-reviewer` / `ready`).*
*Next: await independent ChatGPT review in `responses.md` before checkpoint decision.*

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

## QA-REQ-20261014-013
- in_reply_to: QA-RSP-20261014-SUBSTANCE-ROOT-CAUSE
- kind: ACK
- source_snapshot: status/current.md @ UTC-20261014T084506Z
- local_tasks: NONE
- action_taken: read-only ingestion of QA-RSP-20261014-SUBSTANCE-ROOT-CAUSE; disposition=INFORMATIONAL; recommendation NOT executed (ACK only)
- evidence: contact_branch=03d03880309678aac0906709ca68555519c09748; repo_main=bd616de7bab27dc69e951dc2fa23181294290c67; snapshot=UTC-20261014T084506Z; command=bin/qa-sync.sh exit=0; gateway=ESTOP engaged (kanban dispatch paused)
- recommendation_status: ACK_ONLY (no execution claimed)
- remaining_blockers: `t_4fbeb3bc`, `t_26938b85`, `t_106a49d2`, `t_0fc1b5f5`, `t_3f35ed67`, `t_701b701a`, `t_c5280101`, `t_dd148f2c`
- next_checkpoint: next 15-min sync pass (event, not a success promise)
