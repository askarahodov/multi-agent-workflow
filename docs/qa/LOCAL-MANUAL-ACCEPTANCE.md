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

## Обязательная резервная копия при переходе со старого Git-tracked SQLite (#311)

В версиях до этого исправления `services/orchestration-server/orchestration.db` была
**отслеживаемым бинарным файлом**. Исправление удаляет файл **из нового дерева Git**,
но намеренно оставляет старые Git objects/history. При `git switch` или `git pull`
Git может удалить старый tracked файл, если он не модифицирован, либо прервать
переключение из-за локальных изменений. **Не обновляйте ветку с нужной БД без backup.**

Последовательность для оператора доверенного локального Compose:

1. Из корня репозитория **до `git switch`/`git pull`** остановите только запись
   orchestration: `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml stop orchestration-server`.
   Не выполняйте `down -v` и не стирайте volumes.
2. Создайте приватный каталог вне отслеживаемых файлов: `mkdir -p .local`
   (Windows CMD: `if not exist .local mkdir .local`).
3. Создайте **консистентную копию SQLite** через backup API Python с остановленного
   сервиса, чтобы включить все WAL-транзакции:

   ```text
   python -c "import sqlite3; from pathlib import Path; p=Path('services/orchestration-server/orchestration.db'); assert p.is_file(), 'No local DB found'; s=sqlite3.connect('file:'+p.as_posix()+'?mode=ro',uri=True); t=sqlite3.connect('.local/orchestration-before-untrack.db'); s.backup(t); t.close(); s.close()"
   ```

4. Проверьте backup: `python -c "import sqlite3; c=sqlite3.connect('.local/orchestration-before-untrack.db'); assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; c.close()"`.
   Не отправляйте базу/локальные данные в чат, issue или PR.
5. **Переместите** прежний tracked `services/orchestration-server/orchestration.db`
   в `.local/` под другим именем **вместе с возможными файлами `-wal`,
   `-shm`, `-journal`**. Старую копию и sidecars оставьте до приёмки.
   Только после этого переключайте ветку / выполняйте `git pull --ff-only`.
6. Убедитесь, что `git ls-files -- services/orchestration-server/orchestration.db`
   ничего не возвращает. Скопируйте проверенный `.local/orchestration-before-untrack.db`
   обратно в `services/orchestration-server/orchestration.db`. Повторно проверьте
   `PRAGMA integrity_check` на восстановленной БД, запустите Compose и
   прочитайте ранее созданные данные. Не удаляйте backup до проверки.

Dev Compose хранит SQLite по `sqlite+aiosqlite:///./orchestration.db` внутри
`/app`, который является **bind mount** `./services/orchestration-server`.
Это **не** named volume; смена пути без отдельной миграции привела бы к потере
видимости существующих данных. В чистом checkout новая схема создаётся сервером
через `create_all` при старте. Не переписывайте историю Git для удаления
исторической базы без отдельного согласования миграции со всеми участниками.

## Локальный API smoke и корпоративный прокси (#312)

При обращении к `127.0.0.1`, `localhost` или `::1`
`scripts/local_mvp_api_smoke.py` использует отдельный opener **без прокси**,
даже при заданном `HTTP_PROXY` без корректного `NO_PROXY`.
Для других base URL используется стандартное поведение `urllib`.
HTTP-диагностика содержит лишь метод/путь **без query** и статус;
ошибки транспорта не выводят URL, тела ответа или секреты прокси.
Регрессия без внешнего Интернета: `python -m pytest scripts/test_local_mvp_api_smoke.py -q`.

## Linux — чистый checkout, локальное доверенное устройство

