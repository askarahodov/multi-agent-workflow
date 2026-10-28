# Native Worker: изолированный образ и безопасный Compose preflight (#54)

Этот этап **не запускает OpenRouter** и **не выполняет задачи**. Он
доказывает, что отдельный opt-in образ можно собрать и локально проверить
без Hermes, доступа к Docker socket, SQLite оркестратора и агентского workspace.

## Linux / Windows Docker Desktop (CMD)

Подготовить приватный файл ключа оркестрации за пределами репозитория.
Для Linux bind-mounted файл должен принадлежать контейнерному UID `10001`
и иметь mode `0600`; не ослаблять права до `0644`.
На Windows Docker Desktop права и UID bind mount зависят от backend;
`preflight` обязан отказать, если безопасное владение файла не обеспечено.

Настроить переменные `MAW_NATIVE_WORKER_API_KEY_HOST_FILE` (абсолютный путь
к файлу), `MAW_NATIVE_WORKER_SERVER_URL` (HTTPS) и
`MAW_NATIVE_WORKER_AGENT_ID` (server-owned ID). После этого:

```sh
docker compose -f compose.native-worker-preflight.yml --profile native-worker-preflight config --quiet
docker compose -f compose.native-worker-preflight.yml --profile native-worker-preflight build
docker compose -f compose.native-worker-preflight.yml --profile native-worker-preflight run --rm native-worker-preflight
```

Команда возвращает `0` только при локально валидной конфигурации; без
файла/прав она должна завершаться с ошибкой. Сеть для сервиса отключена
(`network_mode: none`), filesystem readonly, capabilities dropped,
`no-new-privileges`, UID `10001`; никакие приватные ключи не
копируются в образ. Нет `restart: always`, нет background worker.

**Не** используйте `-f docker-compose.yml` для запуска этого preflight:
отдельный файл преднамеренно независим, чтобы не запускать небезопасный
dev оркестратор со значением `AUTH_ENABLED=false`.

## Следующие блокирующие критерии #54

- Защищённая orchestration конфигурация: API auth, explicit lease
  enabled и SQL state, совместный с gateway.
- Отдельный co-located TLS gateway c закрытой сетью и приватными SQLite,
  journal, workspace, certificate/key mounts. Worker не должен видеть их.
- Отдельный строго операторский `run` профиль с budget approval,
  server/gateway trust roots и rate limits. Этот preflight файл не
  содержит `run` и не открывает сеть.
- Доказать cross-process API claim/renew, tool-fencing, Contract Gate,
  restart и quarantine при неоднозначном CLAIMED.
- Пройти Linux Compose E2E, затем документировать вариант Windows CMD.

До этого SDLC autonomy, live OpenRouter acceptance и production-ready
не подтверждены. См. `docs/qa/NATIVE-WORKER-DEPLOYMENT-ACCEPTANCE.md`.


## Полная проверка запускаемого runtime worker (часть #11)

Команда `python -m orchestration_server.native_worker_cli preflight` в `compose.native-worker-runtime.yml` проверяет **все** параметры доверенного запуска: orchestration API и lease, отдельные приватные ключи orchestration/gateway/provider, совпадение `agent_id`, допустимый HTTPS gateway, trust root, фиксированную модель OpenRouter, prompt и бюджеты исполнения. Все три секрета должны различаться. Проверка выполняется локально и не создаёт сеть, LLM completion или tool call. При отсутствующей provider-конфигурации статус 2 (fail closed). Это не заменяет server/gateway handshake, реальную работу provider или SDLC приёмку.

Изолированный образ `compose.native-worker-preflight.yml` и его узкая проверка одного API-ключа описаны выше и остаются отдельным образом. Для полного preflight runtime используйте соответствующий runtime overlay и реальные приватные настройки, без вызова команды `run`.
