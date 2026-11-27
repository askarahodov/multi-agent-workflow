# Реестр контрактов: baseline и план покрытия

Дата: 25.11.2026. Baseline `6e47938df1f94e783f266c8210de5c92e8c20058`. Статус: проект для review; инвентаризация, не завершённая миграция схем. #337, #346. Схемы остаются у владеющих подсистем; реестр указывает на них, не создаёт вторую копию.

## Текущие источники

| ID | Контракт и владелец | Канонический источник / ограничения |
|---|---|---|
| CT-01 | Workflow definition / Orchestration | services/orchestration-server/orchestration_server/schemas.py (WorkflowDefinitionDTO, WorkflowVersionDTO, PublishedRunCreate); apps/frontend/src/workflow/workflow.schema.json — формат редактора, сверять с сервером |
| CT-02 | Task / Orchestration | schemas.py: TaskSpec, RunCreate, TaskResponse; depends_on — индексы предшествующих задач, не произвольный DAG |
| CT-03 | Attempt/result / Orchestration | schemas.py: ClaimAttemptResponse, SubmitRequest, FailRequest, BlockRequest; output — объект, проверяется контрактом, не самоутверждённый PASS |
| CT-04 | Git artifact / Orchestration | GitArtifactReport, GitEvidenceResponse; provenance worker_reported, SHA 40–64 hex, changed_paths ограничены out/ |
| CT-05 | Recovery/lease / Orchestration | AttemptLeaseRenewRequest/Response, ReconciliationRequest/Response, RecoveryLedgerReport; operator evidence metadata, не произвольный переход |
| CT-06 | Release approval / Orchestration | RunReleaseApprovalStatus и RunReleaseApproval в models.py, engine.approve_release; не deploy receipt |
| CT-07 | Profile/model/tool policy / Agent management | services/agent-management/agent_management/schemas.py: AgentDefinition*, ModelProfile*, ToolPolicy*, AgentInstance*, AgentBudgetStatusResponse |
| CT-08 | Native tool / Agent management | native_tool_dispatch.py, tool_policy.py, trusted gateway и tool_ledger.py; проверить wire contract и scope |
| CT-09 | QA attestation / Shared + QA | packages/shared/qa_attestation.py; quality_gates/models.py: GateRunGitScope, EvidenceItem, ReleaseCandidate; отдельный signer |
| CT-10 | Runtime quota / Runtime hardening | services/runtime-hardening/config/resource-quota.schema.json; также копии в hardening/config и docs/runtime-hardening/schemas — определить canonical producer и drift |
| CT-11 | Runtime events/API / Runtime hardening | docs/runtime-hardening/api/agent-runtime-openapi.yaml, lifecycle-events-asyncapi.yaml; сопоставить с real runtime |
| CT-12 | Orchestration REST / Orchestration | services/orchestration-server/docs/openapi.json и actual API/schemas.py; сохранённый OpenAPI 0.1.0, не считать полным без diff |
| CT-13 | Error / каждый API owner | Orchestration ProblemDetail, agent-management/errors.py, quality-gates/errors.py; требуется согласовать общий envelope без breaking changes |
| CT-14 | Budget / Agent management | AgentBudgetReservation, TokenUsage, AgentBudgetStatusResponse; corporate aggregate budget и reservation protocol уточнить #330 |
| CT-15 | GitFlow / dev tooling | gitflow-policy.schema.json + AGENT_GITFLOW_RULES.md; не runtime policy |

## Требуемое развитие (не внедрённые схемы)

| Контракт | Gap / проверка | Зависимость |
|---|---|---|
| Handoff / delegation | Typed bounded child tasks, requirement IDs, dependencies, role eligibility, provenance; не позволять агенту объявлять state | #325 #339 |
| Tenant identity / policy | Trusted organization/project/environment scopes, policy version, actor and capability, separate from untrusted payload | #323 #327 |
| Skill/context | Версия, owner, tool requirements, inputs/outputs, source provenance | #329 #344 |
| Integration connector | Inbound event identity/dedup, outbound operation key, cursor/reconciliation, external PR/CI SHA | #326 |
| Evidence/artifact/approval | Candidate SHA, digest, independent identity, freshness/revocation, scope; audit | #327 |
| Workflow/profile binding | Immutable published version + profile/policy/contract snapshot; reject stale references | #325 #339 |
| Events / errors | Versioned envelope, correlation, safe error codes, no secret-bearing payload | #331 #346 |

## Примеры существующих DTO (не новый API)

TaskSpec ссылается на более ранний индекс в списке:

```json
{"title":"Проверить требования","depends_on":[0],"input_data":{}}
```

SubmitRequest принимает объект output и необязательное Git evidence; пример ниже — синтетический, не подтверждённый коммит:

```json
{"output":{"summary":"Пример"},"git_artifact":{"commit_sha":"0000000000000000000000000000000000000000","changed_paths":["out/report.md"]}}
```

Негативные примеры: output строкой вместо объекта; дубли changed_paths; путь out/../secret; короткий SHA; ссылка depends_on на более позднюю задачу. Отказ на соответствующей schema или engine boundary; эти примеры не запускались как tests в текущей сессии.

## Нормы развития

- Каждый canonical owner ведёт version, schema/API, примеры и tests; остальные используют ссылки или генерируемые артефакты.
- Scope и identity берутся из доверенного контекста, не из заявления модели. Схема проверяет форму, policy проверяет полномочия, evidence подтверждает результат.
- Reject malformed payload, replay, stale SHA, несовместимую версию и неожиданные поля в security-critical протоколах согласно явной версии; расширяемые API требуют documented compatibility policy.
- Проверки producer/consumer, JSON Schema fixtures, OpenAPI diff, negative cases, migration и rollback. В #346 определить поддерживаемые версии, deprecation и mixed-version rollout.
- Не менять действующий wire format ради единообразия без ADR, migration и согласования потребителей.

## Осталось

Проверить актуальный API/OpenAPI diff, выбрать canonical quota schema, согласовать owners, разработать недостающие схемы после #322/#336, запустить реальные contract tests и CI; статус partial. Технические имена и машинные форматы сохраняются, объяснения на русском.

## Проверяемая инвентаризация и обнаруженный дрейф

Машиночитаемый индекс: `docs/architecture/contract-registry.json`. 15 групп, существующие источники и связанные тесты, незакрытые ограничения. `tests/test_contract_registry.py` проверяет ссылки, уникальность идентификаторов и известные различия зеркал; добавлен в действующий root pytest job. Связанный тест не означает полное покрытие соответствующего контракта.

На baseline выявлены три различия копий: $id resource-quota в runtime содержит legacy harbor-transfer-portal, в docs — multi-agent-workflow; OpenAPI/AsyncAPI отличаются contact.name. Других различий по сверке строк в YAML и по JSON-полям quota не найдено. Не менять идентификатор схемы без ADR и миграции потребителей. Тест фиксирует именно эти исключения, не игнорируя остальные изменения. Для устранения исключений обновить тест вместе с согласованным изменением. Существующий `services/orchestration-server/tests/test_openapi.py` проверяет валидность generated OpenAPI и отдельные операции на drift; это не гарантия полного равенства всех конфигураций.

Открытые задачи нового протокола перечислены выше. Этот PR не объявляет их реализованными и не изменяет production wire formats.


## Границы producer/consumer и drift (26.11.2026)

В машинном индексе для всех 15 групп зафиксированы наблюдаемый producer, consumers, исполняемый источник и статус authority. Это техническая карта, не согласование CODEOWNERS. CT-13 оставлен с явным `owner_decision_required`: общего error envelope ещё нет. Для runtime quota исполняемый loader `runtime/config.py` использует `ResourceQuotaConfig.model_validate` из `runtime/models.py`, а не читает JSON Schema; выбор canonical URI зеркал по-прежнему требует ADR и тестов потребителей. Для Runtime API исполняемый источник — `runtime/api.py`; совпадение двух YAML не гарантирует соответствие фактическому API.

На baseline подтверждён конкретный дрейф CT-01/03/04/12: в committed OpenAPI отсутствуют TaskSpec.depends_on, SubmitRequest.git_artifact, GitArtifactReport, GitEvidenceResponse и git-evidence routes. Добавлены positive/negative DTO-тесты и bounded generated-vs-committed regression в существующем orchestration pytest. При расхождении проверка намеренно падает с точной JSON-проекцией реального app.openapi(), которую необходимо перенести в committed OpenAPI после проверки. Не придумывать generated schema и не игнорировать расхождения; полное сравнение остальных маршрутов остаётся отдельной частью #337/#346. Структурный тест индекса также проверяет producer/consumers и явную unresolved authority.


