# Справочник API

Не использовать старые примеры Hermes `/boards`, `/auth/login` или dispatcher API как REST-контракт продукта. Источник состояния продукта — orchestration-server; провайдеры и профили принадлежат agent-management, независимый QA — quality-gates. См. [карту ответственности](../architecture/OWNERSHIP.md).

## Источники контрактов

| Сервис | Источник в Git | Dev host port |
|---|---|---:|
| orchestration-server | `services/orchestration-server/docs/openapi.json`, runtime OpenAPI | 18000 |
| agent-management | runtime OpenAPI и модели сервиса | 8001 |
| runtime-hardening | runtime OpenAPI, `services/runtime-hardening/hardening/api/agent-runtime-openapi.yaml` (техническая спецификация) | 8002 |
| quality-gates | runtime OpenAPI и модели сервиса | 8003 |

Сохранённая спецификация может отставать от runtime; проверять конкретную версию и контрактные тесты (#337/#346). Не копировать полные схемы сюда. Dev Compose слушает loopback и использует AUTH_ENABLED=false; не публиковать этот профиль наружу.

## Примеры чтения

Из доверенной локальной среды с dev Compose и портами по умолчанию:

```sh
curl --fail http://localhost:18000/health
curl --fail http://localhost:18000/api/v1/projects
curl --fail http://localhost:18000/api/v1/workflows/runs
```

В защищённом режиме действуют серверная аутентификация, scope и lease. Не вставлять ключи в URL, командную строку или Git. Получение списка не выдаёт право изменять чужие задачи. Сценарии claim/submit/recovery использовать только через доверенный runtime и [операторский runbook](../NATIVE_WORKER_ACCEPTANCE_RU.md).

## Lifecycle

Проекты, workspaces, workflow definitions и versions, runs/tasks и attempts — существующие ресурсы `/api/v1`. Публикация и запуск выполняются по серверному snapshot; параметры и ошибки проверяются по фактическому OpenAPI. Независимый QA и release approval не подменяются HTTP 200 от task submission. См. [запуск версии](../user-guide/published-workflow-run.md) и [качество](quality-gates.md).

Для SSE/WS см. [отдельный rollout](stream-ticket-rollout.md): включение tickets не разрешено этим справочником. Предыдущая редакция API Reference доступна в Git, но не является действующим контрактом.
