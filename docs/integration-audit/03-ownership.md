# EPIC-INT E2 — Владение состояниями и контрактами (TASK-01)

> Архитектурное решение ADR-102. Таблица «состояние → владелец → хранилище → API».

---

## 1. Матрица владения (State → Owner → Store → API)

| Домен состояния | Сущность (таблица) | Владелец (Service) | Хранилище (БД) | API (Endpoint) | Подсистема |
|-----------------|-------------------|-------------------|----------------|----------------|------------|
| **Проекты / Workspaces / Environments / Teams** | `projects`, `workspaces`, `environments`, `teams` | `ProjectService` / `WorkspaceService` | PostgreSQL (orchestration) | `/projects`, `/workspaces` | Orchestration Server |
| **Контракты (JSON Schema)** | `contracts` | `WorkflowService` / `TaskService` | PostgreSQL (orchestration) | `/contracts` | Orchestration Server |
| **Workflow Definitions (design-time)** | `workflow_definitions`, `workflow_versions` | **WorkflowService** (NEW) | PostgreSQL (orchestration) | `/api/v1/workflows/definitions*` | **Orchestration Server (добавить)** |
| **Workflow Runs (runtime)** | `workflow_runs` | `WorkflowService` / `OrchestrationEngine` | PostgreSQL (orchestration) | `/workflows/runs` | Orchestration Server |
| **Tasks / Attempts** | `tasks`, `task_attempts` | `TaskService` / `OrchestrationEngine` | PostgreSQL (orchestration) | `/tasks/*`, `/workflows/runs/*/tasks` | Orchestration Server |
| **Saga / Audit Events** | `saga_events` | `OrchestrationEngine` (internal) | PostgreSQL (orchestration) | `/admin/recover`, `/workflows/tick` | Orchestration Server |
| **Agents (runtime status)** | `agents` | `OrchestrationEngine` | PostgreSQL (orchestration) | `/agents/register`, `/agents` | Orchestration Server |
| **Agent Definitions (config)** | `agent_definitions` | `AgentDefinitionService` | PostgreSQL (agent-management) | `/api/v1/agents/definitions` | Agent Management |
| **Agent Instances (execution)** | `agent_instances` | `AgentInstanceService` | PostgreSQL (agent-management) | `/api/v1/agents/instances` | Agent Management |
| **Providers** | `providers` | `ProviderService` | PostgreSQL (agent-management) | `/api/v1/providers` | Agent Management |
| **Model Profiles** | `model_profiles` | `ModelProfileService` | PostgreSQL (agent-management) | `/api/v1/model-profiles` | Agent Management |
| **Tool Policies** | `tool_policies` | `ToolPolicyService` | PostgreSQL (agent-management) | `/api/v1/tool-policies` | Agent Management |
| **Token Usage** | `token_usage` | `TokenUsageService` | PostgreSQL (agent-management) | `/api/v1/usage/*` | Agent Management |
| **Runtime: Containers / Isolation** | (in-memory + cgroups v2) | `RuntimeService` | cgroups v2 FS + workspace FS | `/agents`, `/workspaces` | Runtime Hardening |
| **Runtime: Resource Limits** | (cgroups v2) | `ResourceManager` | cgroups v2 FS | `/agents/{id}/limits`, `/usage`, `/pressure` | Runtime Hardening |
| **Runtime: Workspaces / Snapshots** | (FS overlay) | `WorkspaceManager` | FS (`workspace_root`, `durable_root`, `snapshots_root`) | `/workspaces`, `/workspaces/*/snapshot` | Runtime Hardening |

---

## 2. Конфликты владения (решаемые ADR-102)

| Конфликт | Сущность А (Owner) | Сущность Б (Owner) | Решение |
|----------|-------------------|-------------------|---------|
| **Agent Runtime Status** | `Agent` (orchestration: `idle/busy/terminated`) | `AgentInstance` (agent-mgmt: `pending/running/completed/failed/terminated`) | **Orchestration Server = единственный владелец runtime-статуса исполнения.** `Agent` в orchestration отражает доступность агента для захвата задач (`idle`/`busy`). `AgentInstance` в agent-management — это **конфигурация/определение** экземпляра (какую модель, какую политику, какой system_prompt). При запуске run: orchestration создаёт/обновляет `Agent` (status→`busy`), agent-management `AgentInstance` переходит в `running`. При завершении: orchestration `Agent`→`idle`, agent-management `AgentInstance`→`completed/failed`. Синхронизация через event (SagaEvent) или прямой вызов. |
| **Workflow Definition** | Frontend ожидает CRUD в orchestration | **Отсутствует** в orchestration | Добавить домен в orchestration-server (ADR-101). Agent-management не владеет workflow definitions. |
| **Tool Policy Enforcement** | Объявлен в agent-management (`ToolPolicy`, `ToolPolicyEngine`) | Не enforce'ится в runtime | **ADR-103:** Точка enforcement — в Runtime Hardening (container runtime / workspace manager) ИЛИ в `AgentManagementService.run_completion` перед вызовом LLM. Owner остаётся agent-management (CRUD), enforcement делегирован runtime. |
| **Agent Registration** | `AgentRegister` в orchestration (`/agents/register`) | `AgentInstance` в agent-management | Разделить: **orchestration** регистрирует *исполнителя* (identity + status для scheduling). **Agent-management** управляет *конфигурацией* (definition, model, policy). При старте агента: agent-management создаёт `AgentInstance` → оркестрация регистрирует `Agent` с тем же ID (или маппинг). |

