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
docker compose -f deploy/compose/secure/compose.native-worker-preflight.yml --profile native-worker-preflight config --quiet
docker compose -f deploy/compose/secure/compose.native-worker-preflight.yml --profile native-worker-preflight build
docker compose -f deploy/compose/secure/compose.native-worker-preflight.yml --profile native-worker-preflight run --rm native-worker-preflight
```

Команда возвращает `0` только при локально валидной конфигурации; без
файла/прав она должна завершаться с ошибкой. Сеть для сервиса отключена
(`network_mode: none`), filesystem readonly, capabilities dropped,
`no-new-privileges`, UID `10001`; никакие приватные ключи не
копируются в образ. Нет `restart: always`, нет background worker.

**Не** используйте `-f deploy/compose/dev/docker-compose.yml` для запуска этого preflight:
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

Команда `python -m orchestration_server.native_worker_cli preflight` в `deploy/compose/secure/compose.native-worker-runtime.yml` проверяет **все** параметры доверенного запуска: orchestration API и lease, отдельные приватные ключи orchestration/gateway/provider, совпадение `agent_id`, допустимый HTTPS gateway, trust root, фиксированную модель OpenRouter, prompt и бюджеты исполнения. Все три секрета должны различаться. Проверка выполняется локально и не создаёт сеть, LLM completion или tool call. При отсутствующей provider-конфигурации статус 2 (fail closed). Это не заменяет server/gateway handshake, реальную работу provider или SDLC приёмку.

Изолированный образ `deploy/compose/secure/compose.native-worker-preflight.yml` и его узкая проверка одного API-ключа описаны выше и остаются отдельным образом. Для полного preflight runtime используйте соответствующий runtime overlay и реальные приватные настройки, без вызова команды `run`.


## Live OpenRouter: отдельно разрешённый исходящий маршрут (#11)

По умолчанию `deploy/compose/secure/compose.native-worker-runtime.yml` подключён только к
`trusted-control: internal: true` и **не имеет доступа к OpenRouter**.
Для санкционированного live прогона оператор добавляет
`deploy/compose/secure/compose.native-openrouter-egress.yml` к защищённому control + runtime
worker (+ при необходимости autonomous dispatch) **после** настройки
приватных ключей, бюджета и выбранного провайдера:

```bash
docker compose -f deploy/compose/secure/compose.trusted-sqlite-control.yml -f deploy/compose/secure/compose.native-worker-runtime.yml -f deploy/compose/secure/compose.native-openrouter-egress.yml --profile trusted-sqlite-control --profile native-worker-runtime config --quiet
```

Overlay добавляет только `native-worker` в отдельную Docker bridge сеть
`native-provider-egress` (не `internal`), одновременно сохраняя доступ к
TLS `secure-orchestration` и `trusted-gateway` по закрытой сети.
Не добавляйте `secure-orchestration`, `trusted-gateway` или QA к egress.
Overlay не запускает paid API автоматически: команда worker по умолчанию
остаётся `preflight`, а `run`/`dispatch` требует отдельного действия.

**Граница защиты:** Docker bridge egress сам по себе не ограничивает исходящий
HTTPS только доменом OpenRouter. Для строгого deployment требуется внешний
операторский egress firewall/proxy с allowlist и аудитом; не публикуйте
worker на недоверенный интернет и не запускайте непроверенный код в QA.
Отдельная сеть решает сетевую недоступность provider, **но не является**
доказательством реального tool-call, Git commit и полной SDLC acceptance.


## Реальные Git artifacts: доверенный Compose overlay (#11)

Даже после подключения OpenRouter egress worker не сможет возвращать проверенные
Git commits, пока **обе** стороны выключены: `MAW_TRUSTED_GIT_ENABLED` у
worker и `MAW_GATEWAY_GIT_ENABLED` у gateway. Отдельный
`deploy/compose/secure/compose.native-trusted-git-runtime.yml` включает оба флага совместно и
монтирует исходный Git репозиторий и отдельный каталог attempt worktrees
**только в доверенный gateway**. Worker не получает прямого доступа ни к Git,
ни к orchestration SQLite, ни к ledger. Создание worktree, commit и проверка
Git artifact остаются операциями gateway, привязанными к lease.

Пример проверки итогового Compose без исполнения модели:

```bash
docker compose -f deploy/compose/secure/compose.trusted-sqlite-control.yml -f deploy/compose/secure/compose.native-worker-runtime.yml -f deploy/compose/secure/compose.native-trusted-git-runtime.yml -f deploy/compose/secure/compose.native-openrouter-egress.yml --profile trusted-sqlite-control --profile native-worker-runtime config --quiet
```

Перед реальным запуском оператор задаёт приватные каталоги
`MAW_GATEWAY_GIT_REPOSITORY_HOST_DIR` и
`MAW_GATEWAY_GIT_WORKTREE_HOST_DIR`, совместимые с UID 10002.
Bind mounts требуют уже существующих каталогов (`create_host_path: false`).
Рабочий репозиторий должен содержать инициализированный Git с доверенным
владением; отдельный каталог попыток должен быть пустым и приватным.
Нельзя подключать исходный репозиторий worker или контейнеру QA с модельным
ключом. Для independent QA используйте отдельный только-читаемый mount
того же source Git и отдельную собственную директорию checkout.

Overlay остаётся opt-in и не создаёт платных запросов. Полная приёмка требует
реального OpenRouter tool-call и readback Git artifact через подписанный QA
и release approval, чего статическая проверка YAML не доказывает.


## Hardening чтения приватных ключей runtime (#11)

`native_worker_bootstrap._private_key`, используемый native worker для orchestration, trusted gateway и OpenRouter ключей, запрещает теперь символьные ссылки не только в самом файле, но и в любом родительском компоненте абсолютного пути. После `open(O_NOFOLLOW)` дополнительно сверяется inode/device, `nlink == 1` и приватная маска разрешений текущего файлового дескриптора, чтобы не полагаться только на metadata до открытия. На Linux/POSIX это уменьшает риск подмены путей при использовании защищённых bind mounts. Это не атомарная гарантия безопасности произвольно изменяемого родительского каталога: оператор всё равно обязан защищать владение и права mount roots и исключить недоверенных локальных пользователей. Проверка не вызывает provider и не заменяет live acceptance.
