# #11 — защищённый контур QA через Docker Compose (opt-in)

## Назначение

Обычный `docker-compose.yml` не подходит для независимого подписанного QA:
он использует `AUTH_ENABLED=false`. В нём нельзя хранить настоящие
OpenRouter/ADMIN/signing ключи, нельзя смешивать его с защищёнными профилями.

Дополнительный `compose.native-qa-runtime.yml` **не** меняет dev Compose.
Его запускают вместе с `compose.trusted-sqlite-control.yml`. Он добавляет:

- отдельный authenticated TLS `secure-quality-gates` (порт 9444 внутри
  `trusted-control`, без публикации наружу);
- отдельный `native-qa-controller` с **двумя разными** ADMIN-ключами, доверенным
  Git readback, snapshot checkout и signed handoff;
- QA ADMIN и signing ключи для `secure-orchestration`, которых ранее не было
  в защищённом control-plane (worker продолжает иметь только WRITE-доступ).

**По умолчанию QA-контроллер выполняет только preflight;** он не вызывает
модель, не исполняет тесты и не открывает сетевые API. QG TLS-сервис включается
только через профиль `native-qa-runtime`. В отличие от dev-профиля,
отсутствие файлов/неверные права вызывает FAIL_CLOSED.

## Изолированные права и ключи

На доверенном POSIX хосте требуются каталог с `orchestration.db` (UID 10002),
приватный Git репозиторий с исходными пользовательскими файлами и приватный
каталог временных QA checkout (UID 10003, mode 0700). Вся Git метаинформация
владельца checkout доступна только доверенному контроллеру.

Для отдельного signed-QA контура приготовьте по две копии **одинакового
значения HMAC-ключа**, но с разными владельцами/пути:

- `MAW_ORCH_QA_SIGNING_HOST_FILE` — UID 10002, mode 0600;
- `MAW_QG_SIGNING_KEY_HOST_FILE` — UID 10003, mode 0600.

Операторский ADMIN ключ Orchestration передаётся **одинаковым значением**,
но разными host files `MAW_ORCH_QA_ADMIN_HOST_FILE` (UID 10002) и
`MAW_QA_CONTROL_ADMIN_HOST_FILE` (UID 10003). Аналогично ADMIN QG:
`MAW_QG_ADMIN_KEY_HOST_FILE` и `MAW_QA_SERVICE_ADMIN_HOST_FILE`, обе
копии UID 10003. Каждый ключ строго отделён от worker WRITE, gateway key
и HMAC signing key. Значения ключей длиной 32–128 ASCII символов. Не писать
значения в YAML, в репозиторий, командную строку или журналы CI.

Необходимы независимые TLS cert/key для QG (`MAW_QG_TLS_CERT_HOST_FILE`,
`MAW_QG_TLS_KEY_HOST_FILE`) и доверенные CA для контроллера
(`MAW_QA_ORCH_CA_HOST_FILE`, `MAW_QA_SERVICE_CA_HOST_FILE`).
TLS сертификаты должны иметь SAN `secure-orchestration` и
`secure-quality-gates` соответственно.

Подготовьте приватные каталоги:
`MAW_QA_DATA_HOST_DIR`, `MAW_QA_EVIDENCE_HOST_DIR`,
`MAW_QA_ARTIFACT_HOST_DIR`, `MAW_QA_GIT_REPO_HOST_DIR` и
`MAW_QA_WORKTREE_HOST_DIR`. Для всех bind mount установлен
`create_host_path: false`; Compose не создаёт фальшивые пустые каталоги.

## Проверка Compose без запуска и платных запросов

Linux или Windows CMD:

```cmd
docker compose -f compose.trusted-sqlite-control.yml -f compose.native-qa-runtime.yml --profile trusted-sqlite-control --profile native-qa-runtime config --quiet
```

