# Trusted Native Worker — эксплуатация и приёмка #33

## Что работает

- Исполняемый продуктовый процесс: `python -m orchestration_server.native_worker_cli run` (без Hermes). CLI отключён по умолчанию; требуется явная конфигурация из частных файлов.
- Воркер через аутентифицированный HTTPS API выбирает pending-задачу и вызывает серверный `claim` **до** LLM. Экземпляр попытки, токен lease, run/task/agent ID выдаёт control plane.
- Model, prompt, лимиты, TLS и ключи задаются только доверенной конфигурацией оператора. Tool request из LLM не определяет workspace или ledger.
- File tool выполняется отдельным TLS gateway в приватном co-located SQLite deployment с `ScopedFilesystemExecutor`, SQL fence и persistent `SqliteToolLedger`. Модель не имеет доступа к SQLite, workspace, Docker socket или хостовым ключам.
- Активный worker обновляет lease, проверяет его непосредственно перед submit, а при SIGTERM/ESTOP в `stop_event` прекращает активную попытку и не делает submit. Ошибка или потеря lease **не** вызывает автоматическое переисполнение.
- Native Agent Loop сохраняет ограниченный budget; `OrchestrationEngine` остаётся единственным владельцем Contract Gate и перехода в completed. Потоковые ошибки 429, некорректный JSON и denied tools не обходят проверку.

## Отдельное защищённое развёртывание

**Не объединять** с `deploy/compose/dev/docker-compose.yml`: основной dev-стек использует `AUTH_ENABLED=false` и привилегированный runtime-hardening. Для нового worker выделен `deploy/compose/secure/compose.native-worker-runtime.yml`, совместимый **только** с `deploy/compose/secure/compose.trusted-sqlite-control.yml`.

Подготовьте на хосте *вне репозитория* приватные директории для control SQLite, ledger и workspace, доверенные TLS сертификаты с DNS SAN `secure-orchestration` / `trusted-gateway`, и ключи сервиса. У рабочего контейнера UID 10001: секретные файлы worker — обычные файлы владельца UID 10001 с правами 0600; копии ключей, нужные сервисам UID 10002, должны сохранять разграничение владельца и прав.

Для worker установите абсолютные пути к копиям ключей через `MAW_WORKER_ORCH_API_KEY_HOST_FILE`, `MAW_WORKER_GATEWAY_KEY_HOST_FILE`, `MAW_WORKER_PROVIDER_KEY_HOST_FILE`, а к двум CA через `MAW_WORKER_ORCH_CA_HOST_FILE`, `MAW_WORKER_GATEWAY_CA_HOST_FILE`. Укажите `MAW_NATIVE_WORKER_AGENT_ID` и `MAW_OPENROUTER_MODEL`, задайте ограниченные `MAW_NATIVE_WORKER_MAX_POLLS`, `MAW_NATIVE_WORKER_POLL_SECONDS`, `MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS`.

Проверка синтаксиса Compose (Linux или Windows CMD):

```cmd
docker compose -f deploy/compose/secure/compose.trusted-sqlite-control.yml -f deploy/compose/secure/compose.native-worker-runtime.yml --profile native-worker-runtime config --quiet
```

При уже подготовленной закрытой инфраструктуре запуск **только локальной preflight-проверки, без запроса к модели**:

```cmd
docker compose -f deploy/compose/secure/compose.trusted-sqlite-control.yml -f deploy/compose/secure/compose.native-worker-runtime.yml --profile native-worker-runtime run --rm --no-deps native-worker python -m orchestration_server.native_worker_cli preflight
```

Для **явного** ограниченного запуска с реальным OpenRouter (возможны расходы) оператор меняет последнюю команду `preflight` на `run`. По умолчанию Compose содержит только `preflight`, `restart: no`, отдельную внутреннюю сеть без публичного порта и без монтирования хостового Docker socket/DB/workspace. Не запускать `run` до утверждения ключей, лимитов, рабочего пространства и политики восстановления.

## Безопасный restart / аварии

После потери lease, отказа gateway, 429, SIGTERM или краша worker не переиспользует тот же attempt и не повторяет side effects. При рестарте он заново опрашивает API; in_progress/blocked задачи не должны автоматически переисполняться. Durable tool ledger сохраняет `CLAIMED` / `SUCCEEDED` / `DENIED`; повторный call ID не исполняется. Неподтверждённые `CLAIMED` и заблокированные задачи разбираются control plane по отдельной процедуре reconciliation (#38), **без автоматического повтора**. Не сбрасывайте ESTOP без проверки.

## Воспроизводимые offline проверки

```sh
python -m pytest tests/native_agent_e2e -q
python -m pytest services/orchestration-server/tests/test_native_http_worker.py services/orchestration-server/tests/test_native_worker_process.py -q
```

В `tests/native_agent_e2e/test_trusted_worker_acceptance.py` проверяется полный supervisor→authenticated API→claim+lease→LLM-tool→fenced TLS gateway→Contract Gate с настоящими SQLite, а также падение после файла, перезапуск нового worker без второй записи и server recovery без ложного completed. `native-worker-image.yml` проверяет синтаксис защищённого Compose, сборку worker и fail-closed запуск отдельного процесса без ключей.

**Граница доказательства:** offline ASGI fixture и CI не являются подтверждением реального OpenRouter или production multi-host PostgreSQL barrier. Co-located SQLite, доверенная изоляция и отдельное явное разрешение на платный smoke остаются обязательными для реальной установки.
