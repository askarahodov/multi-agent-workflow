# Версионирование

Канонический идентификатор релиза хранится в корневом файле VERSION без префикса v. Для текущей линии это 0.1.0-rc1; корневой package.json имеет ту же версию. Release workflow сверяет версию с тегом. Менять их нужно совместно при выпуске.

## Версии компонентов

На проверенном срезе main 6e47938df1f94e783f266c8210de5c92e8c20058 следующие manifests содержат 0.1.0:

| Компонент | Путь |
|---|---|
| agent-management | `services/agent-management/pyproject.toml` |
| orchestration-server | `services/orchestration-server/pyproject.toml` |
| quality-gates | `services/quality-gates/pyproject.toml` |
| maw-shared | `packages/shared/pyproject.toml` |
| maw-agent-runtime | `packages/agent-runtime/pyproject.toml` |
| agent-runtime | `services/runtime-hardening/pyproject.toml` |
| agent-runtime-hardening | `services/runtime-hardening/hardening/pyproject.toml` |
| multi-agent-workflow-tools | `tools/pyproject.toml` |
| frontend | `apps/frontend/package.json` |

Суффикс rc относится к релизу, а внутренние зависимости используют базовую версию линии. При изменении базовой версии проверяйте manifests, зависимые pin и runtime __version__; не предполагайте совпадение без проверки.

## Независимые версии контрактов

Версии JSON Schema, workflow, OpenAPI/AsyncAPI, политик и профилей независимы от номера пакета. Не изменяйте их автоматически при каждом релизе. Синхронизация версии GitFlow регулируется AGENT_GITFLOW_RULES.md и gitflow-policy.schema.json; версия политики не равна версии приложения. Машиночитаемая матрица наблюдаемых версий хранится в существующем [реестре контрактов](../architecture/contract-registry.md), не в отдельном registry.

## Выпуск

Обновить VERSION, корневой package.json, при необходимости версии компонентов и зависимости, CHANGELOG и release notes. Проверить фактический CI и независимое review. Выпуск и подписанный тег — после разрешённого merge и release gate. Не публиковать релиз только на основании документации.


## Lifecycle и совместимость (#346)

Проект правила. В реестре CT поля `lifecycle` фиксируют только наблюдаемые версии и ограничения поддержки. Unknown означает отсутствие доказанной версии; нельзя подставлять версию компонента. Контракт без явной версии не становится совместимым автоматически.

| Изменение | Допуск структурной проверки | Действия |
|---|---|---|
| Форматирование JSON | Без изменения канонического содержимого | Обычные CI/review |
| Добавление нового REST path/operation | Существующие paths, операции, компоненты, security, параметры и metadata неизменны; info.version увеличен в той же major линии | Exact change record, тесты всех consumers, уведомление, rollout/rollback |
| Удаление, изменение schema/required/response, opaque YAML, неизвестная совместимость | Запрещено менять на месте | Параллельная версия с новой major, старый artifact остаётся побайтово/семантически прежним; plan, adapter и consumer acceptance |
| Удаление старой версии | Запрещено этим baseline | Отдельное согласование retirement после доказанного отсутствия consumers, завершения активных attempts, backup/rollback |
 
Change record в существующем contract-registry.json: ID CV-NNN, CT, kind, from/to path, SHA256 канонического JSON (точные десятичные значения, без IEEE-754 округления; сортировка ключей) или исходных YAML bytes, from/to version, migration, rollback, notification, все связанные consumer tests. Новые записи append-only, не имитируют approval; не использовать для прямого обхода breaking gate. Добавление параллельного schema artifact не доказывает поддержку runtime: перед переключением нужны отдельные producer/consumer tests и независимая приёмка.

### Mixed-version

- CT-01: workflow schema 1.0, published snapshot immutable. Схема дизайнера шире исполняемого compiler; unknown version не принимается.
- CT-07: native snapshot v1 читается как UNKNOWN role и не подходит для pinned task. V2 добавляет роль, reader обновить первым; затем остановить worker, экспортировать v2 и перезапустить. При rollback не удалять pin: остановить affected tasks и reconcile; v1 не даёт role-bound authority.
- CT-09: QA receipt v1 подписывает точный набор полей. Tenant/policy fields не добавлять в v1; новый signer/verifier и overlap должны быть отдельно утверждены.
- CT-10/11/12: версии документов наблюдаемые, не доказательство полной wire/mixed-version parity. CT-13 и другие неявно версионированные протоколы UNKNOWN.
- Для active run запрещено переписывать workflow/profile/policy/skill/contract pin. Сейчас immutable workflow и optional exact native profile revisions есть (#339); skill и полный per-run contract pin остаются #325/#329/#327, не выдавать doc за enforcement.

### Проверка CI

```sh
node --test scripts/check-contract-evolution.test.mjs
CONTRACT_BASE_SHA=$(git rev-parse origin/main) node scripts/check-contract-evolution.mjs
```

CI использует base SHA из PR / predecessor protected push, требует достижимый Git ancestor и читает обычные tracked blobs, а не пользовательские временные файлы. Сравнение проверяет все машинные schema sources из текущего CT-реестра, без второй копии; отсутствующий base, schema, обязательный record или consumer tests — FAIL. Точные numeric constraints проверяются на реальных int64 maximum, дробях и exponent notation; изменение значения не считается форматированием. Дубли JSON-ключей, пересечение новых маршрутов с шаблонными и удаление существующих consumer tests отклоняются. YAML трактуется консервативно, не заявляем семантический AsyncAPI diff. Tests используют реальный OpenAPI baseline, реальные Git commits и synthetic additive/breaking mutations, не выпускают API v2. Продолжать существующие runtime consumer tests; изменение Python DTO без машинной схемы требует отдельного review и contract tests. Новый contract без предыдущего versioned artifact требует отдельного bootstrap решения; существующая политика не разрешает автоматическое снятие ограничения. Не выдавать structural PASS за approved live rollout.
