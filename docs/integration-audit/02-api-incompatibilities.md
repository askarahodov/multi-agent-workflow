# EPIC-INT E2 — Таблица несовместимостей API (TASK-01)

> Источник: статический анализ `apps/frontend/src/api/httpAdapter.ts`, `apps/frontend/src/api/types.ts`, `services/orchestration-server/orchestration_server/api.py`, `services/agent-management/agent_management/api.py`, `services/orchestration-server/docs/openapi.json`, `services/agent-management/agent_management/schemas.py`.

---

## Легенда
| Колонка | Значение |
|---------|----------|
| **Endpoint / Method** | Путь и HTTP-метод, который вызывает frontend |
| **Frontend-ожидание** | DTO, пагинация, формат ответа, которые ждёт `HttpAdapter`/`types.ts` |
| **Backend-факт** | Что реально существует в orchestration-server или agent-management |
| **Решение** | Архитектурное решение (ADR-101): что менять — backend-пути, frontend-адаптер, или вводить единый gateway |

---

## 1. Workflow Definitions (CRUD + Versions) — **КРИТИЧЕСКО: домен отсутствует в backend**

| # | Endpoint / Method | Frontend-ожидание | Backend-факт | Решение |
|---|-------------------|-------------------|--------------|---------|
| 1 | `GET /workflows/definitions` | `CursorPage<WorkflowDefinitionDTO>`<br/>`params: after?, limit?`<br/>`next_cursor` | **НЕТ в orchestration-server**<br/>`grep workflows/definitions` — 0 | **ADR-101:** Добавить домен `WorkflowDefinition` + `WorkflowVersion` в orchestration-server (новые таблицы, модели, endpoint). ИЛИ: перенести в agent-management под `/api/v1` и проксировать. |
| 2 | `GET /workflows/definitions/{id}` | `WorkflowDefinitionDTO`<br/>`id, name, description, definition, is_active, version, created_at, updated_at` | **НЕТ** | То же |
| 3 | `POST /workflows/definitions` | `CreateWorkflowRequest` → `WorkflowDefinitionDTO` | **НЕТ** | То же |
| 4 | `PUT /workflows/definitions/{id}` | `UpdateWorkflowRequest` → `WorkflowDefinitionDTO` | **НЕТ** | То же |
| 5 | `GET /workflows/definitions/{id}/versions` | `CursorPage<WorkflowVersionDTO>`<br/>`version_number, definition_snapshot, changelog, created_by, created_at` | **НЕТ** | То же |
| 6 | `POST /workflows/definitions/{id}/versions` | `CreateVersionRequest` → `WorkflowVersionDTO` | **НЕТ** | То же |

**Вывод:** Весь домен **design-time** (WorkflowDefinition, Version) отсутствует. Orchestration-server имеет только **runtime** (WorkflowRun, Task, TaskAttempt). Frontend не может работать в live-режиме.

---

## 2. Agent Definitions — **ЧАСТИЧНО: есть в agent-management, но другой формат**

| # | Endpoint / Method | Frontend-ожидание | Backend-факт (agent-management) | Решение |
|---|-------------------|-------------------|----------------------------------|---------|
| 7 | `GET /agents/definitions` | `CursorPage<AgentDefinitionRef>`<br/>`AgentDefinitionRef: {id, name, description?}`<br/>Пагинация: `after`, `limit`, `next_cursor` | `GET /api/v1/agents/definitions`<br/>`AgentDefinitionListResponse: {items: AgentDefinitionResponse[], total: int}`<br/>`AgentDefinitionResponse` содержит: `system_prompt`, `default_model_profile_id`, `default_tool_policy_id`, `capabilities`, `config_schema`, `version`, `created_at`, `updated_at`<br/>Пагинация: `offset`, `limit` → `items/total` | **ADR-101:** Унифицировать пагинацию на `CursorPage` (cursor-based) во всех подсистемах. Frontend адаптер ожидает `after/next_cursor`. Backend должен вернуть совместимый формат. Добавить маппинг в gateway или изменить agent-management. |

