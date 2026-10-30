# EPIC-INT E1 — Аудит текущего состояния подсистем (evidence-first)

> Эпик: `t_e447180c` «Архитектурная интеграция, безопасность и стабилизация Multi-Agent Workflow» (P1).
> Репозиторий: `/mnt/data/multi-agent-workflow`, ветка `main` (базовая), рабочий отчёт на `epic-int/e1-current-state`.
> Роль: Researcher (первая стадия конвейера). Код приложения НЕ изменялся — только аналитические артефакты.
> Метод: статический анализ фактического кода; каждая позиция подтверждена командой и файлом:строкой.
> Дата проверки: 2026-10-09 (MSK). HEAD на момент проверки: `eba4685`.

---

## 0. Сводная таблица «риск → статус → доказательство → влияние»

| # | Риск | Статус | Доказательство (путь:строка) | Влияние |
|---|------|--------|------------------------------|---------|
| 1 | Контракт API frontend рассинхронизирован с фактическими endpoint orchestration-server | **ПОДТВЕРЖДЁН** | `apps/frontend/src/api/httpAdapter.ts:60-127`; `apps/frontend/src/api/types.ts:6-16`; `apps/frontend/src/api/client.ts:14,50`; `services/orchestration-server/orchestration_server/api.py:102-297`; `services/orchestration-server/docs/openapi.json` (paths) | Frontend в «живом» режиме (`mock:false`) не может получить ни один серверный ресурс: ни один вызываемый путь не существует в orchestration-server. Работает только `MockAdapter` по умолчанию. |
| 2 | Не подтверждён сквозной ЖЦ workflow между подсистемами | **ПОДТВЕРЖДЁН** (фрагментарно: серверный ЖЦ полный, но UI→HTTP цепочка оборвана) | Серверный ЖЦ: `services/orchestration-server/orchestration_server/engine.py:184-247,250-338,443-533,594-674`; структура данных: `models.py:93-182`. Отсутствие связи UI→server: `apps/frontend/src/App.tsx:12-29`; `apps/frontend/src/main.tsx`; `apps/frontend/src/config` отсутствует; `createApiClient` мок по умолчанию `client.ts:50`; нет вызовов `/workflows/runs` в src (`grep` — 0). Нет cross-subsystem integration/e2e (`grep` — 0). | Редактор может собрать и сохранить схему в память/мок, но цепочка «создание→сохранение→запуск→назначение→выполнение→проверка→обновление→UI» не подтверждена нигде и фактически разорвана между frontend и orchestration-server. |
| 3 | Permissive tool policy (нет deny-by-default / точка enforcement) | **ПОДТВЕРЖДЁН** (в коде declare deny-by-default, но есть `DEFAULT_PERMISSIVE_POLICY`, и точка enforcement не подключена к исполнению) | Отрицание по умолчанию: `services/agent-management/agent_management/tool_policy.py:61-77,80-85`; но разрешающий подкласс: `tool_policy.py:105-112` (DEFAULT_PERMISSIVE_POLICY) — нигде не импортируется (`grep` — только определение). Enforcement не вызывается: `services.py:241` создаёт `ToolPolicyEngine`, но `enforce`/`allow` нигде не используются в runtime (`grep` — 0 вызовов вне модуля). | Политика существует как библиотека, но не привязана к фактическому исполнению агента (completion path `services.py:592-665` не вызывает enforce). Практический эффект политики не обеспечен. |
| 4 | Границы ответственности за состояния между сервисами | **ПОДТВЕРЖДЁН** (дублирующие модели состояний) | Состояние агента/runs/tasks: `services/orchestration-server/orchestration_server/models.py:80-182` (Agent.status, WorkflowRun.status, Task.status, TaskAttempt.status, SagaEvent). Дублирующая модель agent в agent-management: `services/agent-management/agent_management/models.py:122-169` (AgentDefinition, AgentInstance.status). Оба сервиса имеют свою версию «агента». | Двойной владелец состояния агента (Agent в orchestration vs AgentInstance в agent-management) → риск расхождения статусов и отсутствия единого источника истины на уровне исполнения. |
| 5 | Отсутствует единый CI quality gate | **ПОДТВЕРЖДЁН** | `.github/` отсутствует (нет workflows). Корневого Makefile нет (`find` — только `apps/frontend/Makefile`). `services/quality-gates/` — автономный фреймворк (`,pyproject.toml`, `quality_gates/main.py`), не подключён ни к какому CI-конфигу. | Нет автоматического качества на уровне репозитория: `make check` существует только для frontend (`apps/frontend/Makefile:26`), для Python-подсистем единого затвора нет. |
| 6 | Нет подтверждённого воспроизводимого локального запуска | **ПОДТВЕРЖДЁН** (частично) | Docker-compose/Dockerfile отсутствуют (`find` — 0). Инструкции по частям есть: `services/orchestration-server/README.md` (`uvicorn`), `apps/frontend/README.md` ({install,typecheck,lint,test,schema,build}, `apps/frontend/Makefile`). agent-management README отсутствует. | Воспроизводимый запуск всей системы одной командой не документирован; конфигурация разрознена по подсистемам. |
| 7 | Сгенерированные тестовые артефакты попали в Git | **ПОДТВЕРЖДЁН** | `services/runtime-hardening/.coverage`; `services/runtime-hardening/reports/coverage.xml`; `services/runtime-hardening/reports/junit.xml`; `services/runtime-hardening/reports/agent-runtime-p8.3-src.tar.gz` (все в `git ls-files`) | В индексе репозитория лежат бинарные/сгенерированные артефакты (coverage, junit, tar.gz), загрязняющие версионную историю. |
| 8 | Документация с признаками переноса из других проектов | **ПОДТВЕРЖДЁН** | `services/quality-gates/README.md:1-2` («Harbor Transfer Portal agent platform»); `tools/agent-orchestration/harbor_transfer_portal/*` (kanban_tools.py, agent_workspace.py); `services/runtime-hardening/runtime/__init__.py:1` («Harbor-Transfer-Portal agent sandbox»); `docs/...` (несколько файлов, `grep -rl Harbor`) | Чужая терминология и структуры (Harbor-Transfer-Portal) остались в коде и доке, что мешает навигации и подтверждает перенос без полной вычистки. |

