# Доверенный HTTPS-шлюз файловых инструментов (stage #33/#38)

## Цель и чёткие границы

**Удалённый** Native HTTP worker больше не обязан получать прямой доступ к
файловой системе оркестратора или его приватной SQLite. Вместо этого доверенный
`leased_runner` может отправлять запросы на **отдельную службу**, размещённую
рядом с оркестратором. Служба независимо проверяет разрешения на каждую
операцию с файлом, сохраняя журнал `CLAIMED/SUCCEEDED/DENIED`. По умолчанию
служба **НЕ запускается** в составе оркестратора и не активирует платные LLM.

Реализация: `agent_management.trusted_fs_gateway`. Разрешены только
`read_file` и `write_file` — никаких команд shell, Git, сетевых запросов,
исполнения кода и произвольных файлов вне workspace.

## Доверенный контур

Сервис должен выполняться под отдельной контролируемой учётной записью в
**той же защищённой локальной файловой среде, что и orchestration SQLite**.
Его постоянные пути и права назначает оператор, а не модель или worker:

- `MAW_GATEWAY_WORKSPACE_ROOT` — выделенная папка workspace, в которой
  `src/**` доступна только для чтения, `out/**` — только для записи;
- `MAW_GATEWAY_ORCHESTRATION_SQLITE` — абсолютный путь к **реальной**
  SQLite оркестратора с приватными правами (0600), вне workspace;
- `MAW_GATEWAY_LEDGER_SQLITE` — отдельная приватная SQLite для
  `SqliteToolLedger`, тоже вне workspace;
- `MAW_GATEWAY_KEY_FILE` — абсолютный путь к приватному (0600) файлу
  с уникальным ключом шлюза длиной 32–128 символов, вне workspace.

Файл ключа не помещать в репозиторий, workspace агента, .env с доступом
к модели или отчёт GitHub. Шлюз создаётся **только** явным вызовом factory:

```sh
uvicorn agent_management.trusted_fs_gateway:trusted_gateway_from_env \
  --factory --host 127.0.0.1 --port 9443 \
  --ssl-certfile /secure/gateway.crt \
  --ssl-keyfile /secure/gateway.key
```

Команда иллюстрирует запуск; TLS-ключи должны предоставляться оператором.
Для доступа с другой машины требуется отдельно настроить защищённую сеть,
сертификат и взаимно проверяемую идентичность клиента. Не публиковать шлюз
в Internet и не переиспользовать API-key самого оркестратора в качестве
`X-Gateway-Key`. Входящий запрос по HTTP отвергается, перенаправление на
HTTPS не выполняется.

## Контракт

`POST /v1/filesystem/dispatch` с заголовком `X-Gateway-Key: ...` и
JSON body от **доверенного client adapter** (не от LLM):

```json
{
  "run_id": "SERVER_RUN_ID",
  "task_id": "SERVER_TASK_ID",
  "attempt_id": "SERVER_ATTEMPT_ID",
  "agent_id": "SERVER_AGENT_ID",
  "lease_token": "SERVER_ISSUED_OPAQUE_TOKEN",
  "event": {
    "type": "tool_call",
    "id": "tool-call-001",
    "name": "write_file",
    "arguments": {"path": "out/report.txt", "content": "Example"}
  }
}
```

Идентификаторы и token клиент берёт исключительно из подтверждённого
контракта `claim` и `TrustedAttemptLease`. Модель выбирает **только**
поля `event`, которые проходят строгую проверку имён, разрешённых путей,
типов и размеров. Нельзя принимать от LLM root, ledger path, gateway key
или server-issued идентичности. Секреты никогда не включать в prompt.

Проверка полномочий — двухступенчатая: секрет `X-Gateway-Key` для вызова
сервиса и действующий server-issued `lease_token` для конкретного
`run/task/attempt/agent`. Неправильный токен, отозванная/просроченная
попытка или mismatch поколения блокируют новый I/O. Ответы ошибок
обезличены; для успешного чтения возвращается текст файла в `content`.

Внутри шлюза используется **существующий** `ScopedFilesystemExecutor`
с POSIX descriptor-relative `O_NOFOLLOW`, `NativeFilesystemDispatcher`,
приватный `SqliteToolLedger` и `TrustedSqliteAttemptFence`. Последний
удерживает `BEGIN IMMEDIATE` на orchestration SQLite от проверки до
конца файловой операции. Отзыв Lease не может **закоммититься**, пока
ранее допущенная операция не завершилась; после отзыва новые записи
не допускаются. Повторный `call_id` не выполняется и не перезаписывает
файл, даже после перезапуска gateway.

