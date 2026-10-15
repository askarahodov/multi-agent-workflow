# Защищённый SQLite orchestration: точка входа (#54)

`python -m orchestration_server.secure_sqlite_serve` — отдельная
**явная** точка входа для TLS оркестратора с обязательными leases
и API-аутентификацией. Обычный dev `orchestration_server.main` не меняется.

Обязательные параметры: `MAW_SECURE_ORCH_ENABLED=1`,
`ORCH_ATTEMPT_LEASE_ENABLED=1`, `AUTH_ENABLED=true`,
абсолютный `ORCH_DATABASE_URL=sqlite+aiosqlite:////.../orchestration.db`,
`ORCH_TLS_CERT_FILE`, `ORCH_TLS_KEY_FILE`,
`MAW_ORCH_API_KEY_FILE` (уникальный ASCII файл 0600, владелец процесса).
Не указывать `WRITE_API_KEYS`, `READ_API_KEYS` или
`ADMIN_API_KEYS` через переменные окружения. Entry point читает приватный
ключ и присваивает `WRITE_API_KEYS` **до** импорта middleware.
Это обходит проблему shared auth, которая считывает окружение при импорте,
и не включает dev-режим с неограниченными ролями.

Слушает TLS на порту 8443, без доверия к proxy headers.
Перед запуском проверяет обязательные пути, владение API key,
отсутствие PostgreSQL/относительной SQLite, включение leases и auth.
Не печатает секреты или filesystem paths при ошибках.

**Ограничения / НЕ готово к эксплуатации:** API key нужен отдельно от
gateway key, provider key и private TLS key. Нужен отдельный
co-located Compose с корректным UID/ACL для каталога SQLite, чтобы
gateway мог вести атомарный fence без несогласованных WAL/sidecars.
Оператор обязан обеспечить приватный каталог, корректную цепочку TLS,
проверку недоступности сервиса снаружи и ротацию ключей. Данные в
`WRITE_API_KEYS` внутри процесса не должны попадать в журналы.
Текущий этап не запускается автоматически в Compose и не выполняет
платных LLM операций.

До закрытия #54 необходимы тесты настоящего TLS HTTP claim/renew,
shared-SQLite fencing, downtime/restart и quarantine CLAIMED.
