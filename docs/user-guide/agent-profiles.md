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

## Доверенные инструкции профиля в Agent Management API

При `POST /api/v1/completions` с `agent_instance_id` сервер подставляет
сохранённый `AgentDefinition.system_prompt` первым сообщением роли
`system`. Клиент может передать только ограниченную последовательность
`user`/`assistant` с полями `role` и `content`; поддельные системные,
developer, tool-роли или дополнительные служебные поля отклоняются до
создания провайдера и записи usage. Если оператор меняет инструкции
профиля, старая привязка версии перестаёт работать и нужен новый instance.

Это применение инструкций **в Agent Management completion API**, не
доказательство передачи тех же инструкций в native worker: у него остаётся
собственный доверенный prompt из приватной конфигурации.

## Серверный лимит числа запущенных экземпляров

Переход Agent Instance в `running` теперь атомарно проверяет
`AgentDefinition.max_concurrency` для всех экземпляров одного логического
профиля. На PostgreSQL блокируется строка определения агента; на SQLite
используется `BEGIN IMMEDIATE` до первого чтения, чтобы одновременно
запущенные транзакции не заняли один свободный слот. После перехода в
`completed`, `failed` или `terminated` слот освобождается. Эта проверка
сохраняет версию AgentDefinition и применима после перезапуска сервиса.

Лимит касается **running Agent Instance в Agent Management API**, а не
количества внешних native leased worker: для последнего необходимо отдельное
доверенное распределённое admission control в orchestration.

## Резервирование оценочного бюджета completion API

Если у AgentDefinition задан `budget_limit` (сумма в USD), Agent Management
перед каждым *instance-bound* completion вычисляет консервативный резерв из
`ModelProfile.context_window`, `max_tokens` и настроенных USD-ставок за
1000 входных/выходных токенов. При ненулевых ставках отсутствие безопасного
предела токенов ведёт к отказу до вызова провайдера. Доступный предел
рассчитывается из суммарных сохранённых `TokenUsage.est_cost` по всем
экземплярам профиля и всех открытых резервов `agent_budget_reservations`.
SQLite-писатели сериализуются через `BEGIN IMMEDIATE`, PostgreSQL через
блокировку строки AgentDefinition. После успешного ответа запись токенов
и удаление резерва сохраняются одной SQL-транзакцией.

В случае ошибки/неопределённого исхода провайдера или падения процесса резерв
**не освобождается автоматически**, поскольку внешний вызов мог уже стоить
денег. Перед повторным запуском оператор обязан сверить такие резервы по
внешнему учёту и отдельно согласовать корректировку БД; ни TTL, ни
автоматического списания неподтверждённого вызова нет.

Это **лимит по оценочной стоимости в Agent Management completion API**.
Он не является гарантией фактического инвойса провайдера или доказательством
лимитов native leased worker, не блокирует отдельно авторизованные
интроспекционные запросы *без* Agent Instance и не заменяет авторитетный
per-attempt учёт у оркестратора.

### Уточнение безопасной оценки входа и конкурентного учёта

Сервер отказывает, если UTF-8 представление запроса (включая роль,
содержимое, доверенные инструкции и запас служебной обвязки)
превышает указанное `context_window`: считать произвольную
величину из metadata гарантированным ограничителем входа нельзя.
Отрицательные и нечисловые цены за входные и выходные токены
отклоняются **по отдельности** при создании, обновлении и
резервировании. Успешное погашение резерва использует ту же
блокировку AgentDefinition, что и резервирование: это исключает
гонку между вставкой TokenUsage и удалением резерва в PostgreSQL
READ COMMITTED. Оценка байтов **не заменяет** сертифицированный
tokenizer провайдера и не является гарантией реального инвойса.
