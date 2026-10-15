# Совместный SQLite control plane и TLS gateway — opt-in (#54)

Файл `compose.trusted-sqlite-control.yml` содержит **два** доверенных
сервиса: `secure-orchestration` (TLS :8443) и `trusted-gateway` (TLS :9443).
Оба видят **один и тот же локальный каталог** SQLite
`MAW_CONTROL_HOST_DIR` по пути `/srv/maw/control`. Общая SQLite и WAL
не должны находиться на NFS, SMB или двух отдельных томах: это ломает
гарантии локальных блокировок и fencing.

## Границы

Оба сервиса намеренно используют доверенный UID `10002`: SQLite sidecars
должны создаваться/блокироваться обоими процессами. **Недоверенный worker**
имеет другой UID `10001` и не получает mount control/ledger/workspace
или секретов. Между двумя доверенными сервисами нет изоляции одного UID:
это ограничение модели доверия, а не гарантия контейнерного sandbox.

Все host paths должны быть созданы оператором вне репозитория;
Compose запрещает автоматическое создание отсутствующих путей.
Private keys 0600 принадлежат UID 10002; каталоги SQLite, ledger,
workspace защищены и принадлежат UID 10002. Сертификаты должны
соответствовать DNS именам `secure-orchestration` и
`trusted-gateway`, цепочку доверия клиента необходимо проверить.
API-ключ оркестратора, TLS private keys и gateway key — разные секреты.
В образах и YAML секретных значений нет.

Оба сервиса не имеют опубликованных host ports, работают через
`internal: true` сеть, без capabilities и с read-only rootfs.
Worker/provider **не входят** в этот Compose. Обычный девелоперский
`docker-compose.yml` с незащищённой авторизацией сюда не добавлять.

## Проверка модели (Linux / Windows CMD)

```cmd
docker compose -f compose.trusted-sqlite-control.yml --profile trusted-sqlite-control config --quiet
```

Команда не поднимает контейнеры. После отдельного provisioning
приватных каталогов и TLS оператор может явно выполнить
`docker compose -f compose.trusted-sqlite-control.yml --profile trusted-sqlite-control up --build`.
Это **реальный** запуск двух процессов, не безопасный offline preflight:
не использовать без одобрения control-plane и сертификатов.

## Оставшиеся блокеры приёмки

Нужны самостоятельные интеграционные проверки реального старта двух
контейнеров с общим SQLite, HTTPS claim/renew, атомарного fence,
потери связи, перезапуска и карантина неоднозначных `CLAIMED`.
Также нужен отдельный opt-in paid worker профиль с доступом только к
двум TLS endpoint и установленными лимитами. До завершения этих шагов
#54/#33/#38 остаются открытыми.
