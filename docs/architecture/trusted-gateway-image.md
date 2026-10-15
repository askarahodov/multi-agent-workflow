# Trusted gateway: изолированный образ, стадия #54

Образ `agent-management/Dockerfile.trusted-gateway` содержит только серверный
пакет и `maw-shared`. В нём нет ключей, сертификатов, mount SQLite и
workspace. По умолчанию он вызывает **только**:

```sh
python -m agent_management.trusted_gateway_cli preflight
```

Для сборки на Linux или Windows Docker Desktop CMD:

```sh
docker build -f agent-management/Dockerfile.trusted-gateway -t maw-gateway:local .
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges maw-gateway:local
```

Без явных параметров команда возвращает код 2; никакой шлюз не запущен.
Preflight проверяет наличие приватных путей, базовой структуры workspace
(`src/` и `out/`), файлов БД/ключа и TLS-сертификата и разделение путей.
Она **не открывает БД, не создаёт ledger и не проверяет TLS криптографически**.
Сам `trusted_gateway_from_env` проводит дополнительные проверки в момент
настоящего запуска, включая protected ancestors.

Дальнейшая работа #54: отдельный opt-in co-located TLS Compose, Linux
права томов и реальное разделение непривилегированного worker и gateway,
а также end-to-end restart/fencing. Ни Python-тесты, ни сборка образа
не являются приёмкой production. Не добавлять привилегии, Docker socket
или `AUTH_ENABLED=false` в защищённый контур.

## Отдельная Compose-проверка доступа к томам

`compose.trusted-gateway-preflight.yml` добавляет **только** профиль
`trusted-gateway-preflight`, без сети, открытых портов, запусков HTTP
или записи в SQLite. Для syntax-only проверки (Linux, Windows CMD):

```sh
docker compose -f compose.trusted-gateway-preflight.yml --profile trusted-gateway-preflight config --quiet
```

Оператор обязан **до запуска** подготовить шесть host mounts:
`MAW_GATEWAY_WORKSPACE_HOST_DIR` (с каталогами `src` и `out`),
`MAW_GATEWAY_ORCHESTRATION_DB_HOST_FILE`,
`MAW_GATEWAY_LEDGER_HOST_DIR`, `MAW_GATEWAY_KEY_HOST_FILE`,
`MAW_GATEWAY_TLS_CERT_HOST_FILE` и `MAW_GATEWAY_TLS_KEY_HOST_FILE`.
Все значения по умолчанию намеренно указывают на отсутствующие файлы.
Контейнер запускается под UID 10002; секретные файлы должны быть
`0600` и принадлежать этому UID с точки зрения контейнера. На Windows
Docker Desktop различия ACL/UID могут вызвать ожидаемый отказ.

После безопасного локального provisioning:

```sh
docker compose -f compose.trusted-gateway-preflight.yml --profile trusted-gateway-preflight run --rm trusted-gateway-preflight
```

В overlay все mounts read-only, включая workspace и ledger, поэтому это
**не конфигурация выполняющего операции gateway**. Отсутствуют и TLS
listener, и control-plane server. **Не объединять** overlay с обычным
`docker-compose.yml`: его dev auth выключен. Следующий этап требует
совместно расположенный сервер и gateway с независимыми UID, контролируемыми
правами на SQLite journal/sidecars, TLS проверкой и реальными race/restart E2E.
