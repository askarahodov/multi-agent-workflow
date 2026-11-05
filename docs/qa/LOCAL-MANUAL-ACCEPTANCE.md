# Приёмка локального MVP — Issue #8

Этот документ разделяет **запуск контейнеров**, **ручной UI smoke** и **полную автономную разработку**. Не считать успешный `/health`, mock-провайдер или зелёный Compose эквивалентом автономного SDLC.

| Уровень | Что является доказательством | Текущий источник |
|---|---|---|
| `LOCAL_BOOTABLE` | Compose config/build, шесть healthy контейнеров, реальные HTTP `/health` + Vite | Quality Gate → `local Compose build and health` |
| `UI_MANUAL_TESTABLE` | Playwright Chromium по `localhost:5173`: реальный project → workflow definition/revision HTTP → run → task → snapshot log; сохранение фальшивого провайдера и профиля без платного вызова | `apps/frontend/e2e/compose-acceptance.spec.ts` |
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

- Основной `deploy/compose/dev/docker-compose.yml` отключает auth (`AUTH_ENABLED=false`) и содержит `privileged: true` с `docker.sock`: **только доверенная локальная машина**, не публичный сервер/production (#3).
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


## Native task card — read-only execution boundary (#256)

After selecting a run launched from an immutable published workflow version,
select any task and open **Карточка задачи**. The card must display task status,
attempt chronology, reported Git artifacts (clearly labelled worker-reported),
and the independent TESTER/REVIEWER/SECURITY QA status. A verified Contract Gate
or a worker-reported SHA is **not** a release approval.

**Regression and operator checks:**

1. On an active native run, open the task card and confirm there are **no**
   browser Claim, Submit, Fail, Block controls or pre-filled agent ID. A
   read-only session must not be led to impersonate a worker.
2. Follow **Открыть запуск** and **Открыть живой журнал**; both must keep
   the owning run selected, with its authoritative backend status.
3. Follow **Карантин и безопасное восстановление** for a blocked run;
   reconciliation must not re-run tools, lease work, or replay side effects.
4. Refresh the card after backend state changes and check attempts, QA, and
   Git report against server responses. Missing/unverified evidence must
   remain visibly missing or pending, never become a success badge.
5. Repeat with a different task selection. Details from the prior task must
   not be presented as the new task's details.

These product UI restrictions are **not** a substitute for the backend's
authentication, lease, Contract Gate, QA and release approval enforcement.
Native worker/task execution must be validated separately with real approved
credentials and deployment evidence. This checklist is not proof that such a
live acceptance has already been performed.


## Published workflow run preflight — project/graph/contracts (#256)

A published version can be selected in **Запуски** or launched from the
**Редактор**. Both use the read-only orchestration-server preflight
`GET /api/v1/workflows/definitions/{definition_id}/versions/{version_id}/preflight?project_id=...`
before creating any run. The Runs screen exposes **Проверить готовность запуска**
and separately lists passed, blocked and **not verified** checks.

Operator verification on a clean, authorized environment:

1. Publish a supported Start → Agent → automatic Contract Gate → End graph with
   a real Contract owned by the selected project. Select its exact published
   version and run preflight. Project, graph and contract checks must pass.
2. Check that worker connectivity, provider credentials/profile enforcement
   and independent QA/release approval remain **unknown**; `execution_ready`
   must be `false`. This check only permits creation of a *queued-to-be-worked*
   server run, not a claim that live execution has started or can finish.
3. Create an archived graph with unsupported node semantics; a missing Contract
   Gate UUID; a Contract belonging to another project; or select a non-existent
   project/workspace. Each must produce an actionable server-side block with
   no run persisted. Test both the read-only preflight response and the actual
   `POST .../runs` route, which recomputes the same checks.
4. Publish a new version, then switch back to an older version. Confirm the
   preflight and run refer to the explicitly selected immutable snapshot.
   Switching versions invalidates the displayed preflight result.
5. After a successful preflight, remove or revoke a relevant contract *before*
   creation where supported. The launch endpoint must refuse creation even if
   the previous browser report said the contract existed.
6. Require an explicit confirmation mentioning possible paid model usage and
   the unverified worker/provider/QA/release gates. No paid request is made by
   preflight. Follow the run → task → live log → recovery route without
   interpreting a `running` database status as an active live worker.

**Do not sign off** #11, #8 or full #256 from these offline tests. Real worker
presence, identity, budgets, review/QA receipts, human release approval and
browser/Compose persistence require separately recorded live operator evidence.


## Native run log: redaction, stream source and reconnect (#256 / #209)

In **Живой журнал**, select the owning run from **Запуски**. Verify that
websocket/SSE events are labeled `WS/SSE`, while degraded snapshot-derived
events are labeled `снимок API`. A snapshot poll is not evidence of a
connected native worker. The status indicator must say that polling is not
a live stream. On an expired/rejected ticket, the monitor must fail closed:
no anonymous polling or long-lived URL-key fallback.

Verify level and task selectors independently and in combination. They filter
the existing bounded event history locally without modifying execution or
re-requesting paid work. Pause/clear/reconnect must not mutate run/task state.
After a disconnection use **Переподключить поток**: fresh WS/SSE ticket issuance
still requires the current authenticated REST session; events re-delivered from
a prior cursor must not appear twice in the feed. Switching runs must clear
previous run events.

Force a worker failure message containing `Authorization: Bearer SAMPLE`,
`api_key=SAMPLE`, `stream_ticket=SAMPLE` and a URL with a query string.
Neither the event body nor the displayed transport error may show these sample
secrets. Do not treat presentation redaction as adequate upstream protection:
backend, proxy, access logs and tracing still require independent sanitization
and authorization verification. This acceptance section does not certify a
production stream-ticket rollout without #209 independent security approval.
