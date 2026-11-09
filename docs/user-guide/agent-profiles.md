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

### Многовариантные ответы и микроскопические тарифы

Для ограниченных бюджетом Agent Instance провайдерский параметр
`auth_config.parameters.n` обязан равняться `1` (или отсутствовать).
`n > 1` создаёт несколько оплачиваемых ответов, поэтому запрос
запрещается до сетевого вызова. Реально учтённая положительная
оценочная стоимость округляется **вверх** до 0,000001 USD,
чтобы множественные почти бесплатные запросы не терялись
при последующем суммировании расходов.

### Учёт дополнительных полей провайдера и отсутствующего usage

Для бюджетных вызовов `auth_config.parameters` допускает только
ограниченные числовые непубличные параметры генерации
(`n=1`, `temperature`, `top_p`, `presence_penalty`,
`frequency_penalty`, `seed`). `tools`, `functions`,
`response_format` и неизвестные параметры отклоняются:
они могут добавлять скрытые prompt-токены после проверки входа.

HTTP-адаптер различает реально присланные счётчики токенов и
локальную эвристическую оценку `len(text)//4`. Если провайдер не
прислал достоверный `usage`, бюджетный вызов **не освобождает**
резерв; API возвращает ошибку учёта и требует отдельной сверки.
Детерминированный offline mock с явными счётчиками допускается.


## Практический сценарий в Web UI: provider → model → ограниченная policy → profile → editor

1. В **Настройки → Подключения** создать provider (или выбрать `mock` для
   полностью офлайн-приёмки). Сохранение ключа не запускает платный completion.
2. В **Модели** сохранить ModelProfile провайдера.
3. В **Роли агентов** создать отдельную tool-policy с явными
   `fs_read`/`fs_write` путями вида `/srv/maw/workspace/project/**`.
   Этот namespace соответствует `MAW_NATIVE_PROFILE_GATEWAY_ROOT` из
   `deploy/compose/secure/compose.native-profile-snapshot.yml`.
   Если оператор меняет доверенный workspace root, он должен согласовать
   namespace разрешений до snapshot export; браузер не выполняет
   неявную трансляцию путей. Пустые поля
   оставляют соответствующие права закрытыми (*deny-all*).
   UI намеренно **не** выдаёт shell/git/network доступ одной кнопкой.
4. Создать **developer** с именем, system instructions, моделью, политикой,
   max_concurrency. Отдельно создать **reviewer/tester/security** с собственной
   read-only/deny-all политикой; UI отбрасывает для независимых ролей
   tool-policy с `fs_write`, `git`, `shell`, `network`.
   Изменения профиля выполняются с номером версии, на HTTP 409
   требуется обновление данных; кнопка «Копировать» создаёт новый профиль.
5. В **Редактор → Собрать готовый процесс из реальных агентов и контрактов**
   выбрать эти серверные AgentDefinition. Сохранённые
   `default_model_profile_id` и `default_tool_policy_id` подставляются
   в preset автоматически. Если одна из ссылок отсутствует в каталоге,
   создание черновика блокируется; произвольная замена закреплённых
   model/policy через preset недопустима. Отдельные ручные editor API и
   опубликованные графы по-прежнему требуют **серверной** проверки.
6. Сохранить, проверить, опубликовать immutable workflow **отдельно**.
   Создание профиля, policy или черновика **не** запускает worker и
   **не** подтверждает реальные права при runtime dispatch.

**Граница реализации:** ограничение списка policies и выборов в браузере —
удобство и предотвращение случайной ошибки, а не самостоятельный security
enforcement. Реальный native worker использует отдельный операторский
trusted snapshot и пересечение разрешений с gateway allowlist. Изменение
AgentDefinition не обновляет уже запущенную задачу. Нельзя считать
independent QA подписанным только потому, что в редакторе есть узел
`reviewer`; аудит, бюджеты и разрешения должны проверяться на backend.

**Evidence:** `AgentProfilesManager.test.tsx` проверяет создание двух
раздельных ролей, deny-all и конкурентное редактирование; Chromium
`compose-acceptance.spec.ts` проверяет сохранение и восстановление после
reload и селектор редактора. Эти проверки выполняются с mock-моделью
без оплачиваемого запроса к OpenRouter.

## Серверный read-only инвариант для независимых ролей (#254)

Независимые `tester`, `reviewer`, `security` не могут получить
`fs_write`, `git`, `shell` или `network` через ToolPolicy, даже
при прямом вызове REST API в обход UI. Разрешены `fs_read` и deny-all.
Проверка действует при создании и PATCH AgentDefinition (включая смену
роли), при создании AgentInstance с альтернативной policy, и при PATCH
ранее назначенной ToolPolicy (учитываются профили и экземпляры).
Нарушение возвращает HTTP 422 Problem Details, без записи конфигурации.

Для старых записей, обошедших эти правила до обновления, дополнительный
fail-closed барьер действует до provider completion и при operator-only
native snapshot export. Изменение версии ToolPolicy продолжает
инвалидировать уже созданные instance; незаметная эскалация невозможна.

Эта защита **не заменяет** независимую QA-аттестацию и проверку
gateway/worker credentials. Защищённая live-приёмка остаётся обязательной.

### Атомарность назначений ToolPolicy при конкурентных запросах

Контроль read-only прав применяется **в одной транзакции** с записью:
на SQLite запись резервируется через `BEGIN IMMEDIATE` до чтения связей;
на PostgreSQL обновление policy и назначение профиля/instance используют
`SELECT ... FOR UPDATE` соответствующих Policy/AgentDefinition,
а при изменении роли блокируются и связанные instance policies.
Таким образом запись reviewer и одновременное расширение разрешений
не могут обе пройти на устаревшем состоянии.
Два детерминированных теста с конкурирующими SQLite-сессиями проверяют
оба порядка interleaving. Защищённая live-приёмка PostgreSQL остаётся
отдельным release gate.

### Порядок захвата связанных политик

На PostgreSQL при смене роли алгоритм сначала собирает **все** policy IDs
из default и instance overrides, устраняет повторы и захватывает
`SELECT ... FOR UPDATE` строго в глобальном порядке ID. Иначе два
профиля с пересекающимися default/override policies могут образовать
deadlock даже при корректной блокировке каждого отдельного policy.
Рядом с тестами конкурентной записи есть проверка противоположных
default/override назначений. SQLite гарантирует сериализацию
`BEGIN IMMEDIATE`; для production PostgreSQL всё равно требуется
отдельная защищённая acceptance.
