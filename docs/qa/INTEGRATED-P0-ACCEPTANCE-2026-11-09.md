# Интеграционная приёмка первого запуска и native SDLC (P0, 2026-11-09)

**Источник:** PR #310, единая интеграционная ветка `feat/integrated-p0-user-journey`.
Содержит взаимосвязанные изменения исходных PR #301, #305, #306,
#307, #308. Проверки на отдельных source-PR **не принимаются** как доказательство
этого объединённого дерева.

## Входной пользовательский сценарий (реальный Compose, без платного LLM)

1. Собрать и запустить локальный dev Compose, дождаться healthcheck всех
   зависимых сервисов и проверить same-origin `/api/v1` proxy.
2. Создать проект и workspace в первом запуске. При отказе API
   agent-management список проектов должен оставаться доступным, без ложного
   результата успешного подключения.
3. Создать синтетического provider и ModelProfile через **Настройки**.
   Проверить HTTP 201/GET и сохранность после reload; ни один
   `/completions` не должен быть вызван. Проверить отрицательный POST 5xx и
   независимый сбой последующего GET, не показывая сохранённое как неуспешное.
4. Создать ограниченные ToolPolicy и отдельные developer/reviewer AgentDefinition.
   Проверить versioned PATCH/409 и запрет выбора write/shell/git/network policy
   для независимого reviewer. Проверить, что редактор подставляет закреплённые
   model/policy и блокирует отсутствующие ссылки.
5. В редакторе сохранить/publish immutable workflow и пройти серверный
   preflight. Дефектный контракт/graph не должен создавать run.
6. Выполнить подтверждённый POST опубликованной версии сначала из редактора,
   затем через **Запуски**. Проверить server run ID, задачи, reload.
   После успешного POST сбой независимого GET не должен отображаться как
   ошибка создания или вызывать автоматический повтор. Неизвестный результат
   POST требует сверки истории и идемпотентного ключа, не повторного платного
   вызова наугад.
7. Проверить журнал событий: по умолчанию существующий dev-mode; затем только
   для disposable CI явно включить **оба** ticket-флага, получить одноразовые
   WS/SSE билеты, событие, replay denial и запрет `api_key` в URL.
   При ошибке защищённого режима не переходить на long-lived URL credentials.

Сценарий: `apps/frontend/e2e/compose-acceptance.spec.ts` плюс локальный
`.github/workflows/quality-gate.yml`, backend pytest и frontend Vitest.
Работа с существующей базой пользователя, реальный OpenRouter ключ и расходы
**не входят** в этот сценарий.

## Offline native worker и независимое решение о выпуске

`tests/native_agent_e2e` использует настоящий HTTP leased worker, Git worktree,
SQL fencing, trusted gateway, серверный Contract Gate, отдельные QA subprocesses
и signed QA receipts. Модель **scripted**, а не живой OpenRouter. Положительный
семистадийный тест подтверждает checkpoint/restart и отдельный операторский
release approval.

Отрицательный тест провала tester обязан доказать сохранённое evidence именно
для правильной пары attempt/Git SHA и код завершения subprocess `1`.
Следующая зависимая задача остаётся pending; живой worker не делает второй
tool/model вызов; QA receipt выдавать нельзя, release approver получает 409,
worker/QA/admin — 403. После рестарта control plane блокировка сохраняется.

## Отдельные блокеры для настоящего production signoff

- **Не разрешено:** автоматический платный OpenRouter вызов без согласования
  с оператором, реальным credential и заранее заданным бюджетом.
- **Не доказано:** защищённый live Compose с OpenRouter → инструмент → Git
  artifact → Contract Gate → tester/reviewer/security → операторское разрешение
  релиза, включая отказ/переподключение и изменение прав во время попытки.
- **Не доказано:** что исправлен HTTP 500 именно в уже установленной базе
  пользователя; нужны резервная копия, redacted server logs, schema audit
  без модификации данных и проверка после deployment.
- **Нужно:** независимое review объединённого diff и security/QA approval,
  управление ключами, HA ticket-store и журналами proxy, rollback без
  long-lived credentials в URL. `main` и production не изменять до release gate.
- Исходные issue #11, #254, #256, #209 и #8 остаются OPEN до фактической
  приёмки их полных критериев; интеграция PR не означает их закрытие.

## Обязательный технический checkpoint

Все обязательные checks должны быть **SUCCESS на точном SHA интеграционного
PR**: `CI`, `Quality Gate` с Compose/Chromium, `Native agent cross-service E2E`,
`GitFlow Policy`, image/security и документационные проверки. Нельзя
использовать зелёный старый SHA, отложенный/пропущенный job либо результат
из отдельного PR как доказательство принятия интеграции.