## Важные ограничения (P0 всё ещё открыт)

1. **Доступен отдельный opt-in доверенный клиентский адаптер**:
   `agent_management.trusted_fs_client.TrustedLeasedGatewayRunner`,
   который можно передать как `NativeHttpWorker(leased_runner=runner,
   require_lease=True)`. Этот адаптер соединяет настоящий HTTP claim/lease,
   ограниченный `run_agent_loop` и `TrustedRemoteFilesystemDispatcher`;
   модель управляет только `tool_call` и не выбирает run/agent/lease,
   URL или ключ. **Автоматический production deployment не включён.**
   Доверенный оператор обязан внедрить runner с изоляцией workspace.
2. **SQLite только на одном локальном томе**. PostgreSQL, multi-host
   orchestration DB, NFS и общая работа через удалённые диски запрещены
   до отдельной реализации распределённого fencing.
3. Шлюз обеспечивает только чтение/запись текстовых файлов.
   **Shell/Git/HTTP и уже отправленные внешние запросы не контролируются**.
   Незащищённый runner с прямым доступом к workspace может обойти gateway:
   нужна OS/container-изоляция, при которой только шлюз может выполнять
   изменяющие операции.
4. Если шлюз падает после записи, но до `ToolLedger SUCCEEDED`,
   `CLAIMED` остаётся неоднозначным; никаких автоматических повторов.
   Это **не** общая гарантия exactly-once для внешних side effects.
5. Ограниченные DB writer locks могут блокировать серверную запись на
   время файлового I/O; тайм-аут приводит к fail-closed. Ограничения прав
   и timeout защищают от зависаний, но не заменяют мониторинг.
6. Содержимое `read_file` и `write_file` является данными задач.
   Эти данные по контракту доступны доверенному client adapter, но их
   нельзя журналировать как debug HTTP body. Отдельный TLS и правила
   доступа к сети обязательны.

## Trusted runner/client adapter (новая стадия)

Создать `TrustedLeasedGatewayRunner` можно только в доверенной конфигурации
удалённого worker, передав отдельные `gateway_url` (строго HTTPS без path,
userinfo, query или redirect), выделенный `gateway_key`, server-issued
`agent_id`, готовый provider и начальный набор сообщений. Worker вызывает
его после claim как `leased_runner(task, attempt_id, TrustedAttemptLease)`.
Адаптер выбирает run_id/task_id исключительно из заверенной сервером задачи,
а токен — из полученного от сервера Lease; **не помещает токен или ключ шлюза
в сообщения модели**.

`NativeHttpWorker` продлевает Lease во время выполнения. Каждая отдельная
файловая операция проверяется заново на стороне шлюза, под его SQLite
`BEGIN IMMEDIATE` барьером. Клиент не делает retry в случае неясного
исхода сетевой операции или `DUPLICATE_CALL`: даже если файл уже записан,
нужно сохранять `CLAIMED` для разбирательства, а не давать модели новое
право на ту же операцию.

Агентный цикл теперь принимает **только два доверенных типа** диспетчера:
старый синхронный `NativeFilesystemDispatcher` или отдельный асинхронный
`TrustedRemoteFilesystemDispatcher`. Без зарегистрированного server Lease
и ключа шлюза никакие удалённые операции не выполняются. Remote dispatcher
никогда не следует перенаправлениям и не использует переменные окружения
для HTTP-proxy.

Важно: провайдер остаётся объектом, который **оператор должен явно
предоставить**. Тесты используют scripted fake stream — платные модели и
реальная внешняя сеть не запускаются. Поддержка runner не отменяет требования
OS/container isolation: для недоверенного процесса должны быть закрыты
прямые права на рабочую файловую систему, сервисную SQLite и
privileged gateway key. Этот блок остаётся на этапе integration-ready,
не на этапе production accepted.

## Офлайн-проверки

`tests/native_agent_e2e/test_native_contract_pipeline.py`:
валидный защищённый HTTPS write, персистентный duplicate-call denial,
запрет выхода из workspace, неправильный Lease, отзыв после write,
межпоточная гонка с in-flight I/O, неправильный API-key, HTTP и
невалидный/слишком большой запрос. Без реальных LLM и платных API.

Следующий dependency order: независимый review и CI #45 → #46 → #47 →
#48 → #49 → #50 → #51 → данный gateway PR; затем production wired
`leased_runner` adapter, OS isolation и PostgreSQL fencing.
До E2E на отдельном worker host не закрывать #33/#38/#11.
