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
