# Справочник Docker Compose

Единственный источник конфигурации dev-стека — `deploy/compose/dev/docker-compose.yml`. Не копируйте YAML целиком в документацию: он дрейфует относительно кода. Пример локального override — `deploy/compose/dev/docker-compose.override.yml.example`, параметры — `.env.example`.

| Сервис | Host port по умолчанию | Container port |
|---|---:|---:|
| orchestration-server | 18000 | 8000 |
| agent-management | 8001 | 8001 |
| runtime-hardening | 8002 | 8002 |
| quality-gates | 8003 | 8003 |
| frontend | 5173 | 5173 |
| postgres | 5432 | 5432 |

Порты dev привязаны к loopback. PostgreSQL запускается, но сервисы по умолчанию используют SQLite. Dev runtime-hardening привилегирован; этот стек нельзя публиковать во внешнюю сеть.

```sh
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --services
make ps
```

Не публикуйте развёрнутый вывод config: он может содержать секреты. Отдельные защищённые профили в deploy/compose/secure не являются взаимозаменяемыми. Используйте [руководство развёртывания](deployment-guide.md), [trusted gateway](../architecture/trusted-gateway-image.md) и [приёмку worker](../NATIVE_WORKER_ACCEPTANCE_RU.md).