---

## 1. Риск 1 — Контракт API frontend vs orchestration-server (ПОДТВЕРЖДЁН)

### Фактический контракт frontend

Верхнеуровневая базовая ссылка frontend — `/api/v1` (`apps/frontend/src/api/client.ts:14`).

Методы `HttpAdapter` (`apps/frontend/src/api/httpAdapter.ts:60-127`) вызывают следующие пути относительно `baseUrl`:

- `GET    /workflows/definitions` (listWorkflows, `httpAdapter.ts:60-67`)
- `GET    /workflows/definitions/{id}` (getWorkflow, `:69-71`)
- `POST   /workflows/definitions` (createWorkflow, `:73-75`)
- `PUT    /workflows/definitions/{id}` (updateWorkflow, `:77-82`)
- `GET    /workflows/definitions/{id}/versions` (listVersions, `:84-94`)
- `POST   /workflows/definitions/{id}/versions` (saveVersion, `:96-105`)
- `GET    /agents/definitions` (listAgentDefinitions, `:107-114`)
- `GET    /model-profiles` (listModelProfiles, `:116-123`)
- `GET    /tool-policies` (listToolPolicies, `:125-127`)

Декларированный контракт в `apps/frontend/src/api/types.ts:6-16` повторяет этот набор.

### Фактические endpoint orchestration-server (`api.py`)

Все маршруты зарегистрированы на корне FastAPI-приложения без префикса (`services/orchestration-server/orchestration_server/api.py:102-297`):
`/health`, `/projects`, `/workspaces`, `/contracts`, `/agents/register`, `/agents`, `/workflows/runs`, `/workflows/runs/{run_id}`, `/workflows/runs/{run_id}/tasks`, `/tasks/{task_id}`, `/tasks/{task_id}/attempts`, `/tasks/{task_id}/claim`, `/tasks/{task_id}/attempts/{attempt_id}/submit`, `/tasks/{task_id}/attempts/{attempt_id}/fail`, `/tasks/{task_id}/block`, `/workflows/tick`, `/admin/recover`.

OpenAPI (`services/orchestration-server/docs/openapi.json`, `servers: []`, без `/api/v1`) содержит ровно эти 17 путей. Автокросс-проверка api.py ↔ openapi: расхождений нет (все 21 route-декоратора присутствуют в спецификации).

### Итог сопоставления

