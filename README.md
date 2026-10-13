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

Поднимаемые сервисы (`docker-compose.yml`):

| Сервис | Порт | Healthcheck |
|--------|------|-------------|
| `orchestration-server` | 18000 (host) → 8000 (container) | `GET /health` |
| `agent-management` | 8001 | `GET /health` |
| `runtime-hardening` | 8002 | `GET /health` |
| `quality-gates` | 8003 | `GET /health` |
| `frontend` | 5173 | `GET /` |
| `postgres` | 5432 | `pg_isready` |

## Локальная ручная проверка (доверенная машина)

`docker-compose.yml` сейчас предназначен **только для локальной разработки**.
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
docker compose config --quiet
docker compose up -d --build
docker compose ps
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

Настройки внешнего LLM-провайдера пока доступны через agent-management API,
а полноценный раздел настроек в UI отслеживается отдельной задачей.
Успешный healthcheck означает запуск компонентов, **не подтверждает**
полноценный автономный SDLC-конвейер.

В Windows CMD используются те же команды `docker compose ...` без PowerShell.

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

## Структура

| Директория | Назначение | Источник (kanban task) |
|------------|------------|------------------------|
| `orchestration-server/` | Платформенный сервер оркестрации: durable execution, жизненный цикл задач, REST API | t_52732c01 |
| `agent-management/` | Подсистема управления агентами и абстракция LLM-провайдеров | t_cb3ae3dd |
| `runtime-hardening/` | Runtime hardening: контейнерный рантайм, ресурсы (cgroups v2), circuit breaker, health/metrics | t_cea09e5d |
| `quality-gates/` | Гейты качества: tester/reviewer/security/release-prep, evidence store, pipeline | t_ba6ff132 / t_fe85477d |
| `frontend/` | Визуальный редактор workflow (React Flow, TypeScript, Vite) | t_191fcdcb / EditorFS T1–T7 |
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

## Список модулей

### Orchestration server (`orchestration-server/`)
- `orchestration_server/` — движок оркестрации: `engine.py`, `api.py`, `models.py`, `db.py`, `config.py`, `schemas.py`
- `tests/` — жизненный цикл, durability, concurrency, OpenAPI
- `docs/openapi.json` — OpenAPI-спецификация API

### Agent management (`agent-management/`)
- `agent_management/` — CRUD агентов, state machine, провайдеры LLM, tool-policy
- `tests/` — провайдеры, token usage, tool policy, agent CRUD

### Runtime hardening (`runtime-hardening/`)
- `runtime/` — container runtime wrapper, resource manager (cgroups v2), workspace manager, health/metrics, circuit breaker

### Quality gates (`quality-gates/`)
- `quality_gates/` — pipeline, gates (tester/reviewer/security/release-prep), evidence store, release artifacts

### Frontend (`frontend/`)
- React Flow канвас, палитра узлов, property-панели, persistence API client, JSON export/import
- schema: `src/workflow/workflow.schema.json` (Draft 2020-12)
- e2e: Playwright (`e2e/`)
