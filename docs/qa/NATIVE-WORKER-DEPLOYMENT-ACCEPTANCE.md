# Контрольная точка: Native Worker / Trusted Gateway (#33, #38, #54)

> **Статус:** исходный `main` проходит offline CI, но **полный автономный
> запуск из Compose не принят**. Этот документ — контрольная карта, а не
> утверждение о завершении реализации.

## Что уже проверяется в репозитории

- `.github/workflows/native-agent-e2e.yml` запускает
  `python -m pytest tests/native_agent_e2e -q` в Python 3.12.
- `services/orchestration-server/orchestration_server/native_http_worker.py`
  содержит ограниченный authenticated polling и поддержку доверенного
  `leased_runner`, но намеренно **не содержит production process entrypoint**.
- `services/agent-management/agent_management/trusted_fs_gateway.py` — отдельный
  opt-in шлюз. Его TLS, приватные SQLite/ledger и workspace задаёт оператор.
- `deploy/compose/dev/docker-compose.yml` **не** включает сервисы native worker и gateway.
  Успешные healthcheck существующих пяти API и Postgres не означают
  выполнения задачи ИИ.
- `ORCH_ATTEMPT_LEASE_ENABLED` по умолчанию отключён. Для guarded
  submit/fail и remote file gateway нужен согласованный opt-in контур.
- `deploy/compose/dev/docker-compose.yml` использует `AUTH_ENABLED=false` в локальном
  dev-режиме. Такой Compose **не подходит для защищённого запуска**.

## Требуемое состояние до автономного запуска (блокирующие критерии)

| Проверка | Условие приёмки | Связь |
|---|---|---|
| Worker process | Есть штатный entrypoint и контролируемый lifecycle | #54 / #33 |
| Tool gateway | TLS, отдельный ключ, приватные ledger/DB, нет открытого порта в Internet | #54 / #38 |
| Execution isolation | Worker не имеет прямой записи в workspace и доступа к orchestration SQLite | #54 |
| Lease / terminal gate | Положительные и отрицательные попытки проверяются на одном доверенном состоянии | #33 / #38 |
| Crash recovery | `CLAIMED` при неоднозначном эффекте остаётся в карантине; никакого auto-replay | #38 |
| Contract Gate | `completed` только после контрактной проверки сервером | #33 / #11 |
| Native integration | Реальный процесс через HTTP в Compose, в том числе два конкурирующих worker | #54 |
| Hermès independence | Ни gateway, ни worker не вызывают Hermes CLI/kanban | #11 |
| Operations | Readiness, graceful stop, redacted logs, documented rollback | #54 |
| Live provider | Отдельный разрешённый запуск с реальным ключом и бюджетом | #8 / #11 |

## Dependency order и безопасный checkpoint

1. Разработать точку входа native worker с ограниченным supervisor и
   явной конфигурацией доверенного runner. **Никакого скрытого запуска
   платных провайдеров при простом `docker compose up`.**
2. Создать отдельный opt-in Compose override/profile. Не заменять
   `deploy/compose/dev/docker-compose.yml` и не ослаблять режим разработческой изоляции.
3. Изолировать права: filesystem executor запускается только внутри
   gateway; worker не получает mount SQLite/ledger и не исполняет
   файловые инструменты напрямую.
4. Добавить cross-process Compose E2E: успешная задача, второе
   конкурирующее назначение, обрыв gateway, отмена, restart, expired
   lease и recovery во время файловой операции.
5. После зелёных тестов обновить операторский runbook и проверить
   Linux Docker + Windows Docker Desktop (допускаются только команды
   CMD/`docker compose`, без PowerShell `.ps1`).
6. Независимое review и приёмка #54, затем отдельно #33/#38/#11.

## Минимальные проверяемые команды текущей offline базы

```sh
python -m pytest tests/native_agent_e2e -q
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Для чистого запуска из Linux/macOS или Windows CMD необходимо сначала
установить Docker и зависимости проекта. Команды выше **не** запускают
отдельный Native worker; это только проверки инфраструктуры и offline
тестов. Реальное выполнение инструментов на тестовом workspace должно
появиться в отдельном opt-in integration scenario из #54.

## Неизвестное и ограничения доказательств

- Зелёный offline тест не доказывает доступ к живому OpenRouter, скорость
  ответа, фактические расходы или устойчивость в production.
- Отсутствие ошибки Compose healthcheck не означает успешное создание
  и завершение SDLC-задачи.
- `CLAIMED` в Tool Ledger не доказывает, что побочный эффект произошёл
  или не произошёл; запрещено повторное выполнение без reconciliation.
- SQLite fencing предполагает совместно размещённый приватный локальный
  том, не NFS/PostgreSQL/multi-host.
- Нельзя переносить сюда production secrets и ослаблять TLS/RBAC ради
  прохождения демонстрационных тестов.

**Итоговый gate:** `#54 READY` только после независимого review и
реального изолированного Compose E2E. До этого #33/#38 остаются открытыми.
