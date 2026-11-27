# Настройка Multi-Agent Workflow

Актуальная конфигурация локального продукта определяется `.env.example`, `deploy/compose/dev/docker-compose.yml`, конфигурациями сервисов и записями их API. Ранее опубликованные примеры YAML-профилей Hermes, dispatcher.yaml и data/kanban.db относились к инструментам разработки платформы; не используйте их как инструкцию по настройке native runtime.

## Локальный запуск

См. [первый запуск](getting-started.md). Из корня репозитория:

```sh
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --build
```

Пример необязательных локальных параметров в исключённом из Git файле `.env`:

```dotenv
ORCH_HOST_PORT=18000
AGENT_MGMT_HOST_PORT=8001
RUNTIME_HOST_PORT=8002
QG_HOST_PORT=8003
FRONTEND_HOST_PORT=5173
POSTGRES_HOST_PORT=5432
MAW_OUTBOUND_PROXY_URL=
```

Порты привязаны к loopback. Изменение host port не меняет внутренний порт контейнера. В штатном Compose браузер использует Vite proxy и заданные ORCH_UPSTREAM/AGENT_MGMT_UPSTREAM. Не публикуйте dev-стек наружу: AUTH_ENABLED=false, runtime-hardening имеет privileged и Docker socket.

## Провайдеры, модели и профили

Настройте проект в [мастере](project-setup.md), провайдер и модель — в настройках, затем [профили агентов](agent-profiles.md). AgentDefinition, ModelProfile и ToolPolicy — серверные сущности, не YAML-файлы Hermes. Перед сохранением реального ключа установите постоянный AUTH_ENCRYPTION_KEY (base64 от 32 случайных байт, см. первый запуск); не меняйте его без процедуры миграции. Не публикуйте ключи и вывод конфигурации, содержащий секреты. Провайдерский каталог и model profile не доказывают, что конкретный native worker поддерживает эту модель.

Проверка подключения может выполнить реальный вызов модели. Offline smoke не требует ключа и не должен вызывать /completions. Для native worker используйте отдельный согласованный [runbook](../NATIVE_WORKER_ACCEPTANCE_RU.md); экспорт профиля и его доверенная установка не равнозначны запуску или выдаче новых полномочий.

## Хранилища и состояние

Dev Compose запускает PostgreSQL, но orchestration-server, agent-management и quality-gates по умолчанию используют разные SQLite базы в bind-mounted каталогах сервисов. Не удаляйте базы и volumes ради исправления HTTP 500. Для миграции используйте резервную копию и процедуру из [локальной приёмки](../qa/LOCAL-MANUAL-ACCEPTANCE.md). PostgreSQL как production-профиль требует отдельного подтверждения миграции, восстановления и совместимости.

## Прокси и поток событий

MAW_OUTBOUND_PROXY_URL — необязательный прокси для исходящих запросов; MAW_OUTBOUND_NO_PROXY исключает loopback и имена внутренних сервисов. Подробности и безопасная диагностика — в [первом запуске](getting-started.md). ORCH_STREAM_TICKETS_ENABLED и VITE_STREAM_TICKETS_ENABLED в dev Compose выключены по умолчанию; согласованный переход на короткоживущие tickets описан в [руководстве rollout](../developer/stream-ticket-rollout.md). Не включайте только одну сторону без проверки совместимости.

## Проверка и ограничения

Используйте [диагностику](troubleshooting.md), проверку сохранения состояния и браузерный smoke. Не путайте сохранённый граф, health, успешный mock и реальный принятый SDLC. Поддерживаемая enterprise-конфигурация и Kubernetes delivery остаются задачами #324/#332.
