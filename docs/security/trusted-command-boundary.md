# Trusted command boundary — ограниченный этап #20

Добавлен независимый `TrustedCommandExecutor` для запуска **только точных, заранее разрешённых argv**. Это ещё **не** полноценный shell/Git/HTTP tool dispatcher и не основание для закрытия #20.

## Границы доверия

- Путь к бинарному файлу, рабочая директория, разрешённые argv и policy устанавливаются доверенным control plane, не LLM.
- Только прямой запуск argv через `subprocess.run(..., shell=False)`. Не используются `sh -c`, интерпретация командной строки, PATH-поиск исполняемого файла или наследуемое окружение.
- `ToolPolicyEngine.enforce` вызывается до старта subprocess, причём проверяет имя **и все аргументы**, а не просто имя бинарного файла.
- Для Git поддерживаются только запросы `status --porcelain=v1 --untracked-files=no` и `rev-parse --is-inside-work-tree`. Отклоняются настройки через `-c`, внешние diff и любые неразрешённые операции.
- Запрещены имена внешних AI CLI (`hermes`, `codex`, `claude` и другие).
- Ограничены длительность выполнения и размер *принятого* ответа; stderr не возвращается модели. Ограничение размера проверяется после сбора вывода, поэтому отдельная жёсткая memory/CPU sandbox-политика ещё необходима.
- Работает только на POSIX, в доверенном контейнере с отключёнными привилегиями. Запуск в workspace с доступом к секретам, Docker socket или host mounts не разрешён.

## Что остаётся до закрытия #20

Не подключать библиотеки напрямую к model-driven вызовам. Нужны процессная sandbox-изоляция, проверка безопасности Git-репозиториев и runtime-тесты гонок workspace; durable deny/result journal и корреляция с попыткой.\n\n### Отдельная HTTPS-граница\n\n`TrustedHTTPSExecutor` реализует только GET по точным control-plane allowlist URL и публичным IP: разрешает целевой адрес после DNS и закрепляет его для TLS-подключения без второго DNS lookup; проверяет исходный hostname через TLS SNI, запрещает внутренние/metadata адреса и редиректы, ограничивает длительность и размер ответа. Модель пока не может вызвать этот компонент. Он синхронный и должен исполняться вне event loop в изолированном worker. Нужны дополнительные тесты реальной TLS/сетевой изоляции и защитный egress firewall.

Тесты: `python -m pytest agent-management/tests/test_trusted_commands.py agent-management/tests/test_trusted_https.py -q` из корня репозитория при установленном пакете.

См. также [ограниченный файловый dispatcher](native-tool-dispatch.md).


## HTTPS tool through native agent loop (Issue #20)

The native filesystem dispatcher advertises http_get only when a trusted
control-plane caller injects pinned_https=TrustedHTTPSExecutor(...) together
with a matching durable SqliteToolLedger and TrustedSqliteAttemptFence.
The default schema remains filesystem-only. Legacy https_get without a total
deadline stays disabled.

HTTP is GET-only: exact URL/IP allowlist, TLS hostname validation,
all DNS answers approved, no redirects, bounded response, strict network policy.
No arbitrary headers, credentials, verbs, query strings, local or metadata IP
destinations may be supplied by the model.

Model-facing operations call get_bounded, which runs HTTPS network I/O
in an isolated Python child, with no application secrets or ambient proxy,
an in-process signal watchdog and a parent-process kill on deadline (including DNS).
The durable attempt fence covers the request, and the SQLite tool ledger
rejects duplicate correlation IDs. The HTTP tool requires a trusted sandbox
without host credential volumes or Docker sockets.
