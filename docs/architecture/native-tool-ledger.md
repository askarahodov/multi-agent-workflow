# Durable claim ledger for native tool calls (Issue #27)

**Scope:** at-most-once reservation of a tool-call ID in a trusted task scope,
including after the Python process restarts. This is not exactly-once execution
and is not a substitute for distributed transaction coordination, sandboxing or
the orchestration Contract Gate.

## Design

The **trusted control plane** supplies both an absolute path to a private
SQLite database and a stable scope identifier, e.g. `run-123/task-456`. Neither
is derived from a model response. The ledger is stored outside the assigned
workspace and must be protected by OS ownership/permissions (`0600`).
The database stores only `scope`, `call_id`, a safe tool name and `state`.

```text
CLAIMED       ← atomic SQLite insert BEFORE any tool I/O
    ├─ success ──→ SUCCEEDED
    └─ denial  ──→ DENIED
```

A repeated `(scope, call_id)` returns `DUPLICATE_CALL` regardless of whether
the original claim is `CLAIMED`, `SUCCEEDED` or `DENIED`. An interruption
between claim and outcome leaves an ambiguous `CLAIMED`. It must be
**reconciled by the orchestrator**, not replayed automatically.

### Trusted use

```python
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.tool_ledger import SqliteToolLedger

fs = ScopedFilesystemExecutor(
    "/srv/workspaces/task-456",
    {"fs_write": ["/srv/workspaces/task-456/out/**"]},
)
ledger = SqliteToolLedger("/var/lib/multi-agent/ledger/tool-claims.sqlite3")
dispatcher = NativeFilesystemDispatcher(
    fs, ledger=ledger, execution_scope="run-123/task-456",
)
```

With no ledger, the dispatcher retains previous **in-memory only** duplicate
protection for offline tests. Production worker integration MUST explicitly
supply the ledger. Ledger failures are fail-closed before tool execution.
If updating `SUCCEEDED` fails after a write, the prior durable `CLAIMED`
survives and blocks replay by another dispatcher.

## Дополнительный pre-I/O guard прерванной попытки (#33/#38)

`NativeFilesystemDispatcher` принимает **необязательный** доверенный
callback `attempt_active: Callable[[], bool]`, который создаётся control
plane, а не моделью и не из аргументов tool_call. Callback допускается
**только при наличии durable `SqliteToolLedger` + execution_scope**.

После атомарного claim конкретного tool_call в SQLite, проверки имени
инструмента и аргументов — непосредственно перед новым read/write —
диспетчер запрашивает `attempt_active()`. Строгое `True` позволяет
начать I/O; `False`, не-boolean и **любое исключение** дают обезличенный
`ATTEMPT_FENCED`; инструмент не вызывается, ledger фиксирует
`DENIED`, повторный call_id отклоняется. Секреты/путь из исключения не
попадают к LLM или в in-memory audit. При сбое ledger переход остаётся
fail-closed по прежнему контракту.

**Важные границы:** это **pre-execution guard**, а не полная реализация
distributed fencing. Callback в текущем offline native bridge/worker ещё
не подключён к проверяемому server-issued attempt generation/lease.
Если callback не передан, остаётся прежнее поведение. Даже при
корректном callback возможна гонка `check → revocation → side effect`
или side effect уже запущенной файловой операции. Нельзя объявлять
#38/#33 безопасными до durable generation/lease, сериализации revoke
с побочным действием, отмены/drain, кросс-процессного E2E и review.
Нельзя использовать model-controlled флаг как источник истины.

Регрессии без LLM и платных провайдеров:
`python -m pytest tests/test_tool_ledger.py -q` в `agent-management/`.

## Server-owned SQLite execution barrier: новая стадия #38/#33

Для **доверенного исполнителя на том же локальном файловом хранилище**
существует `shared.attempt_fence.TrustedSqliteAttemptFence`.
Она принимает абсолютный путь к **реальной SQLite-базе оркестратора**
и `run_id/task_id/attempt_id/agent_id` исключительно от control plane
после успешного `OrchestrationEngine.claim_task`. Эти значения **не**
передаются через сообщения LLM и не могут выбираться из tool_call.