- **Нет пересечения.** Ни один из 9 путей, вызываемых `HttpAdapter`, не существует в orchestration-server.
- Путь `/workflows/definitions` отсутствует в backend вообще (`grep -rn "workflows/definitions"` по services/orchestration-server/agent-management/runtime-hardening/quality-gates/tools — 0 попаданий).
- Контрактные справочные пути `/agents/definitions`, `/model-profiles`, `/tool-policies` существуют **в подсистеме agent-management** (`services/agent-management/agent_management/api.py:112,142,169`), а не в orchestration-server; и формат пагинации там `{items,total}` на offset/limit, а frontend ждёт `CursorPage{items,next_cursor}` с `after/limit` (`apps/frontend/src/api/types.ts:90-99`, `apps/frontend/src/api/httpAdapter.ts:164-170`).

**Вывод:** рассинхронизация полная на уровне путей и частичная на уровне формата ответа. Работоспособен только `MockAdapter` (значение по умолчанию `createApiClient`, `client.ts:50`).

---

## 2. Риск 2 — Сквозной ЖЦ workflow (ПОДТВЕРЖДЁН, цепочка разорвана между frontend и server)

### Что реализовано на сервере (полный durable ЖЦ в orchestration-server)

- `engine.py:184-247` — `launch_run`: создаёт `WorkflowRun(status='running')` + задачи `Task(status='pending')`, валидирует контракты, пишет saga-события.
- `engine.py:250-338` — `claim_task`: атомарный `UPDATE ... WHERE status='pending'`, контроль занятости агента, создаёт `TaskAttempt(status='running')`.
- `engine.py:443-533` — `submit`: контрактная проверка (JSON Schema), переход attempt→`completed`, task→`completed`, ретраи при `verification_failed`.
- `engine.py:535-570` — `fail_attempt`; `engine.py:572-591` — `block_task`.
- `engine.py:647-674` — `tick` (открытие retry-окон); `engine.py:594-645` — `recover` (durability после рестарта).
- Модель данных: `models.py:93-182` (`WorkflowRun`, `Task`, `TaskAttempt`, `SagaEvent`).

Т.е. **серверная часть** скоуп-цепочки «назначение→выполнение→проверка→обновление состояния» реализована и покрыта тестами (`tests/test_*.py`).

### Что отсутствует / разорвано

- **Редактор не вызывает orchestration-server.** `apps/frontend/src/App.tsx:12-29` и `apps/frontend/src/main.tsx` рендерят только редактор (`NodePalette/WorkflowCanvas/PropertyPanel`). Никакого кода запуска ранна (`workflows/runs`, `launchRun`, `claimTask`) в `apps/frontend/src` и `apps/frontend/e2e` нет (`grep` — 0 совпадений).
- **Подключение mock↔HTTP не сделано в приложении.** `createApiClient` по умолчанию возвращает `MockAdapter` (`client.ts:50`); HTTP-адаптер задействуется только если явно передать `mock:false`.
- **Промежуточного звена «сохранение схемы → запуск ранна» нет в orchestration-server:** нет `WorkflowDefinition`/`workflow_definitions` таблиц/моделей (`grep WorkflowDefinition orchestration-server` — 0); нет персистентного хранилища схем, на которое опирается frontend-контракт.
- **Нет сквозных тестов** frontend↔orchestration (e2e/интеграция отсутствуют).

**Вывод:** «сквозной» ЖЦ как единый подтверждённый поток между подсистемами отсутствует. Реализованы отдельные изолированные фрагменты (редактор и durable-движок), но связка между ними не построена и не проверена. Это блокирует любой сквозной сценарий.

---

## 3. Риск 3 — Permissive tool policy (ПОДТВЕРЖДЁН: deny-by-default в библиотеке, но enforcement не подключён и есть разрешающий default)

- Механика проверки отрицает по умолчанию: `agent_management/tool_policy.py:61-77` (`allow` возвращает `False` для неизвестного action и для пустого списка разрешений), `:80-85` (`enforce` бросает `ToolPolicyDenied`).
- **Однако** определён `DEFAULT_PERMISSIVE_POLICY` (`tool_policy.py:105-112`): `fs_read: ["**"]`, `fs_write: ["**"]`, `git: ["*"]`, `shell: ["*"]`, `network: ["*"]`. Этот константный объект нигде не импортируется/не используется (`grep -rn DEFAULT_PERMISSIVE_POLICY` — только строка определения).
- **Точка enforcement отсутствует в runtime.** `ToolPolicyEngine` инстанцируется в `services.py:241` сервисом, но вызовы `enforce`/`allow` нигде за пределами самого модуля `tool_policy.py` не встречаются (`grep .enforce(/.allow(` — 0). Скоуп исполнения `run_completion` (`services.py:592-665`) не производит ни одной проверки политики перед вызовом LLM-провайдера.
- Политика связана с сущностями декларативно (`tool_policy_id` на `AgentDefinition`/`AgentInstance`, `models.py:137,169`), но не воздействует на выполнение.