Для настоящего локального authenticated QA сначала подготовить закрытые
файлы с указанными владельцами и заполнить переменные, затем запустить
control, trusted gateway и QA сервисы. После их проверки выполнить:

```bash
docker compose -f compose.trusted-sqlite-control.yml -f compose.native-qa-runtime.yml --profile trusted-sqlite-control --profile native-qa-runtime up -d secure-orchestration trusted-gateway secure-quality-gates
docker compose -f compose.trusted-sqlite-control.yml -f compose.native-qa-runtime.yml --profile trusted-sqlite-control --profile native-qa-runtime run --rm native-qa-controller python -m quality_gates.native_qa_controller preflight
# Только после успешного preflight и явного решения запустить доверенные QA:
docker compose -f compose.trusted-sqlite-control.yml -f compose.native-qa-runtime.yml --profile trusted-sqlite-control --profile native-qa-runtime run --rm native-qa-controller python -m quality_gates.native_qa_controller run
```

Встроенный `MAW_QA_TEST_COMMAND_JSON` по умолчанию **отрицательный**
(`python -B -c "raise SystemExit(1)"`) и не может выдать ложный
положительный результат. Для реального QA оператор обязан явно задать
настоящую детерминированную тестовую команду до `run`.
При красном QA зависимая стадия не стартует.

## Важное ограничение защиты

Это **auth/TLS и trust-boundary wiring**, а не готовая production
изоляция непроверенного пользовательского кода. QG subprocess хоть и
запускается с очищенным environment, всё ещё работает в контейнере
QG с тем же Unix UID, что и сервер с signing secret. Вредоносный тестовый
код потенциально может читать доступные тому же UID файловые секреты.
**Не запускать тесты произвольного непроверенного репозитория в таком
профиле**, пока не будет независимого sandbox-контейнера без mounted
секретов, отдельного UID, сети и process namespace. Эта защита нужна
до полного закрытия P0 #11.

Также закрытая сеть `trusted-control: internal: true` не даёт worker
выходить в OpenRouter: реальное provider egress требует отдельного
проверенного маршрута и разрешённого бюджета; это не часть данного пакета.
Полноценная Web UI приёмка под AUTH_ENABLED=true требует отдельного
аутентифицированного reverse proxy/потока входа, который здесь не
симулируется. Сквозной offline E2E с реальными Git/HTTP/QG/SQLite —
`tests/native_agent_e2e/test_auto_qa_controller.py`; live OpenRouter
и production acceptance остаются открыты.


## Проверка настоящего TLS/SQLite через Docker Compose

Отдельный job **protected-qa-live-compose** в native E2E GitHub Actions на чистом
runner создаёт одноразовые TLS-сертификаты (DNS SAN), приватные файлы
ключей с разными UID10002/UID10003, реальный Git и SQLite. Он запускает
**реальные** secure-orchestration и secure-quality-gates через Docker Compose.
QA-controller выполняет preflight, а затем через TLS с проверкой CA
обращается к реальным HTTP API: без ключа ответ 401; ADMIN QG
не подходит для Orchestration и наоборот; правильный ADMIN может
создать проект, QG перечисляет gates, подписанный receipt без evidence
отвергается. После настоящего restart обеих служб проект всё ещё
существует в SQLite. Контейнеры и volumes удаляются после проверки.

Это свидетельство уровня **LIVE_TLS_CONTROL_ACCEPTED**, но не полная
SDLC_MVP_ACCEPTED: модель, пользовательский UI, недоверенный тестовый код
и платные OpenRouter запросы не запускаются. Остаточные ограничения
по production sandbox и защищённому UI остаются в задаче #11.


## Состояние экспериментального Docker QA Executor (#117)

В `quality-gates/quality_gates/isolated_tester.py` существует отдельный opt-in исполнитель
с лимитами ресурсов, сетью `none`, непривилегированным UID и readonly checkout.
Его механизм очистки при timeout реализован в #121. Он **пока не включён**
в `NativeQaController` и не участвует в выдаче подписанных QA receipts.

