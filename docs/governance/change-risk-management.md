# Управление изменениями и рисками

Версия 0.1, проект для согласования #342 (GOV-08). Baseline `43e7ff473b34ca67064f9ea3b98738367684fdc5`, наблюдение GitHub 27.11.2026. Источники: [PRD](../product/PRD.md), [реестр контрактов](../architecture/contract-registry.md), [RTM](../product/traceability.md), [карта владения](../architecture/OWNERSHIP.md), [конституция](constitution.md). Это инструмент разработки платформы, не дополнительный runtime gate и не источник прав.

## Реестр рисков

Машинный источник — `docs/governance/risk-register.json`. Риск имеет ID, владельца области, статус open/restricted/mitigating, качественные impact/likelihood, mitigation, residual и ссылки на фактические файлы и наблюдавшиеся Issues. Оценки low/medium/high/critical — проектные качественные суждения, не измеренные вероятности; не использовать их для автоматического risk acceptance. Закрытый Issue не закрывает риск. При новом факте актуализировать дату, ссылки и остаток; история изменений сохраняется в Git.

- RISK-001: #3 закрыт как local-only deferred. Docker socket/privileged сохраняются; внешний запуск запрещён до #324.
- RISK-002: #209 по API закрыт, хотя последнее интеграционное сообщение оставляет hosted/security acceptance открытой. Техническая интеграция #316 не означает включение ticket-only в production.
- RISK-003: #323, corporate tenancy, RBAC и межпроектная изоляция.
- RISK-004: #324, RKE2 native worker boundary, стендовые escape/recovery/HA tests.
- RISK-005: #327, независимая приёмка, identity/snapshot binding и запрет self-acceptance.

Ссылки на #3/#209/#323/#324/#327 — снимок, не мониторинг GitHub; исходные записи сохраняют наблюдённые состояния и причину residual. Источники и состояния не являются PASS стендового теста.

## RFC и анализ влияния

Машинный источник — `docs/governance/change-proposals.json`. Один RFC привязан к Issue, перечню типов изменений (требования, ADR, контракт, model, skill, permission, dependency, infrastructure), существующим affected paths, requirement/contract/risk IDs. При breaking change обязательны договорённость о версионировании, миграционный и rollback plan, проверяемые ссылки, независимые reviewer/tester/security/architecture и операторское согласование.

1. Автор готовит draft и ограничивает scope, фиксирует affected paths, тесты, документацию, migration и rollback. Для новой сущности явно описать план добавления; ссылки evidence указывают только на уже существующие tracked files.
2. Read-only анализатор добавляет producer/consumers из канонического CT-реестра, консервативно распространяет impact до фиксированной точки по явным требованиям, изменяемым путям, RTM contract_refs и CT sources/runtime_authority, объединяет связанные компоненты, тесты и ADR, выдаёт предложения дочерних задач по компонентам и связанные Issue IDs. Архитектурные ссылки найденных требований остаются выходным списком документации, а не автоматически изменяемыми путями. Совпадение общего schemas.py может расширить список: reviewer уточняет impact, но автомат не создаёт Issues, не изменяет scope и не утверждает исключения.
3. При in_review указываются автор и exact candidate SHA. Структурные decision records содержат роль, actor, решение, exact SHA, дату, внешний GitHub comment/review reference. Проверяются отсутствие self-review, дубли ролей/actors/references, актуальная привязка, отсутствие противоречащих решений и полный набор ролей для recorded approval. Это **проверка формы, не подлинности**. Поле authorization в отчёте всегда false; без доверенной проверки #327, отдельного решения и действующего GitFlow изменение не считается принятым.
4. Исключение содержит ID, риск, точный scope, reason, owner, expiry и status. Requested не действует, recorded требует связанный security decision record на том же candidate и непросроченную дату; expired/revoked не действуют. Любой record только указатель на внешнее решение, не выдаёт permission и не заменяет gate.
5. После согласования реализация выполняется отдельным Issue/PR в утверждённых границах. При изменении candidate обновить evidence; при изменении рисков или контракта повторить impact review. Документация, tests, миграции и rollback в соответствующем PR. Верификация и принятие — по GF-09/#327.

## Проверяемый пример breaking API

RFC-001 предлагает гипотетическую v2 для cursor событий, не меняет текущее поведение. CT-12 связывает orchestration-server, frontend, native-worker и quality-gates. Связи по CT/RTM автоматически добавляют затронутые требования, включая совместимость, и существующие проверки. Migration сохраняет v1 и journal, rollback возвращает совместимый client без URL API keys; независимые роли перечислены, approvals пусты. Никакого production rollout.

## Запуск

Из корня Git checkout (Node.js 22, без сетевых запросов и секретов):

```sh
node --test scripts/check-change-governance.test.mjs
node scripts/check-change-governance.mjs
```

Существующий Quality Gate → requirements traceability выполняет обе команды после проверки RTM. CLI валидирует metadata, уникальность и все ссылки на обычные tracked файлы, исключает symlinks/untracked paths; считает impact по фактическим registry/RTM. При missing/invalid/stale decision record или просроченном recorded exception завершается ненулевым кодом. Фикстуры проверяют корректный impact, negative cases, подмену SHA, self-review, просрочку, утрату source/test refs, попытку добавить authority. Отчёт JSON содержит proposals и ограничения; не публикует secret values, не вызывает provider или GitHub mutation.

## Ограничения и DoD

GOV-02/03/04 интегрированы как проектные baseline, не как утверждённые требования. #327 ещё не принят; подлинность decision records, полномочия actors, фактические security/rollout approvals и аудит внешнего журнала должны быть подтверждены доверенной стороной. Оценки риска требуют подтверждения владельцами. Пример RFC не доказывает реальную migration или rollback. До independent approval и exact CI #342 остаётся открытым; нет изменения runtime permissions. При откате этого PR удалить только новые governance artefacts и добавленные команды существующего gate; не удалять RTM/контрактные проверки. Исторические evidence не меняются.