---

## 3. Model Profiles — **ЧАСТИЧНО: есть в agent-management, другой формат**

| # | Endpoint / Method | Frontend-ожидание | Backend-факт (agent-management) | Решение |
|---|-------------------|-------------------|----------------------------------|---------|
| 8 | `GET /model-profiles` | `CursorPage<ModelProfileRef>`<br/>`ModelProfileRef: {id, name, provider_id?, model_id?, display_name?}`<br/>Пагинация: `after`, `limit`, `next_cursor` | `GET /api/v1/model-profiles`<br/>`ModelProfileListResponse: {items: ModelProfileResponse[], total: int}`<br/>`ModelProfileResponse`: `provider_id`, `model_id`, `display_name`, `parameters`, `context_window`, `cost_per_1k_input`, `cost_per_1k_output`, `capabilities`, `is_default`, `version`, `created_at`, `updated_at`<br/>Пагинация: `offset`, `limit` | **ADR-101:** То же — унифицировать пагинацию. Frontend использует подмножество полей (reference для селекторов), backend возвращает полный объект. Нужен маппинг/проекция. |

---

## 4. Tool Policies — **ЧАСТИЧНО: есть в agent-management, другой формат**

| # | Endpoint / Method | Frontend-ожидание | Backend-факт (agent-management) | Решение |
|---|-------------------|-------------------|----------------------------------|---------|
| 9 | `GET /tool-policies` | `CursorPage<ToolPolicyRef>`<br/>`ToolPolicyRef: {id, name, description?}`<br/>Пагинация: `after`, `limit`, `next_cursor` | `GET /api/v1/tool-policies`<br/>`ToolPolicyListResponse: {items: ToolPolicyResponse[], total: int}`<br/>`ToolPolicyResponse`: `permissions` (JSON), `is_default`, `version`, `created_at`, `updated_at`<br/>Пагинация: `offset`, `limit` | **ADR-101:** Унифицировать пагинацию. Frontend нужен только `id, name, description` для селектора. Backend возвращает полный `permissions` — лишнее для UI. |

---

## 5. Runtime Domain (Orchestration Server) — **Frontend НЕ вызывает, но должен для сквозного ЖЦ**

| # | Endpoint / Method | Назначение | Frontend статус | Решение |
|---|-------------------|------------|-----------------|---------|
| 10 | `POST /workflows/runs` | Запуск workflow (создаёт Tasks) | **Не вызывается** (`grep workflows/runs` в frontend — 0) | **ADR-102:** Добавить в `HttpAdapter` метод `launchRun(request)` → вызывать из UI (кнопка «Run»). Требует `WorkflowDefinition` → `WorkflowRun` маппинга. |
| 11 | `GET /workflows/runs` | Список раннов | Не вызывается | Добавить в UI (панель Runs). |
| 12 | `GET /workflows/runs/{run_id}` | Детали ранна + задачи | Не вызывается | Добавить в UI (мониторинг). |
| 13 | `GET /workflows/runs/{run_id}/tasks` | Задачи ранна | Не вызывается | Добавить в UI. |
| 14 | `POST /tasks/{task_id}/claim` | Агент забирает задачу | Не вызывается | Вызывается **агентом** (не frontend). |
| 15 | `POST /tasks/{task_id}/attempts/{attempt_id}/submit` | Сдача результата + верификация | Не вызывается | Вызывается агентом. |
| 16 | `POST /tasks/{task_id}/attempts/{attempt_id}/fail` | Отказ попытки | Не вызывается | Вызывается агентом. |
| 17 | `POST /tasks/{task_id}/block` | Блокировка задачи | Не вызывается | Вызывается агентом/оператором. |

---

## 6. Сводная таблица несовместимостей