1. Установить Docker Engine и Compose plugin, Git; получить чистый checkout проекта.
2. Из корня репозитория: `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet` (или `make up` для запуска на Linux).
3. До ввода **настоящего** ключа OpenRouter установить постоянный `AUTH_ENCRYPTION_KEY` в локальный исключённый из Git `.env`. Для smoke фальшивых провайдеров также необходим допустимый ключ шифрования:
   `docker run --rm python:3.12-slim python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.
4. `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --build`, затем `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps`. Все шесть сервисов должны быть healthy.
5. Проверить `curl -fsS http://127.0.0.1:18000/health`, порты `8001`, `8002`, `8003`; открыть `http://localhost:5173`.
6. В браузере проверить разделы **Проект**, **Запуски**, **Kanban**, **Карточка задачи**, **Живой журнал**, **Настройки**. Создать проект, выбрать его, создать run с задачей и открыть карточку. Создать определение и revision в Editor или через `/api/v1/workflows/definitions` и `.../versions`: автоматический smoke проверяет именно реальный браузерный HTTP, а **не** полную процедуру ручного drag/drop Editor.
7. В Настройках создать подключение с **фиктивным** API key; убедиться, что backend `GET /api/v1/providers` не возвращает `auth_config` или ключ; создать профиль модели. **Не нажимать** «Проверка подключения», если не одобрен платный запрос.
8. `python3 scripts/local_mvp_api_smoke.py create --state-file /tmp/maw-smoke.json`; `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml restart orchestration-server`; дождаться healthy; `python3 scripts/local_mvp_api_smoke.py verify --state-file /tmp/maw-smoke.json`.
9. `make check` при установленных Python dev зависимости + `npm ci` в frontend; `python -m pytest tests/native_agent_e2e -q` с установленными пакетами. Готовая CI-конфигурация делает релевантные команды в отдельных jobs.
10. Снять с локальной машины реальные логи `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps`, `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml logs --tail=100`, browser screenshot и журналы попыток **без API ключей** и с удалением любых персональных данных.

## Windows Docker Desktop, только CMD (PowerShell и .ps1 не нужны)

В обычной командной строке `cmd.exe` из корня репозитория:

```cmd
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --build
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml restart orchestration-server
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml logs --tail=100 orchestration-server
```

Браузер: `http://localhost:5173`. Проверить `http://localhost:18000/health`, `http://localhost:8001/health`, `http://localhost:8002/health`, `http://localhost:8003/health`.

После установки Python в Windows CMD: `python scripts\local_mvp_api_smoke.py create --state-file smoke.json`, после restart — `python scripts\local_mvp_api_smoke.py verify --state-file smoke.json`.

Все команды выше выполняются из **корня репозитория**. Используется `deploy/compose/dev/docker-compose.yml`, потому что в корне нет `docker-compose.yml`.

**Отдельный статус:** Windows CMD-инструкция подготовлена, но выполнение на реальном Windows Docker Desktop нельзя засчитывать по Linux GitHub runner. Нужен операторский журнал успешного прогона.

## Команда CI для Chromium (Linux с запущенным Compose)