## Дополнительный native preflight: пространство путей ToolPolicy

Для запуска snapshot-backed native worker должны одновременно совпадать
сохранённые `fs_read`/`fs_write` шаблоны из Agent Management и операторский
`MAW_NATIVE_PROFILE_GATEWAY_ROOT`. Например, защищённый Compose использует
`/srv/maw/workspace`; допустима политика
`/srv/maw/workspace/src/**`, но **не** `/workspace/src/**` и не
`/srv/maw/workspace/../private/**`.

Неприменимые к gateway пути вызывают **отказ при preflight**, а не
позднее ложное обещание доступа к файловым инструментам. Пустые списки
оставляют политику deny-all. Проверка не выдаёт никаких дополнительных
прав: trusted gateway отдельно проверяет lease, path containment и
allowlist во время каждой операции. Проверяется тестами
`services/orchestration-server/tests/test_native_worker_wiring.py`
и экспортом реального Agent Management SQLite-профиля в
`tests/native_agent_e2e/test_trusted_runner_wiring.py`.

## Режим частичного отказа каталога tool-policy

Если сервер подтвердил POST новой tool-policy, но параллельная загрузка
каталога завершилась ошибкой, сохранённая политика остаётся доступной для
создания AgentDefinition. Частичные GET-страницы и ранее неизвестные политики
**не** считаются проверенными: после сбоя каталог скрыт, а для сохранения
можно выбрать только policy ID из успешного POST текущего сеанса.
Регрессионные сценарии находятся в `AgentProfilesManager.test.tsx`;
подтверждение роли, прав и выполнения остаётся за серверным preflight.

## Backend security acceptance: независимые QA-агенты

Отдельная обязательная регрессия для #254, выполняется **без платной LLM**:

- Прямой POST AgentDefinition с ролью tester/reviewer/security и разрешением
  `fs_write`, `git`, `shell` либо `network` → HTTP 422.
- PATCH существующей роли developer→reviewer с привязанной привилегированной
  политикой, либо PATCH назначения такой политики существующему reviewer →
  HTTP 422, без изменения версии и записи.
- POST AgentInstance с policy override к независимой роли, а также
  расширение ToolPolicy, используемой профилем или instance → HTTP 422.
- Разрешены read-only (`fs_read`) и deny-all политики. Старые опасные
  записи отклоняются на completion и operator-only native snapshot export.
- В тестах проверяются реальный SQLite, HTTP Problem Details, отсутствие
  записи при отказе и отсутствие провайдерского вызова/usage.

Подтверждение из этих тестов **не** является независимым QA receipt или
разрешением выпускать релиз: signed tester/reviewer/security и операторский
release approval проверяются в защищённом live сценарии отдельно.

### Конкурентная безопасность QA ToolPolicy

Негативные тесты обязаны проверить оба порядка одновременных запросов:
(1) создание reviewer после прочтения safe-policy vs её расширение;
(2) расширение policy после проверки отсутствия ссылок vs создание reviewer.
В обоих случаях допускается только один успех; конечная БД не содержит
independent QA с разрешениями на side effects.

### Deadlock regression PostgreSQL

Для двух независимых дефиниций с перекрёстными default/override политиками
P и Q одновременная миграция обеих ролей в independent QA не должна
создавать цикл блокировок. Policy IDs блокируются **в одном полном
отсортированном порядке**, до проверки разрешений. Offline unit-тест
проверяет порядок и итоговый результат; production PostgreSQL acceptance
остаётся отдельным условием release.

## #256: запуск → read-only QA → scoped recovery

В RunsSection по выбранному серверному запуску выводятся число задач,
завершённых/blocked/failed и попыток, следующий шаг, а также отдельная
QA-сводка из `getTaskQaStatus`. Сводка принимает `verified` только при
совпадении task_id, наличии SHA, signer и receipt IDs всех
tester/reviewer/security gates. Любая ошибка чтения, отсутствующее поле
или `disabled` → unknown/disabled без ложной готовности. Чтение
ограничено 25 задачами, батчами по пять. Выпуск всегда требует
отдельного разрешения человека и не выводится из этих чисел.

Из запуска Recovery показывает карантин **только данного run_id**,
а из карточки задачи передаётся одновременно run_id + task_id.
Карточка автоматически выделяется, только если сервер включил её
в quarantine. Смена запуска скрывает старые данные и форму аттестации,
response от старой задачи не может появиться под новой. Экран не
имеет claim/retry/requeue. Негативные тесты проверяют отсутствие чужих
задач, корректную deep-link навигацию, отказ при отсутствии в quarantine
и неизменность operator-only boundary. Это не заменяет защищённую
live-приёмку #256/#11.