| Категория | Количество endpoint | Статус | Приоритет исправления |
|-----------|---------------------|--------|----------------------|
| Workflow Definition CRUD | 6 | **Отсутствуют полностью** | **P0** — блокирует live-режим frontend |
| Agent Definitions | 1 | Существует в agent-management, diff пагинация/DTO | **P1** — нужен маппинг/единый формат |
| Model Profiles | 1 | Существует в agent-management, diff пагинация/DTO | **P1** |
| Tool Policies | 1 | Существует в agent-management, diff пагинация/DTO | **P1** |
| Workflow Runtime (runs/tasks) | 7 | Существуют в orchestration-server, **frontend не вызывает** | **P1** — для сквозного ЖЦ |
| Auth / Error format | — | Frontend ждёт RFC 9457 Problem Details; orchestration-server возвращает ProblemDetail; agent-management — тоже | **OK** — совпадает |

---

## 7. Конкретные расхождения DTO

### 7.1 Пагинация
| Сторона | Параметры запроса | Формат ответа |
|---------|-------------------|---------------|
| **Frontend** (`types.ts:90-99`) | `after?: string`, `limit?: number` | `CursorPage<T>`: `{items: T[], next_cursor?: string \| null}` |
| **Agent Management** (`api.py:116-122`) | `offset: int`, `limit: int` | `{items: T[], total: int}` |
| **Orchestration** (`api.py:190-195`) | `project_id?`, `status?` (query) | Прямой массив `List[RunResponse]` |

### 7.2 WorkflowDefinitionDTO vs Backend
| Поле | Frontend (`types.ts:26-37`) | Backend (orchestration) | Backend (agent-management) |
|------|----------------------------|------------------------|---------------------------|
| `id` | `WorkflowDefinitionId` (string) | Н/Д | Н/Д |
| `name` | string | Н/Д | `AgentDefinition.name` |
| `description` | string? | Н/Д | `AgentDefinition.description` |
| `definition` | `WorkflowDefinition` (nodes/edges) | **НЕТ** | **НЕТ** |
| `is_active` | boolean | Н/Д | **НЕТ** |
| `version` | number (optimistic lock) | Н/Д | `AgentDefinition.version` |
| `created_at` / `updated_at` | ISO string | Н/Д | `AgentDefinition.created_at` / `updated_at` |

### 7.3 AgentDefinitionRef vs AgentDefinitionResponse
| Поле | Frontend (`types.ts:69-73`) | Agent Management (`schemas.py`) |
|------|----------------------------|--------------------------------|
| `id` | string | string |
| `name` | string | string |
| `description` | string? | string? |
| *extra* | — | `system_prompt`, `default_model_profile_id`, `default_tool_policy_id`, `capabilities`, `config_schema`, `version`, `created_at`, `updated_at` |

---

## 8. Рекомендуемые действия (по ADR-101)

1. **P0 — WorkflowDefinition домен:** Реализовать в orchestration-server (новые таблицы `workflow_definitions`, `workflow_versions`, endpoint под `/api/v1/workflows/definitions*`). Это разблокирует frontend live-режим.
2. **P1 — Унификация пагинации:** Ввести `CursorPage` во всех подсистемах (backend-вариант: добавить `after/limit` параметры, вернуть `next_cursor`). Либо сделать gateway-адаптер, преобразующий `offset/total` → `after/next_cursor`.
3. **P1 — Gateway / API aggregation:** Ввести единый вход `/api/v1` (API Gateway или BFF), который проксирует к orchestration-server (runtime) и agent-management (definitions/profiles/policies), нормализуя пагинацию и DTO.
4. **P1 — Frontend→Runtime звено:** Добавить в `HttpAdapter` методы для запуска/мониторинга workflow-run (`launchRun`, `listRuns`, `getRun`, `listRunTasks`).
5. **P2 — Удалить MockAdapter как default:** В `client.ts:50` сменить default на `mock: false` после готовности backend.

---

*Документ подготовлен в рамках TASK-01. Классификация: подтверждённые / предполагаемые / закрытые — см. `01-architecture-audit.md`.*