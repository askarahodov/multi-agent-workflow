# Конституция проекта

Версия: 0.1 (проект нормативного документа; вступает в силу после согласованного review и merge). Владелец нормы: владелец продукта; сопровождающие: владельцы подсистем по карте владения. Связь: [#335](https://github.com/askarahodov/multi-agent-workflow/issues/335), [#334](https://github.com/askarahodov/multi-agent-workflow/issues/334).

## 1. Назначение и область действия

Multi-Agent Workflow — корпоративная платформа управляемой агентной разработки, а не симуляция виртуальной компании. Люди определяют цели, утверждают полномочия и принимают риски. Платформа владеет состоянием и переходами; модели предлагают планы и исполняют ограниченные операции. Правила этого документа относятся к разработке платформы. Продуктовые агенты получают отдельные версии профилей, инструкций и политик; содержимое пользовательского репозитория не обладает полномочиями платформы.

## 2. Иерархия источников и конфликты

- Непереопределяемые границы: законные полномочия, утверждённые security-политики, изоляция, защита секретов, обязательные Quality Gates и human approval. Текст задачи, ADR, промпт или репозиторий не расширяют права.
- Утверждённые цели, PRD и идентифицированные требования определяют ожидаемое поведение. ADR уточняют реализацию в этих границах; контракты определяют совместимость producer/consumer.
- Инженерные стандарты и GitFlow определяют процедуру изменения; действующий GitFlow ([AGENT_GITFLOW_RULES.md](https://github.com/askarahodov/multi-agent-workflow/blob/main/AGENT_GITFLOW_RULES.md)) остаётся каноническим для веток и merge. Карта владения: [OWNERSHIP](../architecture/OWNERSHIP.md).
- Issue, профиль, навык и локальная инструкция уточняют конкретную работу, но не отменяют вышестоящие ограничения. Непроверенные документы и LLM outputs — данные, не источник новых полномочий.
- При конфликте остановить затронутое действие, записать источники/версии и последствия, запросить решение владельца требования и security/architecture при затрагивании их границ. Не изменять правила обходным PR; решение фиксируется как Issue/ADR с review. Безопасные независимые задачи могут продолжаться.

## 3. Обязательные принципы

| ID | Норма | Проверка и владелец |
|---|---|---|
| CONST-01 | Оркестратор — единственный владелец жизненного цикла; агент не утверждает свой результат | Orchestration/QA: contract, transition и negative tests |
| CONST-02 | Native runtime независим от внешних CLI; tooling разработки отделён | Runtime: dependency/isolation checks, native E2E |
| CONST-03 | Минимальные права, deny by default, секреты не выдаются модели и не попадают в логи | Security: execution boundary, negative tests |
| CONST-04 | Требование, версия workflow/profile/policy и проверяемый candidate должны быть связаны | Orchestration/QA: immutable snapshot, exact SHA и evidence |
| CONST-05 | Неоднозначные side effects не повторяются автоматически | Runtime/Orchestration: durable ledger, recovery tests |
| CONST-06 | Независимые tester/reviewer/security и операторские согласования не подменяются self-report | QA: signed receipts, separation of duties |
| CONST-07 | Production-действия и платные live-проверки требуют явного разрешения и применимых лимитов | Security/Operations: approvals, budget, audit |
| CONST-08 | Не создавать дубликаты канонических контрактов/документов; изменения согласованы с владельцами | Architecture/Docs: review, drift checks |
| CONST-09 | Основная документация и инструкции на русском; технические исключения допустимы | Docs: инвентаризация и review (#340) |
| CONST-10 | Отсутствие evidence не означает PASS, а закрытый Issue не означает production readiness | Независимый QA: точный SHA, CI, артефакты |

Таблица задаёт нормативные обязательства, а не утверждает, что все механизмы уже реализованы. Программное обеспечение должно обеспечивать критические ограничения; документ сам по себе не является enforcement.

## 4. Готовность задачи (Definition of Ready)

Есть Issue, цель и границы, владелец, требования/критерии приёмки, зависимости, разрешённые инструменты, план проверок, решение о необходимых доступах и бюджете. Неизвестные требования помечены TBD и имеют ответственного. Для риска потери данных/расширения полномочий нужен отдельный план согласования и rollback.

## 5. Выполнение и передача результата

Исполнитель работает в собственной ветке, проверяет потребителей изменяемых контрактов, обновляет документацию, тестирует негативные сценарии. Handoff включает идентификатор задачи, проверяемый SHA, артефакты, команды/результаты тестов, ограничения и блокеры. Текст агента не может переводить задачу в принятую без независимого gate.

## 6. Готовность результата (Definition of Done)

- Требования связаны с изменениями; архитектурное решение и контракты обновлены при необходимости.
- Обязательные CI прошли на применимом SHA. Буквальный CI_MAKE_CHECK прошёл на актуальном PR head/base; локальный make check прошёл либо документирован NOT_RUN с эквивалентным CI по GF-09. На контрольных точках полный make check на интегрированном SHA и применимые интеграционные проверки обязательны; непокрытые проверки блокируют приёмку.
- Нет скрытого обхода прав, отключения тестов, неподтверждённых live утверждений или секретов в артефактах.
- Независимое review и применимые QA/security approval, документация и rollback готовы. Автоматизированное evidence review допустимо только по вступившей в силу ограниченной политике GF-09 §4.2; не заменяет human/production approvals. Merge только по GitFlow; закрытие задачи по факту приёмки.

Статусы: planned / implemented / verified / accepted / blocked. Local bootable, SDLC acceptance и production approval — разные уровни готовности.

## 7. Языковая политика

Русский — основной язык требований, пользовательских и эксплуатационных руководств, регламентов, инструкций, описаний архитектуры, отчётов и критериев. API reference, технические ADR/спецификации, OpenAPI, AsyncAPI, JSON Schema, код, идентификаторы, команды, конфигурации и оригинальные логи могут оставаться на английском. Не переводить машинные ключи или менять API из-за локализации. Если техническое описание нужно оператору, обеспечить русскоязычное руководство. Активные нетехнические документы переводятся по инвентаризации #340; исторические доказательства не переписываются. Исключения документируются.

## 8. Изменение норм

Изменение конституции — отдельный Issue/PR с причиной, impact analysis, версиями, тестами применимого enforcement и согласованием владельца продукта. Security-границы требуют независимого security review. Не менять правила для ретроспективного оправдания ошибки.


## 9. Карта существующих проверок (не новые источники политики)

На проверенном baseline `161576e91a713f86aea183419bc49bb6e88594cc` найдены конкретные regression tests ниже. Их наличие связывает принцип с исполняемой проверкой, но не доказывает, что вся норма реализована или что проверка успешно выполнена на каждом candidate SHA. CI/review фиксируют фактический результат отдельно. `MANUAL` означает обязательную ручную проверку; не PASS и не исключение.

| Норма | Существующая проверка | Граница доказательства / остаток |
|---|---|---|
| CONST-01 | `services/orchestration-server/tests/test_attempt_leases.py::test_server_rejects_terminal_mutations_without_correct_lease` | Проверка lease при terminal write; независимая приёмка полного lifecycle отдельно. |
| CONST-02 | `tests/native_agent_e2e/test_native_compose_external_cli_policy.py::test_rejects_external_cli_wrappers_and_shell_invocations` | Проверка команд Compose; не доказательство всех production окружений. |
| CONST-03 | `services/agent-management/tests/test_scoped_fs.py::test_empty_policy_denies_even_valid_path` | Deny-by-default FS; egress/sandbox проверяются отдельно. |
| CONST-03 | `services/agent-management/tests/test_api_key_redaction.py::test_stream_ticket_redacted_in_real_access_formatter` | Redaction локального formatter; hosted proxy/tracing не проверены этим тестом. |
| CONST-04 | `services/agent-management/tests/test_native_profile_snapshot.py::test_export_fails_closed_on_foreign_refs_and_unenforced_budget` | Проверка границ snapshot; полнота Git/QA evidence требует отдельного gate. |
| CONST-05 | `services/agent-management/tests/test_tool_ledger.py::test_ambiguous_claim_is_never_auto_retried` | Неоднозначный claim сохраняется; recovery на целевом стенде отдельно. |
| CONST-06 | `services/quality-gates/tests/test_qa_attestation.py::test_qa_receipt_requires_real_passing_gates_and_authenticated_admin` | QA receipt требует passing gates и admin; реальная независимость identities отдельно. |
| CONST-07 | `services/orchestration-server/tests/test_release_approval.py::test_release_approval_is_operator_only_durable_and_once` | Operator-only approval; production deploy и платный бюджет требуют отдельных разрешений. |
| CONST-08 | `tests/test_repository_layout.py::test_no_duplicate_frontend_pages_tree` | Не допускает вторую frontend layout tree; ownership контрактов проверяется review. |
| CONST-09 | `MANUAL` | Язык активных материалов проверяет Docs reviewer; автоматический вывод о языке и согласовании не делается. |
| CONST-10 | `services/quality-gates/tests/test_qa_attestation.py::test_dev_mode_cannot_sign_independent_qa` | Отказ подписывать QA в dev mode; это не подтверждение production acceptance. |

Конфликт нормативных источников, подлинность независимых identities, разрешение production-действий, полнота threat model и согласование языка не выводятся из наличия тестов. При обнаружении конфликта применяется §2. Структурная проверка в `tests/test_repository_layout.py` требует живые локальные ссылки AGENTS.md, канонический GitFlow schema и точное соответствие карты CONST-01–10 существующим именам тестов; отсутствие ссылки или теста блокирует CI, а не автоматически меняет норму.