## #256: backend run-scoped quarantine under a saturated queue

Ранее браузер выбирал записи из общей очереди после SQL LIMIT, поэтому
карантин выбранного run_id мог ошибочно выглядеть пустым. Теперь
`GET /admin/recovery-quarantine?run_id=...` с тем же admin RBAC
применяет `Task.workflow_run_id` **до LIMIT**. Проверка карантинного
SagaEvent реализована через `EXISTS`: повторные events не вытесняют
задачи из первых записей. HttpAdapter кодирует `run_id` и
запрашивает до 200 записей; при достижении лимита UI предупреждает
о неполном обзоре. Старый общий административный список сохранён.
Реальный backend SQLite + HTTP тест содержит 105 старых карантинных
задач другого run ID, повтор события и один новый карантин.
Новый run обнаруживается независимо от переполнения общей очереди;
запрещённое `limit=201` даёт 422. Reconciliation/ledger/RBAC
по-прежнему обязательны и не обходятся изменением run_id.

## #256: Индекс карантинного события на существующих БД

Для коррелированного `EXISTS` добавлен составной индекс
`ix_saga_events_aggregate_event` по
(`aggregate_type`, `aggregate_id`, `event_type`).
Он объявлен в metadata для новых схем и устанавливается
идемпотентным `CREATE INDEX IF NOT EXISTS` при `create_all`
и через `python -m orchestration_server.migrations --apply`
для уже существующих SQLite/PostgreSQL таблиц. Это добавление индекса,
не перенос строк, не удаление таблиц и не переразметка worker state.
Оператору с большой production БД следует сделать backup и выбрать
согласованное окно миграции: создание индекса может временно блокировать
запись. Dry-run CLI показывает `missing_indexes`.
Regression test создаёт старую БД без индекса, сохраняет audit event,
применяет upgrade дважды и проверяет `EXPLAIN QUERY PLAN`, использование
составного индекса и неизменность записи.

## #256: PostgreSQL parallel startup migration safety

На существующей PostgreSQL БД `CREATE INDEX IF NOT EXISTS` не
сериализует два конкурентных создания одного отсутствующего индекса.
Перед `Base.metadata.create_all` и DDL `create_all` теперь
берёт `pg_advisory_xact_lock(786422, 20261109)` в той же транзакции.
Все экземпляры orchestration-server и CLI `ensure_schema`
захватывают одинаковую advisory-блокировку до проверки физической
схемы, после commit/rollback PostgreSQL освобождает её автоматически.
SQLite использует штатную транзакцию и idempotent `IF NOT EXISTS`.
Добавлен отдельный CI job `PostgreSQL concurrent schema/index migration`
с одноразовым PostgreSQL 16: тест удаляет индекс из существующей БД,
параллельно запускает две независимые async engine миграции,
проверяет восстановление индекса и сохранность audit event. Это
интеграционная CI-проверка PostgreSQL, **не** разрешение мигрировать
production БД без бэкапа/maintenance window/operator approval.

## #254: бюджет исполнителя — durable ledger и безопасное отображение

Новый read-only `GET /api/v1/agents/definitions/{id}/budget` (READ RBAC)
собирает из одного согласованного SQL snapshot уже учтённые
`TokenUsage.est_cost` всех AgentInstance конкретного определения,
незакрытые `AgentBudgetReservation` и число резервов.
Деньги считаются в integer micro-USD с консервативным округлением:
лимит округляется вниз, расходы вверх; остаток не становится
отрицательным. Отсутствие USD-лимита — `not_configured`, нулевой
остаток — `exhausted`. Это **расчётные**, а не подтверждённые суммы
платёжного счёта провайдера. Неизвестные/потерянные API ответы
не показываются как нулевые расходы или доступность.

И редактор профилей в «Настройки → Роли агентов», и отдельная
страница «Профили агентов» теперь различают USD budget для
обычных server-side Agent Management completions и natively
стримящий worker, у которого **нет общего budget enforcement**.
Существующий экспорт native-профиля с USD-лимитом продолжает
отказывать в исполнении. UI показывает spent / held / remaining,
ошибку проверки, неизменяемый контекст профиля и явное обновление.
Тесты проверяют реальную SQLite DB + ASGI + новый engine после
restart, scope другого профиля, нулевой бюджет и stale response в UI;
Compose Chromium создаёт mock-профиль с бюджетом и подтверждает
сохранение отчёта после reload без вызова `/completions`.
#254 остаётся OPEN до независимого native streaming spending cap
и защищённой live-acceptance; это не разрешение платных запросов.
