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