**Вывод:** декларативный deny-by-default существует в библиотеке, но не действует на фактическое исполнение; разрешающий дефолт присутствует как мёртвый код. Эффективного механизма запрета инструментов на уровне выполнения нет.

---

## 4. Риск 4 — Границы ответственности за состояния (ПОДТВЕРЖДЁН: дублирующие модели «агента»)

| Состояние | Где хранится | Модель |
|-----------|--------------|--------|
| Проекты, Workspace, Contract | orchestration-server | `models.py:36-77` |
| Агент (исполняемый) | orchestration-server | `Agent.status` `models.py:80-90` |
| WorkflowRun / Task / TaskAttempt | orchestration-server | `models.py:93-170` |
| Saga-журнал (durability) | orchestration-server | `SagaEvent` `models.py:173-182` |
| Provider / ModelProfile / ToolPolicy | agent-management | `models.py:44-119` |
| AgentDefinition / AgentInstance | agent-management | `AgentInstance.status` `models.py:122-169` |

- **Дублирование:** `Agent` (orchestration, статусы `idle/busy`) и `AgentInstance`/`AgentDefinition` (agent-management, статусы `pending/running/...`) — две независимые сущности «агента» в разных БД/сервисах. Единого источника истины об исполняемом агенте нет.
- Разделение контуров не задокументировано как явный контракт владения; в `docs/domain-architecture.json` заявлено «explicit ownership boundaries» и перечень владельцев (ProjectService, AgentService/Orchestration, WorkflowService/Orchestration), однако фактический код расходится с декларацией (например, orchestration-server не имеет WorkflowDefinition/WorkflowService, а владение «workflow definition» в коде отсутствует).

**Вывод:** границы ответственности размыты и содержат как минимум одну пару дублирующих владельцев (состояние агента). Риск подтверждён.

---

## 5. Риск 5 — Отсутствие единого CI quality gate (ПОДТВЕРЖДЁН)

- Каталог `.github/` отсутствует (нет `.github/workflows`).
- Корневой `Makefile` отсутствует; существует только `apps/frontend/Makefile` (цель `check` = install+typecheck+lint+test+schema+build, `apps/frontend/Makefile:26`).
- Подсистема `services/quality-gates/` автономна: `quality_gates/pipeline.py`, `quality_gates/main.py`, собственный `pyproject.toml`. Ни один CI-конфиг или корневой скрипт её не запускает (её описывает свой `README.md`).
- Ни в одной подсистеме Python-уровня нет общего командного затвора (`make check` уровня repo/CI).

**Вывод:** единого автоматического quality gate на уровне репозитория нет; затвор есть только локально для frontend.

---

## 6. Риск 6 — Воспроизводимый локальный запуск (ПОДТВЕРЖДЁН частично)

- Docker-Compose и Dockerfile отсутствуют (`find` по репо — 0).
- Документированы точечные запуски:
  - orchestration-server: `services/orchestration-server/README.md` (`pip install -e ".[dev]"`; `uvicorn orchestration_server.main:app --port 8000`; `ORCH_DATABASE_URL` для PostgreSQL).
  - frontend: `apps/frontend/README.md` + `apps/frontend/Makefile` (`make check`).
- agent-management README отсутствует (в `services/agent-management/` нет `*.md`).
- Единый «поднять всю систему одной командой» не описан.

**Вывод:** воспроизводимого комплексного запуска (все подсистемы совместно) не документировано; тривиальный запуск отдельных частей возможен, но не агрегирован.

---

## 7. Риск 7 — Сгенерированные тестовые артефакты в Git (ПОДТВЕРЖДЁН)

`git ls-files` (фактически в индексе):

```
services/runtime-hardening/.coverage
services/runtime-hardening/reports/agent-runtime-p8.3-src.tar.gz   (~115 КБ)
services/runtime-hardening/reports/coverage.xml
services/runtime-hardening/reports/junit.xml
```

