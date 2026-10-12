# EPIC-INT E2 — Порядок зависимостей задач (TASK-01)

> Архитектурное решение: порядок реализации TASK-02 и последующих задач. Основан на матрице владения (`03-ownership.md`), несовместимостях API (`02-api-incompatibilities.md`) и аудите (`01-architecture-audit.md`).

---

## 1. Граф зависимостей (Mermaid)

```mermaid
flowchart TD
  %% Foundation
  F1[F-01: PostgreSQL schema + migrations<br/>(workflow_definitions, workflow_versions)]
  F2[F-02: Orchestration Server: WorkflowDefinition CRUD API<br/>(/api/v1/workflows/definitions*)]
  F3[F-03: Unified pagination (CursorPage) across all subsystems]
  F4[F-04: API Gateway / BFF (/api/v1 proxy)<br/>orchestration + agent-management + runtime]

  %% Integration
  I1[I-01: Frontend HttpAdapter → launchRun / listRuns / getRun]
  I2[I-02: Orchestration → Agent Mgmt sync (AgentDefinition, ModelProfile, ToolPolicy)]
  I3[I-03: Orchestration → Runtime Hardening integration<br/>(create_agent, stop_agent, pause_agent, workspaces)]
  I4[I-04: Tool Policy enforcement point (Runtime + run_completion)]

  %% Quality / Operations
  Q1[Q-01: Root Makefile + .github/workflows/ci.yml<br/>(unified quality gate)]
  Q2[Q-02: Docker Compose для полного локального стека]
  Q3[Q-03: Cleanup generated artifacts from Git (.coverage, reports/*)]
  Q4[Q-04: Multi-Agent Workflow Platform terminology purge]

  %% TASK-02 scope (minimal integration)
  T2[TASK-02: End-to-End Workflow Integration<br/>(Editor → Run → Monitor)]

  %% Dependencies
  F1 --> F2
  F2 --> I1
  F2 --> I2
  F3 --> F2
  F3 --> I1
  F4 --> I1
  F4 --> I2
  F4 --> I3
  I2 --> I3
  I3 --> I4
  I1 --> T2
  I3 --> T2
  I4 --> T2

  Q1 -. "parallel" .-> F1
  Q2 -. "parallel" .-> F1
  Q3 -. "independent" .-> F1
  Q4 -. "independent" .-> F1

  style T2 fill:#ffeb3b,stroke:#fbc02d
  style F1 fill:#c8e6c9,stroke:#388e3c
  style F2 fill:#c8e6c9,stroke:#388e3c
  style F3 fill:#c8e6c9,stroke:#388e3c
  style F4 fill:#c8e6c9,stroke:#388e3c
```

---

## 2. Детальный порядок задач

### Фаза 0: Фундамент (блокирующие, можно параллелить)

| ID | Задача | Описание | Оценка | Блокирует |
|----|--------|----------|--------|-----------|
| **F-01** | **PostgreSQL migrations: WorkflowDefinition + WorkflowVersion** | Новые таблицы в orchestration-server: `workflow_definitions` (id, project_id, name, description, definition JSONB, current_version_id, is_active, version, timestamps), `workflow_versions` (id, workflow_definition_id, version_number, definition_snapshot JSONB, changelog, created_by, created_at, is_deprecated). FK, индексы, GIN на JSONB. | 2-3 дн | F-02, I-01 |
| **F-02** | **Orchestration Server: WorkflowDefinition CRUD API** | Реализовать в `orchestration_server/api.py` под префиксом `/api/v1` (ADR-101): `GET/POST /api/v1/workflows/definitions`, `GET/PUT /api/v1/workflows/definitions/{id}`, `GET/POST /api/v1/workflows/definitions/{id}/versions`. DTO в `schemas.py`, логика в `engine.py` / новом `WorkflowService`. Вернуть `CursorPage` (после F-03). | 3-4 дн | I-01, TASK-02 |
| **F-03** | **Унификация пагинации (CursorPage)** | Во всех подсистемах (orchestration, agent-management, runtime) добавить поддержку `after/limit` → `CursorPage{items, next_cursor}`. Вариант А: изменить каждый сервис. Вариант Б (рекомендуется): API Gateway (F-04) делает трансформацию `offset/total` → `next_cursor`. | 2-3 дн | F-02, I-01, I-02 |
| **F-04** | **API Gateway / BFF (единый `/api/v1`)** | Ввести легкий прокси (nginx / FastAPI / Traefik) на входе, который: а) маршрутизирует `/api/v1/workflows/*` → orchestration-server, б) `/api/v1/agents/*`, `/api/v1/model-profiles`, `/api/v1/tool-policies` → agent-management, в) `/api/v1/runtime/*` → runtime-hardening, г) нормализует пагинацию, ошибки (RFC 9457), CORS. | 3-4 дн | I-01, I-02, I-03 |

### Фаза 1: Интеграция (core TASK-02)