Для Docker bind-mount источника запрещены запятые, символы перевода строки
и возврата каретки, а также символьные ссылки в пути. Это валидация
параметров CLI, а **не** подтверждение безопасности файловой системы
(проверка путей подвержена TOCTOU, если хостовый каталог может меняться).

**Важный остаточный риск:** процесс, вызывающий Docker daemon или имеющий
доступ к `docker.sock`, обладает слишком широкими полномочиями. Нельзя
монтировать Docker socket внутрь QA-сервиса с секретом подписи. Перед
реальным использованием нужен отдельный runner/service без ключей,
негативные интеграционные тесты с настоящим daemon, безопасное удаление
после аварийного завершения и независимый security review. #117 и #11
остаются открытыми.


## Настоящий Docker smoke для отдельного исполнителя

CI workflow `.github/workflows/isolated-qa-docker-smoke.yml` запускает
`scripts/isolated_qa_docker_smoke.py` на GitHub Linux runner с Docker daemon.
Он проверяет фактические UID, read-only checkout, временный /tmp, отсутствие
Docker socket, известных переменных с секретами и сетевого интерфейса `eth0`.
Выбранный Docker image сначала загружается, затем используется локальный
неизменяемый image ID (не tag). Smoke не вызывает LLM и не расходует API бюджет.

**Ограничение:** smoke проверяет только одноразовый opt-in исполнитель.
Он не проверяет malicious escape, ограничения секрета в production mounts,
права Docker daemon, завершение detached children и выдачу подписанного receipt.
Не является основанием для закрытия #117 и #11.


## Browser Compose acceptance: реальный UI и семистадийный запуск (#11)

`frontend/e2e/compose-acceptance.spec.ts` проверяет браузерный UI без `page.route` и без mock adapter: создание проекта, server-side Contract Gate, заполнение канонического семистадийного шаблона, отправку run с семью задачами и сохранение проекта/задач после `page.reload()` с повторным выбором проекта. В этом smoke нет оплаченного OpenRouter и не должен появляться фиктивный статус завершённой задачи: native dispatcher не запускается. Браузерная перезагрузка **не равна перезапуску Docker Compose**; server restart отдельно проверяется backend integration test. Запуск браузерного smoke требует реально работающего обычного Compose frontend/orchestration и совместимого профиля авторизации. Защищённый native overlay с реальными секретами остаётся opt-in и не смешивается с обычным Compose.


## Full protected native SDLC: проверка всех Compose overlays (#11)

Перед opt-in live OpenRouter запуском проверяйте **итоговую объединённую** Compose конфигурацию, а не отдельные YAML-файлы:

```bash
python scripts/check_native_qa_compose.py --live-sdlc
```

Этот режим собирает `compose.trusted-sqlite-control.yml`, `compose.native-worker-runtime.yml`, `compose.native-qa-runtime.yml` вместе с `compose.native-autonomous-dispatch.yml`, `compose.native-autonomous-qa-dispatch.yml`, `compose.native-trusted-git-runtime.yml`, `compose.native-openrouter-egress.yml`, `compose.release-approval.yml` через настоящий `docker compose config --format json`. Проверка отказывает, если неполны защищённые сервисы, worker/gateway Git и автономный QA, отсутствует отдельное release approval, подключён внешний egress к orchestration/gateway/QA, Git mounts попадают в worker или ослаблены read-only/no-restart boundaries. Команда **не запускает контейнеры** и **не вызывает OpenRouter**. Предыдущий запуск без `--live-sdlc` продолжает проверять безопасный preflight профиль.

Это конфигурационный gate, не attestation о выполненном Git commit. Для реальной приёмки всё ещё требуются приватные операторские ключи, живой tool-call и независимая QA/release проверка. Docker bridge egress не ограничивает домены без внешнего firewall.
