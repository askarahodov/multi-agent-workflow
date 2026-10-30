# multi-agent-workflow

Платформа для агентной разработки: сервер оркестрации задач, управление
агентами и LLM-провайдерами, визуальный редактор workflow, hardening
агентного рантайма и гейты качества.

> **Канонический каталог проекта — `/mnt/data/multi-agent-workflow/`.**
> Все агенты этой доски ведут разработку ТОЛЬКО здесь (см. `docs/PROJECT_DIRECTORY.md`).

## Быстрый старт (локально)

Всё управляется одним корневым `Makefile` (точка входа из задачи E9.1).
Требуется Docker с плагином `compose`.

```bash
make up      # собрать образы и поднять весь стек в фоне (docker compose up -d --build)
make ps      # статус сервисов (все контейнеры должны быть healthy)
make logs    # живые логи всех сервисов
make down    # остановить и удалить контейнеры/сети
```

Поднимаемые сервисы (`deploy/compose/dev/docker-compose.yml`):

| Сервис | Порт | Healthcheck |
|--------|------|-------------|
| `orchestration-server` | 18000 (host) → 8000 (container) | `GET /health` |
| `agent-management` | 8001 | `GET /health` |
| `runtime-hardening` | 8002 | `GET /health` |
| `quality-gates` | 8003 | `GET /health` |
| `frontend` | 5173 | `GET /` |
| `postgres` | 5432 | `pg_isready` |

## Локальная ручная проверка (доверенная машина)

`deploy/compose/dev/docker-compose.yml` сейчас предназначен **только для локальной разработки**.
В нём `AUTH_ENABLED=false` у API-сервисов, а внешние порты публикуются
на `127.0.0.1`. Не запускайте эту конфигурацию на публичном сервере,
не проксируйте её в общедоступную сеть и не открывайте порты наружу.

В текущей архитектуре `runtime-hardening` намеренно использует
`privileged: true` и `/var/run/docker.sock` для управления контейнерами
Docker на хосте. Это **доверенная локальная конфигурация**, а не безопасная
модель для запуска недоверенного кода на общей машине. Соответствующий
остаточный риск отслеживается в GitHub Issue #3.

**Старт:**

```bash
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --build
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps
```

Откройте `http://localhost:5173` и проверьте: создание проекта,
выбор проекта, создание workflow run, просмотр доски, задач и журнала.
Сервисы проверяются отдельно через `http://localhost:18000/health`,
`http://localhost:8001/health`, `http://localhost:8002/health` и
`http://localhost:8003/health`.

**Порты:** если на хосте заняты 8000, 8080 или 8081, проект по умолчанию
не использует ни один из них: Orchestration доступен по `localhost:18000`
(внутри контейнера по-прежнему 8000). Все опубликованные порты можно
переопределить в локальном `.env`: `ORCH_HOST_PORT`,
`AGENT_MGMT_HOST_PORT`, `RUNTIME_HOST_PORT`, `QG_HOST_PORT`,
`FRONTEND_HOST_PORT`, `POSTGRES_HOST_PORT` (см. `.env.example`).
Это настройки **хостовых портов**, адреса Docker-сервисов менять не надо.

**Важно:** Docker-сервисные адреса для Vite задаются через `ORCH_UPSTREAM`
и `AGENT_MGMT_UPSTREAM`; они указывают на внутренние Compose hostnames.
Перед сохранением реального OpenRouter API-ключа создайте в корне файл `.env`
(он исключён из Git) с постоянным значением
`AUTH_ENCRYPTION_KEY=<base64 от 32 случайных байт>`. Если ключ поменять
после сохранения учётных данных, старые зашифрованные записи перестанут
расшифровываться. Для чистого smoke-теста без реальных ключей `.env`
необязателен. Значение для `.env` можно сгенерировать без PowerShell:
`docker run --rm python:3.12-slim python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"`.