Исправление 26.11.2026: проекции реального `app.openapi()` из двух независимых CI jobs ([CI](https://github.com/askarahodov/multi-agent-workflow/actions/runs/45790596407/job/139808335818), [Quality Gate](https://github.com/askarahodov/multi-agent-workflow/actions/runs/45790596351/job/139808326501)) совпали полностью. Четыре generated schemas и два generated paths перенесены в committed OpenAPI без изменения API runtime. Сохранена строгая регрессия equality; ожидается повторный CI на новом SHA, не PASS по старому запуску. Остальной OpenAPI требует отдельной сверки, полный schema drift не считается устранённым. Исправлена негативная fixture реестра: отсутствующий source добавляется к действующему authority, чтобы тест проверял именно отсутствие файла, а не более ранний отказ authority guard.


## Проверка исполняемых границ CT-10 и CT-11

CT-10: добавлена проверка существующего YAML-примера и минимальной синтетической конфигурации через реальный `load_quota_config`, Draft 2020-12 и повторную сериализацию с alias `class`. Восемь негативных структурных сценариев должны отклоняться и схемой, и loader. Три семантических сценария (high > max, несовпадающий swapMax, неизвестный class) отклоняются runtime, хотя текущая JSON Schema их допускает. Не использовать JSON Schema как единственный security gate. Три наблюдаемых расхождения в обратную сторону (неуказанная версия, неизвестная версия, числовая строка) выделены явно; тест фиксирует их как **незакрытый compatibility gap**, а не принятую политику. Потребуется решение владельца по версии и строгим типам без неожиданной поломки существующих конфигов (#346).

CT-11: проверка реального `GET /openapi.json` runtime API через TestClient сравнивает все HTTP path/method из опубликованного YAML с generated routes; нормализуется только snake_case/camelCase имени path parameter. Ожидаемый известный runtime-only путь `GET /metrics` указан отдельно, другие расхождения должны блокировать CI. Это проверка поверхности HTTP, не полного wire schema или AsyncAPI. Тесты auth/WS связаны в индексе, их покрытие не означает полную приёмку протокола. Никаких изменений production API, существующих схем или ослабления проверок; CI на новом SHA ещё не подтверждён.


## Полный drift default HTTP OpenAPI

На exact baseline `d3802d9e11b295835fbda7340609fe6a44cdaa10` статически сопоставлены декораторы HTTP router и опубликованный OpenAPI: отсутствуют 22 операции (11 операций в двух вариантах URL — без prefix и с /api/v1), включая published workflow preflight/run, SSE events, QA attestation, release approval, recovery quarantine, tool ledger, reconciliation и ready-tasks. Это инвентаризация расхождений, не сгенерированная спецификация.

Добавлена строгая проверка полного default HTTP OpenAPI на фактическом `build_app(Settings(...)).openapi()` с явным /api/v1 и выключенным optional stream-ticket API. Проверяются все paths, schemas и остальные поля документа без исключений; сохранённые точечные регрессии остаются. При drift тест печатает точные JSON-операции OPENAPI_DRIFT_JSON из generated spec и завершает CI ошибкой; тест не изменяет файл. Применять только полученные из CI generated данные для того же candidate SHA, проверить все references и повторить CI. До восстановления полного совпадения CT-12 не принят. Optional ticket API и WebSocket требуют отдельных контрактных проверок; OpenAPI HTTP их не заменяет. Production runtime не меняется.


## Восстановление default HTTP OpenAPI по двум CI runs (27.11.2026)

На exact candidate `041ba55a2d768706bdb92d63d5bc73609715e310` два независимых CI jobs [Quality Gate](https://github.com/askarahodov/multi-agent-workflow/actions/runs/45979543409/job/140439633278) и [CI](https://github.com/askarahodov/multi-agent-workflow/actions/runs/45979543714/job/140439634102) вывели 31 идентичную JSON-операцию: 13 секций schemas и 18 paths. Единственный failed test в каждом backend job — новый полный drift guard (662/660 остальных тестов passed, 1/2 skipped). Все 31 изменения применены без ручного изменения схем. Число путей 46 → 64, операций 60 → 84, схем 35 → 42; 365 ссылок проверены на разрешимость внутри документа, operationId уникальны. Тест полного равенства остаётся строгим и должен пройти на новом SHA. Runtime не изменён. Полный локальный make check NOT_RUN; независимое review и фактический повторный CI обязательны. Optional stream-ticket и WebSocket, согласование owners и отсутствующие корпоративные контракты остаются за пределами этой проверки.


## Потоковые контракты CT-11 и CT-12

Default HTTP OpenAPI прошёл полный CI (7/7) на `34e03ed4df7902652be2b672971b67aa6b72a44e`. Для opt-in stream tickets проверяется реальное generated OpenAPI с выключенным/включённым флагом: только два alias POST, строгий request transport=sse/websocket, response DTO и статусы, отсутствие изменений прочих routes/schemas. Источник — исполняемый router, не вторая копия спецификации. Existing HTTP/security integration tests сохраняются; это не разрешение включить feature flag.

SSE и WebSocket оркестратора читают один saga journal. Новый тест сравнивает реальные ответы, одинаковые поля/id/payload, run scope и resume после первого id в обоих транспортах. SSE frame имеет integer cursor и JSON data, WS добавляет type=run_event; heartbeat — отдельный сигнал. Это не изменение auth, query bounds или production; #209 остаётся отдельным security PR.

**CT-11 — обнаруженное несовпадение AsyncAPI.** Фактический runtime WS `/agents/{agent_id}/events` отдаёт state, pong и error; в опубликованном AsyncAPI ожидаются lifecycle EventEnvelope (eventId/type/occurredAt/traceId), firehose и workspace channels. Последние два отсутствуют. Новый regression фиксирует известный разрыв и точный фактический payload; ожидаемый PASS этого теста НЕ означает соответствие AsyncAPI. Не заменяем нормативный контракт фактическим без решения владельца: согласовать canonical producer, идентичность/версии/дедупликацию, поддержку workspace/firehose и migration с потребителями в #331/#346. Наблюдаемая auth модель runtime (API key + READ) не подтверждает описанные в AsyncAPI mTLS/JWT. Исполняемый протокол, права и runtime feature flags не меняются.


## Корпоративные границы и зависимости (#321)

В том же машинном реестре добавлен `enterprise_gaps` (EG-01…EG-07): handoff/delegation (#325/#339), tenant/principal (#323/#327), immutable bundle (#325/#329/#346), skill/context (#329), product connectors (#326/#327), policy/approval/aggregate budget (#327/#330), lifecycle/errors (#331/#346). Каждый пункт ссылается на существующие CT и исходные Issues, имеет unresolved и runtime_authority=null. Proposed owner — предложение, не назначение владельца. Это не второй реестр схем и не фиктивное утверждение, что эти протоколы внедрены.

Добавлены cross-boundary tests в действующий root pytest job: реальная frontend Draft 2020-12 схема проверяется вместе с исполняемым compiler на двух связанных Agent/Contract Gate, malformed metadata/positions/fields и unsupported design semantics (parallel, manual gate, retry, mapping, delegation, override, cycle). Валидная JSON Schema не означает исполнимый или разрешённый граф. Published workflow хранит immutable graph; полная связка версии policy/skill/contract/commit и авторизованная декомпозиция ещё не реализованы. Проверка scope существующего проекта не является tenant authorization.

QA v1: проверяется общий signer/verifier, tampering task/attempt/SHA/issuer, неверный ключ, expired/future receipt, дубли gate IDs и отказ неизвестных полей tenant/project/run/policy. Эти поля не являются поддерживаемой v1 схемой; их нужно согласовать в #323/#327/#346, не добавлять молча и не доверять заявлению модели. Тесты не выдают реальные credentials/approvals и не подменяют existing integration tests. CI на предыдущем candidate `db75d3aae4b98bd7e1299d9d0c75280c821aae96` 7/7 PASS; новый SHA требует повторного CI. Runtime и протоколы не изменены.


## CT-07 / CT-08: реальные границы native профиля и tool gateway

CT-07 дополнен ссылками на существующие reader/binding/wiring и `tests/native_agent_e2e/test_trusted_runner_wiring.py`: тест уже проходит путь real SQLite Agent Management → private snapshot → trusted runner и проверяет model/prompt/token cap, отсутствие credentials, несовпадение gateway workspace. Отдельную копию профильной схемы не создаём; #339 отвечает за role/revision binding. Вызов модели в этом тесте подменён, live provider acceptance не заявляется.

CT-08: установлено расхождение в строгой JSON-границе. Файловый endpoint принимал дубли полей (last-wins), Git endpoint отклонял дубли, а клиент принимал двусмысленные JSON responses; массив/объект error_code мог вызвать TypeError вместо санитизированного отказа. Общий декодер gateway_wire.py теперь одинаково отклоняет дубли на любом уровне, NaN/Infinity и некорректный JSON, клиент проверяет тип error_code до lookup. HTTP endpoints, поля, статусы, lease/fence, tool permissions и версия действующего протокола сохранены. Это не новый API. Добавлены negative client/Git tests и реальный SQLite leased gateway round-trip: повторяющиеся run_id/lease_token/event/arguments/content, nonfinite JSON отвергаются до записи в ledger или файла, после чего тот же call ID успешно выполняется один раз реальным клиентом. CI на актуальном SHA обязателен. Корпоративные tenant scopes, MCP, versioned tool contracts и PostgreSQL fence остаются зависимостями, не объявляются реализованными.


После интеграции #316 (`38f8deb138d422a10ba988897ad0b822fa341df2`) полный drift guard на кандидате #353 `c26add33a91dfa576818c74453a43f75b0665cc5` обнаружил ровно две секции: SSE events с `/api/v1` и без prefix. Два CI job (140523970442, 140523969304) выдали одинаковые generated diagnostics: `after.maximum=9223372036854775807` (signed int64). Обе границы перенесены в checked-in OpenAPI точным десятичным литералом, без округления JavaScript Number. Runtime, остальные поля и строгий тест полного равенства не изменены; новый CI обязателен. Production rollout #209 по-прежнему не подтверждён.