| ID | Задача | Описание | Оценка | Блокирует |
|----|--------|----------|--------|-----------|
| **I-01** | **Frontend HttpAdapter: runtime методы** | Добавить в `httpAdapter.ts` / `types.ts`: `launchRun(request)`, `listRuns(params)`, `getRun(run_id)`, `listRunTasks(run_id)`. Вызовы идут через Gateway (`/api/v1`). UI: кнопка «Run» в PropertyPanel/Toolbar, панель Runs (новая вкладка/модалка). | 2-3 дн | TASK-02 |
| **I-02** | **Orchestration ↔ Agent Mgmt синхронизация** | В `OrchestrationEngine.launch_run` / `claim_task`: резолвить `agent_definition_id` → вызвать Agent Mgmt `/api/v1/agents/definitions/{id}`, `/model-profiles/{id}`, `/tool-policies/{id}` для построения `AgentSpec`. Кэшировать TTL 5 мин. Обработка ошибок (404 → Task blocked). | 2-3 дн | I-03 |
| **I-03** | **Orchestration → Runtime Hardening интеграция** | В `OrchestrationEngine.claim_task` / `submit` / `fail_attempt` / `block_task`: вызывать Runtime API (`POST /agents`, `POST /agents/{id}/stop`, `POST /agents/{id}/pause`, `POST /workspaces`). Передавать `AgentSpec` из AgentDefinition + ModelProfile + ToolPolicy. Обработка таймаутов, ретраев, ошибок контейнера. | 4-5 дн | I-04, TASK-02 |
| **I-04** | **Tool Policy enforcement (ADR-103)** | Точка enforcement: в `RuntimeService.create_agent` (container runtime) — передать `ToolPolicy.permissions` в seccomp/profile / cgroup / network policy. В `AgentManagementService.run_completion` — вызвать `ToolPolicyEngine.enforce` для каждого tool call перед LLM. Удалить/депрекейтить `DEFAULT_PERMISSIVE_POLICY`. | 3-4 дн | TASK-02 |

### Фаза 2: Качество и операции (параллельно с Фазой 1)

| ID | Задача | Описание | Оценка |
|----|--------|----------|--------|
| **Q-01** | **Root Makefile + GitHub Actions CI** | Корневой `Makefile` с целями `check`, `test`, `lint`, `typecheck` для всех подсистем. `.github/workflows/ci.yml`: matrix для frontend (Node), orchestration (Python), agent-management (Python), runtime (Python). Quality Gates подключить как job. | 2-3 дн |
| **Q-02** | **Docker Compose (full stack)** | `docker-compose.yml` в корне: postgres, orchestration-server, agent-management, runtime-hardening, frontend (dev), gateway. Healthchecks, depends_on, env файлы. Документация в `README.md`. | 2-3 дн |
| **Q-03** | **Очистка Git от артефактов** | `git rm --cached` для `runtime-hardening/.coverage`, `reports/*.xml`, `reports/*.tar.gz`. Добавить в `.gitignore`: `*.coverage`, `reports/`, `*.tar.gz`. | 0.5 дн |
| **Q-04** | **Multi-Agent Workflow Platform purge** | `grep -rl Multi-Agent Workflow Platform` → заменить на проект-нейтральные термины в: `quality-gates/README.md`, `tools/agent-orchestration/agent_orchestration/*`, `runtime-hardening/runtime/__init__.py`, `docs/**`. Переименовать пакет `agent_orchestration` → `agent_orchestration` (или удалить если не используется). | 1-2 дн |

---

## 3. Минимальный набор для TASK-02 (End-to-End Workflow)

> **TASK-02 acceptance:** Пользователь создаёт workflow в редакторе → нажимает «Run» → видит запущенный Run с задачами → задачи исполняются агентами → результаты верифицируются → Run завершается.

**Обязательные зависимости (critical path):**
```
F-01 → F-02 → I-01
            ↓
         I-02 → I-03 → I-04
            ↓          ↓
           TASK-02 ←───┘
```

**Можно отложить до после TASK-02:**
- F-04 (Gateway) — можно временно хардкодить базы в frontend/env
- Q-01, Q-02, Q-03, Q-04 — качество/операции, не блокируют функционал

**Рекомендуемый порядок исполнения (критический путь):**
1. F-01 (PostgreSQL миграции)
2. F-02 (WorkflowDefinition API в orchestration)
3. F-03 (CursorPage пагинация — минимум в orchestration)
4. I-01 (Frontend: launchRun + Runs UI)
5. I-02 (Orchestration → Agent Mgmt sync)
6. I-03 (Orchestration → Runtime integration)
7. I-04 (Tool Policy enforcement)
8. **TASK-02 верificado**

---

## 4. Риски порядка

| Риск | Описание | Митигация |
|------|----------|-----------|
| F-01/F-02 затянутся | Сложность миграций + новых моделей | Начать с миграций сразу; использовать feature flag для API |
| I-03 сложность Runtime | Runtime Hardening API нестабилен / отличается | Сначала мок-интеграция (testcontainers), потом реальная |
| F-04 (Gateway) нужен раньше | Без него frontend не знает куда стучаться | Временный `VITE_API_BASE` в frontend `.env`, прокси через Vite dev server |
| I-04 (Tool Policy) блокирует агенты | deny-by-default ломает существующие агенты | Постепенный rollout: флаг `enforce_tool_policy=false` по умолчанию, включать после тестов |

---

## 5. Критерии готовности к TASK-02

- [ ] `GET/POST /api/v1/workflows/definitions` работают (CRUD + версии)
- [ ] Frontend может создать WorkflowDefinition и получить `id`
- [ ] `POST /api/v1/workflows/runs` запускает Run из WorkflowDefinition
- [ ] Orchestration резолвит AgentDefinition/ModelProfile/ToolPolicy из Agent Mgmt
- [ ] Orchestration создаёт контейнер в Runtime для задачи
- [ ] Tool Policy enforce работает (хотя бы в run_completion)
- [ ] `GET /api/v1/workflows/runs/{id}/tasks` возвращает задачи с статусами
- [ ] UI показывает Run, Tasks, логи/статус в реальном времени

---

*Документ подготовлен в рамках TASK-01. Зависимости выражают архитектурные ограничения, не управленческие предпочтения.*