При наличии `SqliteToolLedger` можно передать эту структуру
`NativeFilesystemDispatcher(..., attempt_fence=fence)`. Диспетчер
проверяет совпадение `execution_scope` и наличие доверенного ledger.

Непосредственно перед каждым `read_file/write_file` выполняется
`BEGIN IMMEDIATE` **на той же SQLite БД, в которой OrchestrationEngine
меняет статус попытки**. Проверяются статусы `running/in_progress/busy`,
владелец агента и `run_id`. Транзакция удерживается до окончания
файловой операции. Следовательно, `recover()/submit()/fail()`
не могут **зафиксировать** перевод той же БД в другое состояние до
окончания ранее допущенной операции. После успешного commit recovery
новый tool_call старой попытки отклоняется `ATTEMPT_FENCED`
с ledger `DENIED`, без изменения файлов. Тайм-аут или ошибка
БД также означают запрет операции.

Это сильнее независимой проверки `attempt_active()`: здесь
`check → filesystem I/O` сериализован с серверным SQL-переходом.

**Жёсткие условия эксплуатации:**

- Только **SQLite на одном доверенном локальном томе**, где действуют
  межпроцессные блокировки; не использовать NFS, несколько хостов,
  PostgreSQL или другой внешний источник состояния.
- Доверенный worker имеет доступ к SQLite (режим `rw` необходим для
  `BEGIN IMMEDIATE`). Поэтому запускать gate следует только внутри
  **привилегированного tool-executor**, а не в недоверенном процессе
  модели. Доступ к БД должен быть ограничен: приватный обычный файл
  `0600`, владелец — сервис, путь за пределами workspace; директории
  защищены от модификации агентами. Это модель доверенного хоста,
  не безопасная схема для удалённых исполнителей.
- Длительный/зависший I/O может удерживать SQLite write lock;
  администратор не вправе считать восстановление успешным до
  фактического commit. Используются ограниченные операции
  `ScopedFilesystemExecutor`; для сетевого/shell/git I/O
  отдельные протоколы, не расширять этот gate вслепую.
- Проверяемый `attempt_id` — серверный уникальный **fencing identity**,
  а статус `running` — разрешение на запуск нового tool action.
  **Это ещё не TTL lease:** продление, время истечения, worker
  generation и отзыв в распределённой системе остаются открытыми.
  Механизм только opt-in: обычный dispatcher без `attempt_fence`
  по-прежнему может выполнять инструменты. Требуется интеграция
  в production worker / trusted tool gateway и deny-by-default профиль.
- Сбой между реальным side effect и записью `SUCCEEDED` в отдельный
  Tool Ledger всё ещё оставляет `CLAIMED`, который требует
  операторского reconciliation. Это намеренный fail-closed исход,
  **не exactly-once**.

Offline acceptance tests: `tests/native_agent_e2e/test_native_contract_pipeline.py`
проверяют реальные server SQLite transitions, блокировку изменения
состояния до завершения ранее начатой записи и запрет записи после
восстановления. **Не закрывать #38/#33/#11 без полноценного server
lease и удалённого worker fencing.**

## Threat model / limitations

- The DB path and its parent are **trusted infrastructure**: an untrusted agent
  must not be allowed to rename, write, hardlink, remount or replace them.
  SQLite path-to-handle race safety relies on this invariant.
- A restarted model can issue a **new tool_call_id** for the same logical action;
  this ledger does not detect semantic duplicates with new IDs.
- Filesystem writes are atomic per file, not across multiple files or Git
  commits. A crash cannot prove whether a side effect was made without
  domain-specific reconciliation and a durable workflow journal.
- Shell/Git/HTTP remain disabled in the current dispatcher. Do not interpret
  this ledger as approval to run unsandboxed AI-generated commands.
- Store and protect the SQLite DB outside workspace; `CLAIMED` entries and
  recovery policy must be surfaced in the future native worker UI and journal.

## Reproduce

```bash
cd agent-management
python -m pytest tests/test_tool_ledger.py tests/test_native_tool_dispatch.py -q
```

Tests cover file writes across two independent dispatcher instances, SQLite
reopening, at-most-once across concurrent connections, interrupted `CLAIMED`
replay prevention, ledger down before I/O, failed finalize after I/O, private
DB permissions and redaction. All existing backend/CI checks must remain green.