- `.gitignore` игнорирует только `coverage/` (каталог), `dist/`, `node_modules/`, `__pycache__/`, `.venv/`, `.qg-verify/` и т.п., но НЕ покрывает `.coverage`, `reports/*.xml` и `reports/*.tar.gz` — поэтому они попали в индекс.
- Указанные артефакты реально существуют в рабочем дереве и в индексе (проверено `git ls-files`).

**Вывод:** сгенерированные тестовые артефакты (coverage, junit, бинарный tar.gz) закоммичены в репозиторий.

---

## 8. Риск 8 — Документация с признаками переноса из других проектов (ПОДТВЕРЖДЁН)

Найдено упоминание чужого проекта **Harbor Transfer Portal**:
- `services/quality-gates/README.md:1-2` — «...quality-gate pipeline for the Harbor Transfer Portal agent platform...».
- `tools/agent-orchestration/harbor_transfer_portal/__init__.py` — пакет целиком назван `harbor_transfer_portal`.
- `tools/agent-orchestration/harbor_transfer_portal/kanban_tools.py` — docstring «Kanban integration helpers for Harbor-Transfer-Portal multi-agent orchestration».
- `tools/agent-orchestration/harbor_transfer_portal/agent_workspace.py`.
- `services/runtime-hardening/runtime/__init__.py:1` — «Hardened runtime components for the Harbor-Transfer-Portal agent sandbox».
- Плюс ряд `docs/runtime-hardening/*` и `docs/research/*` (см. `grep -rl Harbor`).

**Вывод:** чужой терминологический пласт (Harbor-Transfer-Portal) остался в коде и документации — признак переноса артефактов без полной локализации/вычистки.

---

## 9. Карта фактических REST-endpoint orchestration-server

