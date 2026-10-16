# Приёмка локального MVP — Issue #8

Этот документ разделяет **запуск контейнеров**, **ручной UI smoke** и **полную автономную разработку**. Не считать успешный `/health`, mock-провайдер или зелёный Compose эквивалентом автономного SDLC.

| Уровень | Что является доказательством | Текущий источник |
|---|---|---|
| `LOCAL_BOOTABLE` | Compose config/build, шесть healthy контейнеров, реальные HTTP `/health` + Vite | Quality Gate → `local Compose build and health` |
| `UI_MANUAL_TESTABLE` | Playwright Chromium по `localhost:5173`: реальный project → workflow definition/revision HTTP → run → task → snapshot log; сохранение фальшивого провайдера и профиля без платного вызова | `frontend/e2e/compose-acceptance.spec.ts` |
| `CONTRACT_GATE_VERIFIED` | Через реальный Vite proxy/API сервер отвергает `{success:true}` и принимает только корректный `{summary:...}`; SQLite переживает restart | `scripts/local_mvp_api_smoke.py` |
| `NATIVE_LOOP_OFFLINE_VERIFIED` | Offline тест `LLM → tool → LLM → Contract Gate` и проверки no-replay | `tests/native_agent_e2e/` из отдельного Native E2E CI |
| `SDLC_MVP_ACCEPTED` | Настоящий worker автономно проходит требуемые стадии до release-prep и выдаёт Git commit/evidence без Hermes | **НЕ ПОДТВЕРЖДЕНО**: требует полного закрытия P0 #11 и отдельного интеграционного evidence |
| `LIVE_PROVIDER_ACCEPTED` | Явно оплаченный короткий онлайн-тест настоящего OpenRouter, без скрытых запросов | **НЕ ПОДТВЕРЖДЕНО** без ключа, согласованного лимита и оператора |

## Linux — чистый checkout, локальное доверенное устройство

1. Установить Docker Engine и Compose plugin, Git; получить чистый checkout проекта.
2. `docker compose config --quiet`.
3. До ввода **настоящего** ключа OpenRouter установить постоянный `AUTH_ENCRYPTION_KEY` в локальный исключённый из Git `.env`. Для smoke фальшивых провайдеров также необходим допустимый ключ шифрования:
   `docker run --rm python:3.12-slim python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.
4. `docker compose up -d --build`, `docker compose ps`. Все шесть сервисов должны быть healthy.
5. Проверить `curl -fsS http://127.0.0.1:18000/health`, порты `8001`, `8002`, `8003`; открыть `http://localhost:5173`.
6. В браузере проверить разделы **Проект**, **Запуски**, **Kanban**, **Карточка задачи**, **Живой журнал**, **Настройки**. Создать проект, выбрать его, создать run с задачей и открыть карточку. Создать определение и revision в Editor или через `/api/v1/workflows/definitions` и `.../versions`: автоматический smoke проверяет именно реальный браузерный HTTP, а **не** полную процедуру ручного drag/drop Editor.
7. В Настройках создать подключение с **фиктивным** API key; убедиться, что backend `GET /api/v1/providers` не возвращает `auth_config` или ключ; создать профиль модели. **Не нажимать** «Проверка подключения», если не одобрен платный запрос.
8. `python3 scripts/local_mvp_api_smoke.py create --state-file /tmp/maw-smoke.json`; `docker compose restart orchestration-server`; дождаться healthy; `python3 scripts/local_mvp_api_smoke.py verify --state-file /tmp/maw-smoke.json`.
9. `make check` при установленных Python dev зависимости + `npm ci` в frontend; `python -m pytest tests/native_agent_e2e -q` с установленными пакетами. Готовая CI-конфигурация делает релевантные команды в отдельных jobs.
10. Снять с локальной машины реальные логи `docker compose ps`, `docker compose logs --tail=100`, browser screenshot и журналы попыток **без API ключей** и с удалением любых персональных данных.

## Windows Docker Desktop, только CMD (PowerShell и .ps1 не нужны)

В обычной командной строке `cmd.exe` из корня репозитория:

```cmd
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose restart orchestration-server
docker compose logs --tail=100 orchestration-server
```

Браузер: `http://localhost:5173`. Проверить `http://localhost:18000/health`, `http://localhost:8001/health`, `http://localhost:8002/health`, `http://localhost:8003/health`.

После установки Python в Windows CMD: `python scripts\local_mvp_api_smoke.py create --state-file smoke.json`, после restart — `python scripts\local_mvp_api_smoke.py verify --state-file smoke.json`.

**Отдельный статус:** Windows CMD-инструкция подготовлена, но выполнение на реальном Windows Docker Desktop нельзя засчитывать по Linux GitHub runner. Нужен операторский журнал успешного прогона.

## Команда CI для Chromium (Linux с запущенным Compose)

```sh
cd frontend
npm ci
npx playwright install --with-deps chromium
npx playwright test --config compose.playwright.config.ts
```

Этот Playwright конфиг **не** запускает поддельный webServer, не делает `page.route` и не использует `MockAdapter`. API должен отвечать через настоящий Vite proxy. Он не вызывает paid `/completions`. В CI перед `docker compose up` создаётся эфемерный тестовый `AUTH_ENCRYPTION_KEY`; он не используется для продакшен-ключей.

## Известные границы и блокеры

- Основной `docker-compose.yml` отключает auth (`AUTH_ENABLED=false`) и содержит `privileged: true` с `docker.sock`: **только доверенная локальная машина**, не публичный сервер/production (#3).
- Простой dev Compose не запускает native worker автоматически и **не создаёт** реальный OpenRouter вызов. Отдельный opt-in защищённый native worker описан в `docs/NATIVE_WORKER_ACCEPTANCE_RU.md`, требует ключей/cert и явно разрешённого бюджета.
- Текущий UI «Живой журнал» показывает разницу между snapshot при polling; это не исходный durable native `AgentEventJournal`. Нельзя выдавать snapshot UI за настоящий поток agent tool events.
- Полная автономность, SDLC handoffs до release-prep и Git commit в user worktree остаются acceptance критериями **#11**. До подтверждения не присваивать статус `SDLC_MVP_ACCEPTED`.
- Скриншоты не воссоздаются задним числом: CI сохраняет в логах команды и статусы; screenshot Playwright снимает только при ошибке. Для Windows/manual evidence нужен отдельный подтверждённый прогон.

## Диагностика

- `/health` зелёный, но UI пустой — проверить Vite proxy `ORCH_UPSTREAM` и `AGENT_MGMT_UPSTREAM`, а не `localhost` внутри контейнера.
- HTTP 401 в UI — dev Compose ожидает `AUTH_ENABLED=false`; для доверенного production stack требуется отдельная модель токенов. Не отключать auth в защищённом native gateway.
- Подключение провайдера не сохраняется — проверить постоянный `AUTH_ENCRYPTION_KEY`; не ротировать его без процедуры миграции.
- Данные пропали после `docker compose down -v` или `docker compose down` — проверить место хранения SQLite и volume policy. Smoke рестартует контейнер без удаления файлов.
- CI упал — читать именно шаг `Run Chromium browser through Vite proxy` или `Validate real lifecycle, Contract Gate and durable restart`. Не объявлять GREEN, если один из шагов был пропущен.
