# multi-agent-workflow

Агентная разработка: платформенная оркестрация + управление агентами + визуальный редактор workflow + hardening агентного рантайма + гейты качества.

> **Канонический каталог проекта — `/mnt/data/multi-agent-workflow/`.**
> Все агенты этой доски ведут разработку ТОЛЬКО здесь (см. `docs/PROJECT_DIRECTORY.md`).

## Структура

| Директория | Назначение | Источник (kanban task) |
|------------|------------|------------------------|
| `orchestration-server/` | Платформенный сервер оркестрации: durable execution, жизненный цикл задач, REST API | t_52732c01 |
| `agent-management/` | Подсистема управления агентами и абстракция LLM-провайдеров | t_cb3ae3dd |
| `runtime-hardening/` | Runtime hardening: контейнерный рантайм, ресурсы, circuit breaker, health/metrics | t_cea09e5d |
| `quality-gates/` | Гейты качества: tester/reviewer/security/release-prep, evidence store, pipeline | t_ba6ff132 / t_fe85477d |
| `frontend/` | Визуальный редактор workflow (React Flow, TypeScript, Vite) | t_191fcdcb / EditorFS T1–T7 |
| `docs/` | Доменная модель, hardening-архитектура, research, ADR, планы, обзоры, аудит | см. ниже |
| `tools/` | Инструменты разработки: spawn агентов, worktree-менеджер, детектор hotspots | t_25e65cca |

### Docs (`docs/`)

| Путь | Содержание | Источник |
|------|-----------|----------|
| `docs/domain-architecture.json` | Доменная модель и записи решений | t_7cd41bc2 |
| `docs/runtime-hardening/` | ADR-001..005, spec, sequence-plan, STRIDE, OpenAPI/AsyncAPI, quota-схемы | t_72478f3c / t_c39cb99e |
| `docs/adr/ADR-010-multi-agent-orchestration.md` | Архитектура мультиагентной оркестрации | t_c55dd026 |
| `docs/research/` | Отчёты research: паттерны автономной разработки, P8.3 hardening, сравнение технологий | t_ca94c155 / t_8aaf9df7 |
| `docs/plans/workflow-editor-implementation-plan.json` | План реализации редактора | t_191fcdcb |
| `docs/reviews/` | Независимые обзоры и верификация P8.3 | t_c2af4bc8 / t_197396cf |
| `docs/audit/task-project-assignment-audit.md` | Аудит привязки задач к проектам | t_fe26d6eb |
| `docs/PROJECT_DIRECTORY.md` | Канонический каталог и правила для всех агентов | t_7f363f69 |

## Список модулей

### Orchestration server (`orchestration-server/`)
- `orchestration_server/` — движок оркестрации: `engine.py`, `api.py`, `models.py`, `db.py`, `config.py`, `schemas.py`
- `tests/` — жизненный цикл, durability, concurrency, OpenAPI
- `docs/openapi.json` — OpenAPI-спецификация API

### Agent management (`agent-management/`)
- `agent_management/` — CRUD агентов, state machine, провайдеры LLM, tool-policy
- `providers/` — абстракция и адаптеры провайдеров
- `tests/` — провайдеры, token usage, tool policy, agent CRUD

### Runtime hardening (`runtime-hardening/`)
- `runtime/` — container runtime wrapper, resource manager (cgroups v2), workspace manager, health/metrics, circuit breaker

### Frontend (`frontend/`)
- React Flow канвас, палитра узлов, property-панели, persistence API client, JSON export/import
- schema: `src/workflow/workflow.schema.json` (Draft 2020-12)
- e2e: Playwright (`e2e/`)

### Docs (`docs/`)
- `domain-architecture.json` — доменная модель и записи решений (t_7cd41bc2)
- `runtime-hardening/` — ADR-001..005, STRIDE threat model, OpenAPI/AsyncAPI, quota-схемы (t_72478f3c)