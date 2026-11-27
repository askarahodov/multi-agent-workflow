# Развёртывание

Поддерживаемый путь локальной проверки — dev Compose. Он **не является production-профилем**: AUTH_ENABLED=false, runtime-hardening privileged с Docker socket, исходники bind-mounted. Не публиковать его наружу и не запускать с production credentials.

## Локальный стенд

Из корня репозитория, на доверенной машине с Docker Engine и Compose plugin:

```sh
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
make up
make ps
curl --fail http://localhost:18000/health
curl --fail http://localhost:8001/health
curl --fail http://localhost:8002/health
curl --fail http://localhost:8003/health
```

UI: `http://localhost:5173`. При изменённых host ports используйте фактические значения из локальной конфигурации. `make logs` — диагностика; `make down` — остановка без явного удаления volumes. Перед любыми действиями с данными — резервная копия. Health не доказывает SDLC acceptance.

См. [настройку](../user-guide/configuration.md), [Compose](docker-compose-reference.md), [локальную приёмку](../qa/LOCAL-MANUAL-ACCEPTANCE.md).

## Защищённый native runtime

Специализированные файлы находятся в `deploy/compose/secure/`. Использовать только согласованные профили и инструкции [native worker](../NATIVE_WORKER_ACCEPTANCE_RU.md), [trusted gateway](../architecture/trusted-gateway-runtime-compose.md), [secure SQLite control](../architecture/trusted-sqlite-control-compose.md). Не объединять произвольные overlays, не переносить dev secrets или privileged boundary в недоверенный worker. Проверять образ, digest, scope, хранилища, сетевую политику, credentials и rollback на изолированном стенде.

## Релиз, RKE2 и HA

Release Dockerfiles и workflow release.yml существуют, но образ сам по себе не подтверждает production deployment. Helm/Fleet, RKE2, HA scheduler, PostgreSQL migration, backup/restore и отдельные air-gap контуры — целевые требования #324/#332, не подтверждённая инструкция. Старые демонстрационные Helm/HPA/Redis и single-binary recipes из предыдущей редакции не выдаются за поставляемые артефакты. Перед production нужны принятые manifests, миграции, стендовые проверки, security review и rollback.
