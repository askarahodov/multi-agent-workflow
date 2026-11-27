# Диагностика Multi-Agent Workflow

Сначала определите версию/SHA и окружение. Ниже команды для локального dev Compose; не выполняйте их на production без согласования.

## Службы не запускаются

Из корня репозитория:

```sh
docker compose version
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml logs --tail=100 orchestration-server agent-management frontend
```

Ожидаются шесть служб: postgres, orchestration-server, agent-management, runtime-hardening, quality-gates, frontend. Проверьте ошибки сборки, занятые host ports и состояние health. По умолчанию UI доступен на 127.0.0.1:5173, orchestration на 18000, agent-management на 8001, runtime на 8002, QA на 8003.

```sh
curl -fsS http://127.0.0.1:18000/health
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8002/health
curl -fsS http://127.0.0.1:8003/health
```

Health подтверждает доступность процесса, не корректность данных или SDLC.

## HTTP 500, проекты или профили не загружаются

Определите конкретный запрос через Network в браузере. Сопоставьте статус, время и обезличенную ошибку с логом соответствующего сервиса. Проверьте Vite upstream, версию и старую схему SQLite. Не удаляйте базы и не регенерируйте ключ шифрования для устранения ошибки. Сделайте резервную копию до любых миграций. Read-only проверка agent-management после backup:

```sh
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml exec -T agent-management python -m agent_management.schema_audit
```

Результат проверяет наличие ожидаемых таблиц/столбцов, а не все типы, индексы или корректность данных. При несовпадении требуется план миграции и rollback. См. [локальную приёмку](../qa/LOCAL-MANUAL-ACCEPTANCE.md).

## Модель или провайдер не работает

Сначала проверьте настройки профиля, разрешённый provider/model, постоянство AUTH_ENCRYPTION_KEY и сетевой доступ. Не выводите значения ключей и proxy URL с credentials. Коды 401/403/429, transport error и truncation разбираются в [первом запуске](getting-started.md). Не обходите ограничения egress, не увеличивайте расход автоматически. Offline проверка не требует реального вызова.

## Задача не исполняется или зависла

Проверьте run/task/attempt, зависимости, lease, блокеры, подключение native worker и соответствие профиля. Dev Compose сам по себе не запускает платного worker. Используйте [сценарий публикации](published-workflow-run.md) и [native worker runbook](../NATIVE_WORKER_ACCEPTANCE_RU.md). При неоднозначной операции — карантин и независимое reconciliation; не меняйте статус напрямую в БД, не повторяйте действия вслепую. См. [восстановление](../architecture/safe-worker-recovery.md).

## Поток событий и UI

Проверьте фактический API response и соответствие ORCH_UPSTREAM/AGENT_MGMT_UPSTREAM. Если включены stream tickets, проверьте согласованность клиента и сервера, истечение срока и повторное подключение по [rollout](../developer/stream-ticket-rollout.md). Не вставляйте ключи в URL или публичные логи.

## Приёмка и обращение за помощью

Для воспроизведения используйте [проверку первого запуска](getting-started.md) и [локальную приёмку](../qa/LOCAL-MANUAL-ACCEPTANCE.md). Укажите SHA, окружение, шаги, ожидаемый и фактический результат, обезличенный лог, CI и ограничения. Не публикуйте токены, персональные данные, содержимое .env или полный вывод compose config. Не ослабляйте QA/security gates ради зелёного результата.
