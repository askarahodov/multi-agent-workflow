# Масштабирование

Локальный dev Compose не является HA control plane. Не масштабировать произвольный сервис worker, не включать Redis/replicas или PostgreSQL migration по старым демонстрационным командам: их наличие и совместимость не доказаны.

## Безопасный порядок подготовки

- Зафиксировать workload, очередь, latency, resource limits, число активных leases и фактическое использование provider budget. Не выводить секреты.
- Проверить native worker и fencing попыток: повторный claim, lease expiry, restart, отмена и recovery. См. [server attempt leases](../architecture/server-attempt-leases.md).
- Разделить control plane, worker и trusted gateway; не переносить Docker socket или privileged из dev в недоверенную рабочую нагрузку.
- До HA проверить единый источник состояния, атомарность claim, идемпотентность, migration/rollback и восстановление на стенде.
- Сравнивать нагрузочные результаты на одинаковой конфигурации и фиксировать фактические limits, ошибки и UNKNOWN usage.

RKE2 Jobs, NetworkPolicy, HPA, PostgreSQL HA и изолированные контуры — #324/#332. До их приёмки нет подтверждённой инструкции production scaling. См. [развёртывание](deployment-guide.md), [backup/recovery](backup-recovery.md) и [мониторинг](monitoring-alerting.md).