```sh
cd apps/frontend
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


## Проверка QA на уровне запуска: обязательны сведения о попытке и Git (#256)

Сводка **Запуски** и **Карточка задачи** должны использовать одинаковые критерии достоверности. Сводка вправе учитывать результат QA как подтверждённый **только** при выполнении всех условий для каждой завершённой задачи, состоянием которой управляет сервер:

1. Задача принадлежит выбранному запуску; идентификаторы задач уникальны во всём ответе сервера, включая все страницы с курсором.
2. Задача имеет структурно корректную аттестацию QA с тремя различными идентификаторами запусков tester/reviewer/security, точным идентификатором задачи, идентификатором завершённой попытки и SHA из 40 символов.
3. Отдельно полученный список попыток целиком относится к этой задаче, не содержит повторяющихся идентификаторов и включает именно указанную завершённую попытку.
4. Отдельно полученный корректный список Git-отчётов целиком относится к задаче, содержит допустимые относительные пути изменений и **тот же** идентификатор попытки и SHA, что и аттестация QA.
5. Сама задача завершена. Аттестация неуспешной или ожидающей задачи не может учитываться как завершённая независимая QA.

Ошибка GET, запоздавший ответ после переключения запуска, чужая задача или попытка, поддельная аттестация, иной SHA, недопустимые Git-пути или незавершённая попытка должны давать статус **не проверено**, а не зелёный индикатор. Проверка ограничена 25 сводками задач и пятью одновременно выполняемыми группами запросов по задачам; для более крупных запусков отображается **неизвестна**, а не неподтверждённый успех.

**Воспроизводимая автономная проверка:**
`cd apps/frontend && npx vitest run src/mvp/sections/RunIntegritySummary.test.tsx`.
Приёмка Compose/Chromium намеренно подменяет через `page.route` ответ 200 одного endpoint QA, в то время как **реальный сервер** продолжает предоставлять задачу, попытки и Git evidence. Поддельная аттестация не должна делать ожидающий запуск зелёным. Остальная часть браузерного сценария использует реальные запросы API с сохранением данных, Contract Gate и проверку перезапуска.

В интерфейсе происхождение Git evidence по-прежнему обозначается **worker_reported**. Это не заменяет независимую проверку Git через trusted gateway, разрешение выпуска человеком или согласование реального платного native execution.

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


## Журнал native-запуска: скрытие секретов, источник потока и переподключение (#256 / #209)

В разделе **Живой журнал** выберите соответствующий запуск из **Запуски**. Убедитесь, что события websocket/SSE помечены как `WS/SSE`, а события из резервного снимка — как `снимок API`. Опрос снимков не подтверждает подключение native worker. Индикатор состояния должен явно показывать, что опрос не является живым потоком. При просроченном или отклонённом ticket монитор обязан отказать безопасно: без анонимного опроса или возврата к долговечному ключу в URL.

Проверьте фильтры уровня и задачи отдельно и совместно. Они локально фильтруют ограниченную историю событий, не меняя выполнение и не инициируя повторную платную работу. Пауза, очистка и переподключение не должны менять состояние запуска или задачи.
После разрыва соединения нажмите **Переподключить поток**: выдача свежего WS/SSE ticket по-прежнему требует текущей аутентифицированной REST-сессии; события, повторно доставленные с предыдущего курсора, не должны дублироваться. При смене запуска прежние события должны очищаться.

Вызовите тестовую ошибку worker, содержащую `Authorization: Bearer SAMPLE`, `api_key=SAMPLE`, `stream_ticket=SAMPLE`, URL со строкой запроса и адрес прокси `http://operator:PRIVATE_CANARY@proxy.invalid:8080`.
Если опрос снимка API недоступен, индикатор должен показывать **Снимок API недоступен — состояние запуска устарело**, а не видимость исправного соединения.
Ни тело события, ни отображаемая ошибка транспорта не должны содержать эти тестовые секреты. Маскирование в интерфейсе не заменяет защиту вышестоящих компонентов: backend, прокси, журналы доступа и трассировка требуют независимой проверки очистки данных и авторизации. Данный раздел не подтверждает production rollout stream-ticket без независимого security approval по #209.

## Браузерная приёмка опубликованного графа редактора в Chromium (#253 / #256)

Тест Playwright на базе Compose `apps/frontend/e2e/compose-acceptance.spec.ts` проверяет **текущий** интерфейс, а не устаревшую ручную форму из семи задач. Он работает с шестью исправными сервисами через реальный прокси Vite `/api/v1`, без адаптера в памяти. Изолированный отрицательный тест QA намеренно подменяет **только** браузерный запрос GET к QA через `page.route`, чтобы доказать: недостоверный ответ 200 не может повысить статус незавершённой задачи; состояние задачи, попытки и Git берётся из реальных ответов сервера.

Тест создаёт уникальный проект, реальные сохраняемые ссылки agent-management (mock provider, model profile, tool policy, agent definition), а также Contract Gate в границах проекта; настраивает шаблон редактора с одним агентом, сохраняет черновик и публикует неизменяемую версию. Chromium перезагружает страницу, открывает сохранённый workflow, проверяет серверный снимок и отчёт предварительной проверки, затем явно подтверждает предупреждение и запускает **выбранную** версию.
Ответ и серверная задача должны содержать идентификаторы опубликованной версии, узла графа, контракта и агента; сведения задачи остаются доступными только для чтения, журнал показывает серверное событие запуска. Повторная перезагрузка должна сохранить запуск и задачу.

Во втором браузерном сценарии создаётся архивный неподдерживаемый граф с корректным проектом и контрактом. Предварительная проверка должна заблокировать его, а прямой вызов `POST .../runs` — завершиться ошибкой **без создания запуска**. Это проверяет безопасный отказ сервера даже при обходе интерфейса.

Запустите на Linux с чистым локальным стеком (без реального платного API-ключа):

```sh
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up --build -d
cd apps/frontend
npm ci
npx playwright install --with-deps chromium
npx playwright test --config compose.playwright.config.ts
```

Задача CI `local Compose build and health` автоматически запускает этот набор при изменении файла приёмки. **Не приравнивайте автономную браузерную проверку** к реальному выполнению native worker, полной семантике графа из 11 узлов, согласованному security rollout stream-ticket, независимой QA/приёмке выпуска или операторской приёмке в Windows: для них требуются отдельные доказательства.

