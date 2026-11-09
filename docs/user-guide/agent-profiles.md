# Agent definitions / profiles (developer & operator UI)

`Профили агентов` is an explicit Settings-adjacent screen. It creates and edits a server-owned `agent_definitions` record via versioned agent-management REST, and can create a bounded allowlist `tool_policies` record (empty permissions are deny-all). Model references point to existing `model-profiles`. Its role, stages, skills, max_concurrency and budget_limit fields were present in the SQL model but were not previously exposed by the public API. The new API uses the existing DB columns, storing stages/skills as JSON strings for backward compatibility.

**Security boundary:** these records describe a logical agent. They are not a live registered native worker, and they **do not enforce** LLM expenditure or worker concurrency just by existing. The UI labels them metadata until the execution control-plane applies limits. No provider calls, secret storage or automatic invocation occur. Tool actions must still be authorised by the runtime/gateway and independent QA uses separate credentials. Changes carry optimistic versioning and must not be treated as hot mutation of running attempts.

Remaining for full #254: backend-enforced runtime budgets, live profile→task/worker stage matching, project-scoped profiles, profile archival and independent QA proof. Do not claim #254 closed on CRUD alone.

## Привязка версии при создании Agent Instance (#254)

Agent Management фиксирует версии AgentDefinition, выбранного ModelProfile,
ToolPolicy и Provider в отдельной серверной таблице
`agent_instance_execution_bindings`. Это не пользовательский `runtime_config`:
клиенту запрещено задавать старое зарезервированное поле `_execution_binding_v1`,
и старые JSON-значения никогда не принимаются за доверенное подтверждение. При вызове
`POST /api/v1/completions` с `agent_instance_id` проверяются сохранённые
версии и назначенный model profile. Изменение любой из этих записей приводит к
отказу **до** вызова провайдера, вместо незаметного изменения параметров
существующего экземпляра. После осознанной перенастройки оператор создаёт новый
экземпляр. Старые экземпляры, созданные до привязки версий, для вызовов completion
запрещаются (fail-closed): их нужно создать заново.

Это API-level version fencing, а **не** подтверждение применения профиля,
бюджета или ToolPolicy в native leased worker. Worker и gateway продолжают
опираться на собственную операторскую доверенную конфигурацию и должны быть
проверены в отдельном реальном Compose acceptance перед закрытием #254.

Версии профилей увеличиваются атомарным SQL compare-and-swap (условие на
текущую версию + `version = version + 1`), чтобы два конкурентных обновления
не могли записать разные конфигурации с одинаковой версией. Снятие флага
`is_default` у другого профиля также увеличивает его версию.

**Миграция БД:** новая таблица создаётся существующим `create_all` при
запуске Agent Management или штатной схемной миграцией production PostgreSQL.
Старым экземплярам строки не добавляются автоматически: для повторного
completion их нужно создать заново. Не переносить и не доверять данным
`runtime_config._execution_binding_v1` старых записей.

## Запрет подмены параметров модели в completion API

Когда `/api/v1/completions` вызывается с `agent_instance_id`,
параметры `temperature` и `max_tokens` берутся из выбранного
ModelProfile. Запрос может явно повторить эти значения, но не может
заменить их на отличающиеся или задать отсутствующий в профиле параметр:
отказ происходит до внешнего вызова модели и записи расхода. Режим
интроспекции `/completions` без `agent_instance_id` сохраняет
существующую возможность задавать параметры запроса и не считается
выполнением под закреплённым профилем агента.
