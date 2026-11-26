# Интеграция Kanban: две разные границы

**Продукт:** [ADR-111](../adr/ADR-111-native-sdlc-dependencies.md) определяет единственный серверный источник истины — orchestration-server. UI отображает его runs, tasks, attempts и event log; native worker получает задачи через HTTP и атомарный claim. Не создавать второй runtime scheduler и не изменять статусы напрямую из UI.

- [Доска задач продукта](../user-guide/kanban-runtime-board.md).
- [Запуск опубликованного workflow](../user-guide/published-workflow-run.md).
- [Native worker: приёмка](../NATIVE_WORKER_ACCEPTANCE_RU.md).

**Разработка платформы:** Hermes Kanban и GitHub Issues могут синхронизироваться через отдельный инструмент `tools/github_kanban_sync/`. Это не продуктовая зависимость, не источник полномочий native worker и не API конечного пользователя. Актуальная инструкция — [runbook синхронизации](github-kanban-sync-runbook.md), включая ограничения, credentials, dry-run и доказательства. Старые команды hermes-kanban, /boards/{board}/tasks и recipes из предыдущих версий этой страницы не подтверждены как публичное API продукта; их оригинал доступен в Git-истории. Не исполнять старые сценарии на production.

Изменения инструментов разработки подчиняются AGENT_GITFLOW_RULES.md; #192 остаётся самостоятельной задачей. Состояние GitHub Issue не заменяет серверную запись задачи и не доказывает принятие результата.