## Atomic publication and authoritative current version (#253)

Published workflow versions are immutable records; `WorkflowDefinition.version`
is a mutable draft revision and `current_version_id` is the server's current
published pointer. A successful publication must insert exactly one version
row and move the pointer **in the same database transaction**, guarded by a
compare-and-swap on the draft revision. A stale second editor or concurrent
publication must receive a conflict without changing the pointer or adding
a phantom published version.

Acceptance regression: save/publish version 1; inspect the workflow GET and
confirm `current_version_id` equals the new immutable version ID. Modify the
draft, save/publish version 2, reload the editor, and verify version 2 remains
selected even when version-list pagination orders version 1 first. Verify that
version 1 remains intact and can be selected for launch. Repeat a publication
with the pre-publication `expected_version`: it must return 409 with no new
version row, and an old draft save must likewise fail. Unsupported graphs
still fail strict publish without mutating the definition.

This is database/editor revision safety, not evidence of live model policy
enforcement, independent QA, or release authorization.


## Published workflow native execution boundary (#253 / #11 / #256)

Published graph references to agent/model/tool policies are provenance, not
capabilities. Only an explicitly enabled, HTTPS-authenticated **leased** native
worker with all three operator-pinned profile IDs may claim a published
workflow task. An unleased HTTP worker, a leased worker with no private profile
binding, and the legacy in-process worker must refuse the published run
**before claiming any attempt or invoking any model or tool**. This must remain
true even when an unleased worker happens to have matching UUID metadata.

Regression acceptance:
1. Create a compiled published run. Inspect that its immutable source version
   and agent/model/policy references are present in authoritative server data.
2. Exercise an unleased HTTP native worker with *matching* profile pins: it must
   fail closed with no attempt and no provider/tool call.
3. Exercise a leased HTTP native worker with no profile pins: same refusal.
4. Exercise a local native worker against the published run: it must refuse
   before constructing its runner.
5. Exercise an explicitly approved leased HTTPS worker with exact private
   pins: its normal contract/lease tests must continue passing. Incorrect
   pins must never cause a fallback to a legacy worker.
6. Exercise an old manually launched run with the legacy worker: it may
   continue to work under existing manually authorized permissions.

This boundary does **not** prove the runtime model selection matches agent
management's model catalog, that tool-policy permissions are independently
loaded/enforced, or that budgets, independent QA and release approval have
passed. Do not enable production native execution or close entire #253/#11
on this regression alone.


## Отрицательная сквозная приёмка: провал независимой QA блокирует SDLC

Приёмка #11 должна доказывать не только успешную семистадийную цепочку.
`tests/native_agent_e2e/test_auto_qa_controller.py` выполняет защищённый
offline E2E без Hermes и платного провайдера: настоящий leased HTTP worker
пишет файл через trusted gateway, Git worktree создаёт fenced commit,
server-owned Contract Gate принимает JSON; **отдельный QA-сервис**
запускает намеренно неуспешную tester-команду в изолированном checkout.

Обязательные утверждения одного интеграционного сценария:

1. Worker завершает первый этап и оставляет verified Git evidence, но
   `QA status` остаётся `pending`, поскольку tester-проверка провалилась.
2. Следующий этап с зависимостью на первый **не исполняется** даже после
   повторного polling native worker; никакого второго model/tool call.
3. Ни worker, ни orchestration admin, ни QA admin не способны подписать
   отдельное release approval (403). Настоящий release approver также
   получает **409** до завершения всех обязательных QA gates.
4. После рестарта нового orchestration-server с тем же SQLite
   pending QA / непроходимая зависимость / отказ в выпуске сохраняются.
   Git HEAD исходного проекта не изменяется, временный checkout QA удалён.
5. Только успешный отдельный операторский QA процесс и последующее
   разрешение выпуска способны продвинуть процесс. Тест **не** создаёт
   фальшивую аттестацию и не вызывает внешние модели.

Локальная команда из checkout с установленными пакетами:

```sh
python -m pytest tests/native_agent_e2e/test_auto_qa_controller.py -q
```

В CI запуск входит в native-agent cross-service E2E c пустым HOME и без
Hermes в PATH. Это реальная работа Git/SQLite/HTTP и QA subprocess, но
**не live OpenRouter и не production multi-container approval**.
Не закрывайте #11/#8 без разрешённого live tool-call, операторских
подписей, TLS/Compose deployment и независимого review.
