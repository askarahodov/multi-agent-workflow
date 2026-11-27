# Команды управления платформой

Штатное локальное управление продуктом выполняется через Makefile, Docker Compose и API. Hermes/Kanban — отдельный dev tooling для разработки самой платформы, не обязательный CLI для пользователя продукта.

## Makefile

Из корня репозитория на системе с make:

| Команда | Назначение |
|---|---|
| `make up` | Сборка и запуск dev Compose |
| `make ps` | Состояние служб |
| `make logs` | Просмотр логов |
| `make down` | Остановка стека |
| `make check` | Полная локальная проверка |
| `make backend-test` | Набор backend pytest |
| `make frontend-check` | Frontend tests, schema validation и build |
| `make security` | Security scan |

Правила передачи PR на review определяет действующий AGENT_GITFLOW_RULES.md, а не данная справка.

## Docker Compose

На Windows CMD, Linux или macOS:

```sh
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --build
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml logs --tail=100
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml down
```

Не добавляйте флаг -v при остановке с нужными данными. Dev Compose предназначен только для доверенной локальной машины.

## Проверки API

См. [первый запуск](getting-started.md), [справочник API](../developer/api-reference.md) и [локальную приёмку](../qa/LOCAL-MANUAL-ACCEPTANCE.md). Пользовательские задачи создаются через штатный интерфейс/REST, не через старую dev Kanban DB. Для защищённого запуска worker применяется [отдельный runbook](../NATIVE_WORKER_ACCEPTANCE_RU.md).

## Для разработчиков самой платформы

Интеграция GitHub ↔ локальный Kanban описана в [руководстве разработчика](../developer/github-kanban-sync-runbook.md). Действующие команды GitFlow и worktree определены AGENT_GITFLOW_RULES.md в корне. Старые примеры hermes-kanban не являются продуктовым API и не гарантируют доступность установленной CLI.