---

## 3. Контракты между подсистемами

### 3.1 Orchestration Server → Agent Management (вызовы)

| Вызов | Когда | Данные | Результат |
|-------|-------|--------|-----------|
| `GET /api/v1/agents/definitions/{id}` | При создании Task с `agent_definition_id` | AgentDefinition (system_prompt, default_model_profile_id, default_tool_policy_id) | Используется для построения AgentSpec в Runtime |
| `GET /api/v1/model-profiles/{id}` | При запуске AgentInstance | ModelProfile (model_id, parameters, context_window) | Передаётся в Runtime / Provider |
| `GET /api/v1/tool-policies/{id}` | При запуске AgentInstance | ToolPolicy (permissions JSON) | Передаётся в Runtime для enforcement |
| `POST /api/v1/completions` | При выполнении задачи агентом (LLM call) | `provider_id`, `model_profile_id`, `agent_instance_id`, `messages`, `temperature`, `max_tokens` | LLM response + usage recording |

### 3.2 Orchestration Server → Runtime Hardening (вызовы)

| Вызов | Когда | Данные | Результат |
|-------|-------|--------|-----------|
| `POST /agents` | При `claim_task` (агент начинает работу) | `AgentSpec`: isolationTier, image, resourceClass, workspace, seccompProfile, env | Созданный контейнер + cgroup + workspace |
| `POST /agents/{id}/pause` | При `block_task` или прерывании | — | Контейнер на паузе |
| `POST /agents/{id}/stop` | При завершении/ошибке задачи | graceSeconds | Контейнер остановлен, ресурсы освобождены |
| `GET /agents/{id}/status` | Для мониторинга / recovery | — | `AgentStatus` (state, usage, pressure, health) |
| `POST /workspaces` | При создании Task/Run | `WorkspaceSpec` | Изолированное FS окружение |

### 3.3 Agent Management → Runtime Hardening

| Вызов | Когда | Данные |
|-------|-------|--------|
| `POST /agents` | При `POST /api/v1/agents/instances` (create instance) | `AgentSpec` из `AgentDefinition` + `ModelProfile` + `ToolPolicy` |

---

## 4. Таблица состояний (для реализации синхронизации)

| Событие | Orchestration `Agent` | Agent Mgmt `AgentInstance` | Runtime `AgentState` | Действие |
|---------|----------------------|---------------------------|---------------------|----------|
| Агент зарегистрирован | `idle` | — | — | Orchestration: `register_agent` |
| AgentInstance создан | — | `pending` | — | Agent Mgmt: `create_agent_instance` |
| Run запущен, задача назначена | `busy` | `running` | `CREATED` → `RUNNING` | Orchestration: `claim_task` → Runtime: `create_agent` |
| Агент начал выполнение | `busy` | `running` | `RUNNING` | Runtime: health probes |
| Задача завершена успешно | `idle` | `completed` | `TERMINATED` | Orchestration: `submit` → Runtime: `stop_agent` |
| Задача провалена (retry) | `idle` (переход к следующему) | `running` (остаётся) | `RUNNING` | Orchestration: `fail_attempt` → retry |
| Задача провалена (max attempts) | `idle` | `failed` | `TERMINATED` | Orchestration: `fail_attempt` → Runtime: `stop_agent` |
| Агент блокирован | `idle` | `running` | `PAUSED` | Orchestration: `block_task` → Runtime: `pause_agent` |
| Сервер рестарт (recovery) | `idle` (бывшие `busy`→`idle`) | unchanged | `TERMINATED` (orphaned) | Orchestration: `recover()` → Runtime: cleanup |

---

## 5. Принципы владения (для разработчиков)

1. **Единственный владелец на домен состояния.** Никаких дублирующих таблиц с одинаковой семантикой.
2. **Ссылаться по ID, не дублировать данные.** Orchestration хранит `agent_definition_id` (FK на agent-management), не копирует `system_prompt`.
3. **Событийная синхронизация.** Изменения состояния в одном сервисе → событие (SagaEvent / outbox) → обновление в другом. Не использовать распределённые транзакции.
4. **API-контракты версионируются.** `/api/v1` — единый префикс. Breaking changes → `/api/v2`.
5. **Enforcement в точке исполнения.** ToolPolicy проверяется там, где выполняется действие (Runtime container / workspace FS), а не в API gateway.

---

*Документ подготовлен в рамках TASK-01. Основа для ADR-102.*