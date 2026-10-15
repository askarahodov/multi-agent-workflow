# Native tool dispatch: constrained filesystem stage

**Status:** first tested slice of [Issue #20](https://github.com/askarahodov/multi-agent-workflow/issues/20). Shell, Git and HTTP adapters remain **intentionally unsupported** until their separate security tests and sandbox/egress boundaries are implemented. This component **does not** close #20, #5, #9 or #11.

## Trust boundary

`NativeFilesystemDispatcher` is constructed by the **trusted orchestration control plane** with one `ScopedFilesystemExecutor` rooted at a previously assigned task workspace, with control-plane-owned permissions. Model output is limited to an assembled `tool_call` record:

```json
{"type":"tool_call","id":"call-1","name":"read_file","arguments":{"path":"src/main.py"}}
```

Only `read_file(path: string)` and `write_file(path: string, content: string)` exist in `tools_schema()`. Paths, content, call IDs and function names are untrusted. Both methods go through the Linux `O_NOFOLLOW`-based workspace boundary and `ToolPolicyEngine.enforce` before file I/O. Unsupported names are rejected, never dynamically imported. No shell, subprocess, HTTP or Git is reachable from this dispatcher.

The result has `to_provider_message()` for the next model turn, with `role=tool`, matching `tool_call_id`, and a stable error code on failure. Denied operations never include exception messages, filesystem paths, content, OS errors or stack traces in the provider-visible response. The fixed-size redacted `audit_snapshot()` excludes request arguments and file content.

## Replay and limitations

- Call IDs are claimed atomically inside one dispatcher instance before execution. Repeated identical IDs are denied even if arguments differ or the original operation failed. This **does not** guarantee exactly-once behavior across service restart, parallel workers, process crash or a regenerated ID. A persistent execution ledger and idempotency contract belong to the native Agent Loop.
- The current implementation is filesystem **only**, not a security sandbox. The trusted workspace mount must not expose host directories, secrets or Docker socket; Linux filesystem rights, containers and orchestration process isolation remain separate obligations.
- File contents are untrusted task data, not agent instructions. The future agent loop must prevent tool outputs from escalating privileges or modifying system instructions.
- The underlying scoped filesystem boundary intentionally fails closed on Windows pending a native handle-based solution.
- This module does not call the LLM, close tasks, mutate Contract Gate results or emit durable events. Only the orchestration service can change task completion status.

## Tests

From `agent-management/`:

```bash
python -m pytest tests/test_scoped_fs.py tests/test_native_tool_dispatch.py -q
```

The dispatch tests exercise valid read/write, JSON tool result shape, invalid event IDs/schema, unknown tool hard-deny, no shell or subprocess invocation, path/policy denial, symlinks, non-leaking audit, double-call replay and concurrent same-ID calls.

**Next:** separate locked-down Git/shell/HTTP adapters with denial before side effects, route only approved allowlisted schemas, persist replay/audit evidence, then bounded LLM→tool→LLM execution and Contract Gate integration.

## Отдельная стадия: доверенные read-only процессные операции

В рамках #20 добавлен `TrustedReadOnlyProcessTools` для фиксированных
операций `git_status` и `shell_list` с абсолютными путями исполняемых
файлов, строго фиксированными argv, `shell=False`, очищенным окружением,
таймаутами и размером ответа. Проверка `ToolPolicyEngine.enforce`
выполняется до запуска процесса. Команды не формируются из текста модели.

**Важно:** этот адаптер **не подключён** к перечню инструментов LLM.
До допуска shell/Git/HTTP в работающий Agent Loop необходимы sandbox
изоляция, проверка команд записи и ограниченный HTTPS egress с DNS/IP
pinning, блокировкой redirect и localhost/metadata. Статус #20 остаётся
открытым. Положительный тест локального `git status` не доказывает
безопасность git-write, команд shell или HTTP.

## Доверенный HTTPS GET: отдельная стадия #20

В `TrustedHttpsGet` реализован ограниченный GET для заранее доверенного
списка хостов. До DNS производится `ToolPolicyEngine.enforce(network, url)`.
Разрешены только HTTPS:443, точное имя из `allowed_hosts`, без userinfo,
fragment, query и управляющих символов. Результаты DNS проверяются **все**:
loopback, частные, link-local/metadata и не-глобальные адреса запрещены.
TCP-соединение использует проверенный цифровой IP (DNS pinning), но
TLS/SNI и проверка сертификата используют исходное доверенное имя.

Запрещены redirects, MIME вне text/plain и application/json, сжатые
ответы и объём более заданного лимита. Ответы ошибок редактируются.
Исполнение не наследует системный HTTP proxy. Внешние API не вызываются
в offline CI.

**Не является завершённой приёмкой #20**: подключение инструментов к
LLM-маршрутизатору, policy/ledger и контроль отмены, runtime sandbox
и политика безопасных изменяющих Git/shell-операций ещё требуются.

## Условное включение доверенных инструментов

При доверенной передаче `process_tools` и/или `https_get` dispatcher
добавляет в `available_tools_schema()` только `git_status`,
`shell_list` и/или `http_get(url)`. Без этих адаптеров схема остаётся
файловой, а неподдерживаемые вызовы запрещены.

Чтобы активировать расширенные операции, обязательны:
- SQLite ledger с scope прерванной попытки **за пределами workspace**
- `TrustedSqliteAttemptFence` с совпадающим scope
- для процессных операций — совпадение доверенного корня workspace

Каждый вызов сначала получает одноразовую запись в ledger, затем
проверяет fencing и собственную политику инструмента. Дублирующийся
call ID после рестарта не исполняется повторно. Отказ и итог
сохраняются без аргументов и содержания ответа.

Это **ограниченный opt-in режим**, не общий shell. Команды записи Git,
произвольные аргументы shell и небезопасный HTTP запрещены. В удалённом
gateway/worker новые операции не включены автоматически: потребуется
отдельная проверка доверенной проводки в продуктовой среде.