Источник: `services/orchestration-server/orchestration_server/api.py` (маршруты на корне, без `/api/v1`) и `services/orchestration-server/docs/openapi.json` (17 путей; `servers: []`; версия `0.1.0`).

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/health` | Liveness-status (`ApiStatus`, `api.py:102-104`) |
| POST | `/projects` | Создание проекта (`api.py:107-115`) |
| GET | `/projects` | Список проектов (`api.py:117-119`) |
| POST | `/workspaces` | Создание workspace (`api.py:121-131`) |
| GET | `/workspaces` | Список workspaces (фильтр `project_id`) (`api.py:133-137`) |
| POST | `/contracts` | Создание контракта (JSON Schema) (`api.py:140-150`) |
| GET | `/contracts` | Список контрактов (`api.py:152-154`) |
| POST | `/agents/register` | Регистрация агента (`api.py:157-165`) |
| GET | `/agents` | Список агентов (`api.py:167-169`) |
| POST | `/workflows/runs` | Запуск workflow-run (создание задач) (`api.py:172-188`) |
| GET | `/workflows/runs` | Список раннов (фильтры project_id, status) (`api.py:190-195`) |
| GET | `/workflows/runs/{run_id}` | Детали ранна (`api.py:197-204`) |
| GET | `/workflows/runs/{run_id}/tasks` | Задачи ранна (`api.py:206-212`) |
| GET | `/tasks/{task_id}` | Детали задачи (`api.py:215-222`) |
| GET | `/tasks/{task_id}/attempts` | Попытки задачи (`api.py:224-230`) |
| POST | `/tasks/{task_id}/claim` | Захват задачи агентом (concurrency-safe) (`api.py:232-240`) |
| POST | `/tasks/{task_id}/attempts/{attempt_id}/submit` | Сдача результата + контрактная проверка (`api.py:242-256`) |
| POST | `/tasks/{task_id}/attempts/{attempt_id}/fail` | Отказ попытки (`api.py:258-272`) |
| POST | `/tasks/{task_id}/block` | Блокировка задачи (`api.py:274-287`) |
| POST | `/workflows/tick` | Открытие retry-окон (`api.py:290-292`) |
| POST | `/admin/recover` | Восстановление после рестарта (`api.py:294-297`) |

---

## 10. Ключевые файлы и их назначение

| Путь | Назначение |
|------|-----------|
| `services/orchestration-server/orchestration_server/api.py` | FastAPI-приложение, endpoint orchestration-server (корневой namespace) |
| `services/orchestration-server/orchestration_server/engine.py` | Durable-движок: state-machine, контракт-проверка, retry, recovery |
| `services/orchestration-server/orchestration_server/models.py` | SQLAlchemy модели (projects…saga_events) |
| `services/orchestration-server/orchestration_server/schemas.py` | Pydantic DTO и контракты |
| `services/orchestration-server/docs/openapi.json` | Генерируемая OpenAPI-спецификация (17 путей) |
| `apps/frontend/src/api/httpAdapter.ts` | HTTP-адаптер (вызывает `/api/v1/...`, paths НЕ совпадают с orchestration-server) |
| `apps/frontend/src/api/types.ts` | Типизированный контракт frontend (`CursorPage`, `/api/v1`) |
| `apps/frontend/src/api/client.ts` | Фабрика клиента; по умолчанию `MockAdapter` |
| `apps/frontend/src/api/mockAdapter.ts` | In-memory мок для офлайн-разработки |
| `services/agent-management/agent_management/api.py` | FastAPI agent-management с префиксом `/api/v1` (источник для `/agents/definitions`, `/model-profiles`, `/tool-policies`) |
| `services/agent-management/agent_management/services.py` | Сервисы (ToolPolicyService, AgentDefinitionService, run_completion) |
| `services/agent-management/agent_management/tool_policy.py` | Политика инструментов; `DEFAULT_PERMISSIVE_POLICY` (мёртвый код) |
| `apps/frontend/Makefile` | `make check` — локальный затвор frontend |
| `services/quality-gates/` | Автономный фреймворк гейтов (не подключён к CI) |
| `services/runtime-hardening/reports/*` | Закоммиченные артефакты (coverage.xml, junit.xml, .tar.gz) |
| `tools/agent-orchestration/harbor_transfer_portal/*` | Остатки чужого проекта (Harbor-Transfer-Portal) |

---

## 11. Команды проверки (все выполнялись в `/mnt/data/multi-agent-workflow`, ветка `epic-int/e1-current-state`)

- `git branch -a` → `* main` + `remotes/origin/main`; создана рабочая ветка `epic-int/e1-current-state`.
- `python3 -c "...openapi.json paths..."` → 17 путей; `servers: []`; нет `/api/v1`.
- Autokross-check роутов `api.py` ↔ `openapi.json` → все маршруты присутствуют (расхождений нет).
- `grep -rn "workflows/definitions"` по backend → 0 попаданий (эндпоинт не существует на сервере).
- `grep -n router/@router services/agent-management/api.py` → `APIRouter(prefix="/api/v1")` + `/model-profiles`, `/tool-policies`, `/agents/definitions`.
- `grep -rn "DEFAULT_PERMISSIVE_POLICY"` → только строка определения `tool_policy.py:106`.
- `grep .enforce(/.allow(` → только `tool_policy.py:81` (внутренний вызов); runtime-вызовов нет.
- `grep -rn "workflows/runs\|launchRun\|claimTask\|submit" apps/frontend/src apps/frontend/e2e` → 0.
- `find . -name 'Makefile'` → только `apps/frontend/Makefile`; `ls .github` → нет.
- `find . -name 'docker-compose*' -o -name 'Dockerfile*'` → 0.
- `git ls-files` → `services/runtime-hardening/.coverage`, `reports/coverage.xml`, `reports/junit.xml`, `reports/agent-runtime-p8.3-src.tar.gz`.
- `grep -rl "Harbor\|Transfer Portal"` → services/quality-gates/README.md, tools/agent-orchestration/harbor_transfer_portal/*, services/runtime-hardening/runtime/__init__.py, docs/*.

*Часть команд выполнена через `search_files`-аналоги (ripgrep); тексты подтверждающих строк указаны в разделах выше.*

---

## 12. Принятые решения/декомпозиция (передано от эпика `t_e447180c`)

Наследуемые решения конвейера: API `/api/v1` (единый источник — OpenAPI orchestration-server, ADR-101), deny-by-default tool policy (ADR-103), независимая верификация, рабочие ветки `epic-int/eN-*`, local-only без push в `main`. Накопленные выводы этого аудита выше должны быть учтены при планировании E2+ (в первую очередь: полная пересинхронизация frontend-контракта с orchestration-server, подключение enforcement tool policy, устранение дублирующего владельца состояния агента, единый CI-gate, очистка чужой терминологии).