# Технические документы: границы актуальности

Проверка среза Git `45d914afdb5bc83f73ae2976d973eff2b876539d`. Эта карта не заменяет исходные контракты и не подтверждает production readiness. При изменении API или deployment сверять исходники сервиса и CI.

## ADR: пространства идентификаторов

| Пространство | Канонический источник / назначение |
|---|---|
| Продукт | `docs/adr/` — индекс в [портале](../developer/architecture-decisions/adr-index.md); старые восемь адресов — include, не самостоятельный текст |
| Runtime P8.3 | `docs/runtime-hardening/` — проектные ADR-001…005 и отдельный ADR-011 в architecture-decision-record.md; это локальные идентификаторы пакета, не продуктовые ADR-001/011 |
| Интеграционный аудит | `docs/integration-audit/adr/` — сохранённый срез ADR-101…103; не заменяет продуктовые решения |

При ссылке на P8.3 использовать полное пространство имени и путь; не переименовывать старые ADR и evidence только ради одинакового номера. Сравнение восьми продуктовых пар по исходному Git blob выполнено ранее; guard проверяет include и связь с каноническим файлом.

## Конфигурации и машинные контракты

| Материал | Результат проверки дерева |
|---|---|
| Resource quota JSON Schema | `docs/runtime-hardening/schemas/resource-quota.schema.json` (blob 765baffc) — проектная редакция, отличается от двух service copies (b8fd6940). Не выдавать draft за действующую runtime schema. |
| Resource quota YAML | Все три файла resource-quotas.example.yaml на этом срезе имеют одинаковый blob 62f387e4; совпадение байтов не доказывает корректность для production. |
| Runtime OpenAPI | Документная проектная версия (810550ba) и service версия (cafcc643) различаются. Сверять действующий service contract и runtime. |
| Domain model / plans | JSON в docs описывает исходный проектный замысел. Реальные state machine, migrations, contracts и API принадлежат сервисам, не этому JSON. |

Устранение дрейфа service schemas и контрактов — предмет #337/#346; не менять продуктовые схемы в PR #340. Исходные проектные файлы сохранены, их статус draft отражён в реестре.

## Практические инструкции

- [Пользовательская доска](../user-guide/kanban-runtime-board.md) использует native orchestration; [Kanban sync](../developer/kanban-integration.md) — отдельный dev tooling.
- [Native Worker](../NATIVE_WORKER_ACCEPTANCE_RU.md), [операторская приёмка](../qa/PILOT-READINESS.md) и [защищённый Compose](../qa/issue-11-secure-compose-ru.md) — рабочие runbooks, не свидетельства live запуска. Исторические секции архитектурных страниц описывают последовательность разработки.
- [Справочник API](../developer/api-reference.md) и [проверяемые примеры](documentation-inventory.md) сверяют реальные репозиторные пути; внешние окружения и секреты не проверяются автоматически.
