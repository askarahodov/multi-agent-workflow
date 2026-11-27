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

Версии JSON Schema, workflow, OpenAPI/AsyncAPI, политик и профилей независимы от номера пакета. Не изменяйте их автоматически при каждом релизе. Синхронизация версии GitFlow регулируется AGENT_GITFLOW_RULES.md и gitflow-policy.schema.json; версия политики не равна версии приложения. Правила совместимости, миграций и deprecation развиваются в #337/#346.

## Выпуск

Обновить VERSION, корневой package.json, при необходимости версии компонентов и зависимости, CHANGELOG и release notes. Проверить фактический CI и независимое review. Выпуск и подписанный тег — после разрешённого merge и release gate. Не публиковать релиз только на основании документации.