Настройки OpenRouter уже доступны через раздел «Настройки» в UI (#7).
Данные сохраняются в agent-management; платная диагностика выполняется только после явного согласия пользователя.
Успешный healthcheck означает запуск компонентов, **не подтверждает**
полноценный автономный SDLC-конвейер.

В Windows CMD используются те же команды `docker compose ...` без PowerShell.

## Установка Python-подсистем из произвольного каталога

Зависимости между Python-подсистемами **не используют абсолютные пути
разработчика**. Общий пакет дистрибутива `maw-shared` (импортируется как
`shared`) устанавливается из `./shared` перед зависимыми сервисами.
Все пути ниже относительны к корню репозитория; команды совместимы с
Windows CMD и Linux:

```text
python -m pip install -e ./packages/shared
python -m pip install -e "./orchestration-server[dev]" -e "./agent-management[dev]" -e "./runtime-hardening[dev]"
python -m pip check
```

Для Docker Compose локальная установка Python-пакетов не требуется:
соответствующие Dockerfile уже устанавливают `./shared` внутри образов.
При установке вне монорепозитория сначала предоставьте wheel
`maw-shared==0.1.0` из этого репозитория; не используйте сторонний
пакет с похожим именем. CI проверяет установку всех внутренних пакетов
в чистом Python-окружении.

## Quality gate (проверка качества)

Единый гейт качества из задачи E9.2 — локальный аналог CI-воркфлоу
`.github/workflows/quality-gate.yml`. Прогоняется одной командой:

```bash
make check        # lint + typecheck + backend-test + frontend-check + security
```

Отдельные цели гейта:

```bash
make lint         # eslint (frontend)
make typecheck    # tsc --noEmit (frontend)
make backend-test # pytest по всем Python-подсистемам
make frontend-test # vitest (frontend)
make frontend-check # vitest + schema:validate + production build
make test         # backend-test + frontend-test
make security     # статический security-скан (quality-gates SecurityGate)
```

`make check` завершается успешно только если **все** проверки прошли
(каждый шаг — prerequisite, гейт падает на первой ошибке). Тот же набор
проверок выполняется в CI: job `quality-gate` в
`.github/workflows/quality-gate.yml` агрегирует `backend`, `frontend`,
`lint` и `security` и падает, если любой из них не `success`.

## Native AI worker и независимость от Hermes

Для работы конечного пользователя **Hermes не нужен**: сервер оркестрации, Native Worker, Agent Loop, Trusted Gateway и Contract Gate принадлежат этой платформе. Hermes/CAL в исторических `tools/agent-orchestration` относится исключительно к разработке самого продукта и **не входит** в runtime-зависимости продукта.

`POST /api/v1/workflows/runs` поддерживает задачи со списком `depends_on` (индексы более ранних задач, от 0). Сервер разрешает следующий `claim` только после успешного Contract Gate для всех предыдущих стадий, а их короткие проверенные результаты передаёт далее как служебный `_maw_upstream`. В UI раздел «Запуски» имеет отдельный переключатель последовательного выполнения, **не заменяющий** обязательные контракты на результат.

Это пока не означает полную автономную SDLC-разработку. Основной локальный Compose не запускает платную модель автоматически; доверенный worker включается через отдельный opt-in Compose. Опциональный per-attempt Git worktree/commit уже доступен через отдельный trusted gateway; сервер сохраняет такой SHA как `worker_reported`, не как независимо проверенный release artifact. Leased native worker требует явный Contract Gate для каждой стадии, тогда как обычные non-leased задачи остаются обратно совместимыми. Для `SDLC_MVP_ACCEPTED` по-прежнему нужны независимые test/review/security gates, release-prep/human approval, строгая проверка Git evidence и подтверждённый live-провайдер. Подробности: [ADR-111](docs/adr/ADR-111-native-sdlc-dependencies.md), [native worker](docs/NATIVE_WORKER_ACCEPTANCE_RU.md) и [Issue #11](https://github.com/askarahodov/multi-agent-workflow/issues/11).

## Структура

| Директория | Назначение | Источник (kanban task) |
|------------|------------|------------------------|
| `services/orchestration-server/` | Платформенный сервер оркестрации: durable execution, жизненный цикл задач, REST API | t_52732c01 |
| `services/agent-management/` | Подсистема управления агентами и абстракция LLM-провайдеров | t_cb3ae3dd |
| `services/runtime-hardening/` | Runtime hardening: контейнерный рантайм, ресурсы (cgroups v2), circuit breaker, health/metrics | t_cea09e5d |
| `services/quality-gates/` | Гейты качества: tester/reviewer/security/release-prep, evidence store, pipeline | t_ba6ff132 / t_fe85477d |
| `apps/frontend/` | Визуальный редактор workflow (React Flow, TypeScript, Vite) | t_191fcdcb / EditorFS T1–T7 |
| `shared/` | Общий Python-пакет: auth- и security-middleware, используемый сервисами | E8 |
| `tools/` | Инструменты разработки: spawn агентов, worktree-менеджер, детектор hotspots | t_25e65cca |
| `scripts/` | Служебные скрипты (например, `security_scan.py` для `make security`) | E9.2 |
| `docs/` | Доменная модель, hardening-архитектура, research, ADR, планы, обзоры, аудит | см. ниже |

### Docs (`docs/`)

| Путь | Содержание | Источник |
|------|-----------|----------|
| `docs/domain-architecture.json` | Доменная модель и записи решений | t_7cd41bc2 |
| `docs/runtime-hardening/` | ADR-001..005, spec, sequence-plan, STRIDE, OpenAPI/AsyncAPI, quota-схемы | t_72478f3c / t_c39cb99e |
| `docs/adr/ADR-010-multi-agent-orchestration.md` | Архитектура мультиагентной оркестрации | t_c55dd026 |
| `docs/research/` | Отчёты research: паттерны автономной разработки, P8.3 hardening, сравнение технологий | t_ca94c155 / t_8aaf9df7 |
| `docs/plans/` | Планы реализации: редактор workflow, миграция календаря | t_191fcdcb |
| `docs/reviews/` | Независимые обзоры и верификация P8.3 | t_c2af4bc8 / t_197396cf |
| `docs/audit/task-project-assignment-audit.md` | Аудит привязки задач к проектам | t_fe26d6eb |
| `docs/integration-audit/` | Аудит интеграции подсистем (E1/E2): архитектура, несовместимости API, ownership, порядок зависимостей, ADR-101..103 | EPIC-INT E1/E2 |
| `docs/PROJECT_DIRECTORY.md` | Канонический каталог и правила для всех агентов | t_7f363f69 |
| `docs/ci-guide.md` | **CI & GitHub Guide for Agents** — `gh` auth, workflows, logs, artifacts, secrets, troubleshooting, verified green runs | t_aea44484 / t_25ec9e17 |

## Список модулей

### Orchestration server (`services/orchestration-server/`)
- `orchestration_server/` — движок оркестрации: `engine.py`, `api.py`, `models.py`, `db.py`, `config.py`, `schemas.py`
- `tests/` — жизненный цикл, durability, concurrency, OpenAPI
- `docs/openapi.json` — OpenAPI-спецификация API

### Agent management (`services/agent-management/`)
- `agent_management/` — CRUD агентов, state machine, провайдеры LLM, tool-policy
- `tests/` — провайдеры, token usage, tool policy, agent CRUD

### Runtime hardening (`services/runtime-hardening/`)
- `runtime/` — container runtime wrapper, resource manager (cgroups v2), workspace manager, health/metrics, circuit breaker

### Quality gates (`services/quality-gates/`)
- `quality_gates/` — pipeline, gates (tester/reviewer/security/release-prep), evidence store, release artifacts

### Frontend (`apps/frontend/`)
- React Flow канвас, палитра узлов, property-панели, persistence API client, JSON export/import
- schema: `src/workflow/workflow.schema.json` (Draft 2020-12)
- e2e: Playwright (`e2e/`)


### Статус Native Worker, Trusted Gateway и MVP

Базовый `deploy/compose/dev/docker-compose.yml` служит **только** для запуска UI/API на доверенной локальной машине и не запускает платного агента автоматически. Отдельный opt-in co-located SQLite worker/gateway подготовлен и документирован в [руководстве Native Worker](docs/NATIVE_WORKER_ACCEPTANCE_RU.md) (#33/#54 закрыты); ограничения изоляции и ручного развёртывания остаются существенными.

**Независимая локальная приёмка:** [чеклист Linux, Windows CMD, браузер/API smoke и уровни готовности](docs/qa/LOCAL-MANUAL-ACCEPTANCE.md). CI проверяет реальный Chromium UI через Vite proxy, контрактную валидацию API и SQLite после рестарта; отдельно native E2E проверяет ограниченный `LLM → tool → Contract Gate` offline. Это подтверждает `LOCAL_BOOTABLE` / `UI_MANUAL_TESTABLE` при зелёных запусках, но **не подтверждает** `SDLC_MVP_ACCEPTED` без полного сценария до release-prep и Git-артефактов из P0 [#11](https://github.com/askarahodov/multi-agent-workflow/issues/11). Настоящий OpenRouter smoke возможен только с одобренным ключом и бюджетом.


### Автоматический независимый QA после native Git commit

Отдельный opt-in доверенный QA-контроллер автоматически обнаруживает завершённые native стадии, сверяет ref Git, запускает независимые `tester/reviewer/security` и передаёт QG-signed receipt оркестратору. Native worker **не получает** ключей подписи или QA ADMIN. [Настройка и ограничения](docs/qa/issue-11-auto-controller-ru.md). Стандартный dev Compose не превращается в защищённый режим; санкционированный live OpenRouter и production sandbox по-прежнему обязательны для приёмки #11.


### Защищённый QA Compose (отдельный opt-in)

Независимый подписанный QA-контур теперь имеет отдельный Compose overlay с TLS и отдельными операторскими ключами, не выдаваемыми native worker: [порядок настройки и ограничения](docs/qa/issue-11-secure-compose-ru.md). Это **не** полноценный многопользовательский sandbox и не live OpenRouter smoke. Не объединять с небезопасным базовым `deploy/compose/dev/docker-compose.yml`.


**Реальный protected-Compose smoke:** отдельный CI job запускает TLS Orchestration/QG с одноразовыми приватными ключами и SQLite, проверяет API роли и restart без вызова OpenRouter. Подробности в [руководстве защищённого QA](docs/qa/issue-11-secure-compose-ru.md). Этот контроль не заменяет полный UI + provider acceptance #11.
