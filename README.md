# multi-agent-workflow

Агентная разработка: платформенная оркестрация + управление агентами + визуальный редактор workflow + hardening агентного рантайма.

## Структура

| Директория | Назначение | Источник (kanban task) |
|------------|------------|------------------------|
| `orchestration-server/` | Платформенный сервер оркестрации: durable execution, жизненный цикл задач, REST API | t_52732c01 |
| `agent-management/` | Подсистема управления агентами и абстракция LLM-провайдеров | t_cb3ae3dd |
| `runtime-hardening/` | Runtime hardening: контейнерный рантайм, ресурсы, circuit breaker, health/metrics | t_cea09e5d |
| `frontend/` | Визуальный редактор workflow (React Flow, TypeScript, Vite) | t_191fcdcb / EditorFS T1–T7 |
| `docs/` | Доменная модель (`domain-architecture.json`) и hardening-архитектура (ADRs, OpenAPI/AsyncAPI) | t_7cd41bc2 / t_72478f3c |

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