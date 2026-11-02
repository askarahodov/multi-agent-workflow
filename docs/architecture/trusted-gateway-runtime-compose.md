# TLS Gateway runtime: отдельный opt-in Compose (#54)

**Назначение:** запускать уже реализованный TLS-only
`agent_management.trusted_gateway_serve` в отдельном непривилегированном
контейнере рядом с **уже защищённым SQLite control plane**. Это не установка
оркестратора и не готовый end-to-end кластер.

## Безопасные границы

`deploy/compose/secure/compose.trusted-gateway-runtime.yml` не участвует в обычном
`docker compose up`, требует явного профиля
`trusted-gateway-runtime`. Gateway работает как UID `10002`;
все Linux host paths должны быть подготовлены оператором до запуска
(в Compose стоит `create_host_path: false`). Ключи/TLS-файлы
read-only; код внутри контейнера и root filesystem также read-only.

Важно: **вместо отдельного монтирования SQLite-файла монтируется весь
закрытый каталог** (`MAW_GATEWAY_CONTROL_HOST_DIR`), чтобы WAL,
rollback journal и блокировки были на том же локальном диске и
разделялись с orchestration-server. Каталог ledger тоже отдельный и
доступен gateway для записи. Каталог workspace — отдельный, без секретов
и базы; правила `ScopedFilesystemExecutor` разрешают `src/**`
только читать, `out/**` только записывать.

Сеть `trusted-tools` — `internal: true`. Входящих host ports нет;
доступ возможен только из других явно подключённых доверенных
контейнеров. TLS-сертификат должен соответствовать DNS, который
использует клиент, с проверенной цепочкой доверия. Не включать
неаутентифицированного dev orchestrator и не подключать обычный
публичный frontend к этой сети.

## Команда проверки синтаксиса (Linux / Windows CMD)

```cmd
docker compose -f deploy/compose/secure/compose.trusted-gateway-runtime.yml --profile trusted-gateway-runtime config --quiet
```

Эта команда **не создаёт** секреты, SQLite или TLS. Для реального
запуска оператор должен независимо обеспечить защищённый control plane
с `ORCH_ATTEMPT_LEASE_ENABLED=1`, реальной приватной локальной SQLite,
TLS и API auth, а также переменные host mounts:

- `MAW_GATEWAY_CONTROL_HOST_DIR`: закрытый каталог с orchestration.db;
- `MAW_GATEWAY_LEDGER_HOST_DIR`: отдельный каталог private ledger;
- `MAW_GATEWAY_WORKSPACE_HOST_DIR`: каталог с `src` и `out`;
- `MAW_GATEWAY_KEY_HOST_FILE`: private 0600 ключ gateway;
- `MAW_GATEWAY_TLS_CERT_HOST_FILE`: TLS сертификат;
- `MAW_GATEWAY_TLS_KEY_HOST_FILE`: private 0600 TLS ключ.

На Windows Docker Desktop необходимо отдельно подтвердить корректное
отображение владельца UID 10002 и ACL: несовпадение должно приводить
к отказу, а не к chmod 777.

**Запуск сервиса способен писать в workspace и ledger.** Выполнять
его допустимо только в одобренной изоляции и после обеспечения всех
путей/прав; стандартная конфигурация ничего не запускает. Никакой
LLM/provider в этом Compose нет.

## Не закрыто

Пока нет защищённого orchestration-server в этом же Compose,
подключённого leased worker и проверок настоящего HTTP claim/renew,
TLS dispatch, race, crash/restart и quarantine `CLAIMED`. До этих
проверок нельзя считать #54, #33 и #38 готовыми к эксплуатации.
