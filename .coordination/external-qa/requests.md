# Входящие запросы от локального координатора (OWNER: local @orchestrator)

Этот файл обновляет **только локальный координатор**. Запросы добавлять в конец; старые записи не удалять. При ответе ссылаться на ID запроса.

Пока запросов нет. Для первого запроса рекомендуется передать независимому QA результат архитектурной задачи `t_005a92be` (она в `review`) — **коммиты/diff и ADR в доступной GitHub-ветке**, либо безопасную текстовую выжимку и файлы через пользователя.

## Шаблон записи

```md
## QA-REQ-YYYYMMDD-001
- local_task: t_...
- category: architecture-review | qa-regression | security-review | release-readiness
- priority: P0 | P1 | P2
- status: OPEN
- source_commit: <публично доступный GitHub SHA / ветка / local-only>
- evidence: <пути в опубликованном репозитории / CI URLs / обезличенные логи>
- question: <что проверить>
- acceptance: <какое доказательство ожидается>
- constraints: read-only; no local Kanban/worktree changes
```
