# #192 · единый GitHub ↔ Kanban: интеграционный checkpoint

**Дата:** 03.11.2026  
**Источник:** [Issue #192](https://github.com/askarahodov/multi-agent-workflow/issues/192),
[единый PR #235](https://github.com/askarahodov/multi-agent-workflow/pull/235).  
**Исходный main:** `ee06a35ed6ae367dd47bc73ac33d420fa9b5fa5c`.

## Исполняемый контракт

Две отдельно прошедшие CI ветки консолидированы **в одну PR-серию**:
[#231 — strict CI/close](https://github.com/askarahodov/multi-agent-workflow/pull/231)
и [#232 — all-page polling](https://github.com/askarahodov/multi-agent-workflow/pull/232).
В интеграционной ветке добавлены необходимые для автономной доставки механизмы:

- Полная пагинация Issues/PR/comments/check-runs; fail-closed на сбое страницы
  и отсутствии `total_count`; безопасный переход со старого cursor/ETag.
- Регулярный `daemon`/`sync` опрашивает linked Issue comments (включая
  `MIGRATION_182_HANDOFF`) и CI на валидном SHA связанных PR, а не только
  Issues/PR metadata.
- Одно GitHub событие с несколькими Issue доставляется каждой существующей
  Kanban-карточке без создания дубликата. Итог доставки завершается только
  после проверки **всех** получателей: ошибка первой карточки при успехе
  второй, равно как ошибка последней, сохраняет `pending_events` до retry.
- Webhook может опередить poll и не содержать ссылок на Issue. Повторный poll
  **дополняет durable PR payload списком связанных Issue** до доставки, так
  что отказ SQLite не теряет маршруты для последующего restart/retry.
- Повтор исторического (меньшего по номеру) PR не перепривязывает карточку
  со свежего PR на старый merged SHA. Соответствие Issue↔PR движется только
  к более новому номеру; replay отдельных событий остаётся идемпотентным.
- Ранее замеченная Issue попадает во вновь связанную карточку из durable
  ledger даже после `since` cutoff; начальный Kanban status публикуется
  только в уже связанную Issue.
- Исходящие сообщения используют один versioned marker, durable cursor
  коммитится **после** GitHub ACK. Временный rate-limit и 401/403/5xx
  не закрывают очередь ложным `success`.
- Issue closure требует merge PR, полный именованный список required checks
  на merge SHA, acceptance evidence и завершённую карточку. По умолчанию
  `GKS_REQUIRED_CHECKS` пуст и `close` отказывает.

## Автоматическая проверка (в репозитории)

```bash
python -m pytest tools/tests/test_gks_integrated_flow.py -q
cd tools && python -m pytest tests/test_gks_*.py -q
```

`test_gks_integrated_flow.py` использует **настоящие временные SQLite базы**
для Kanban и coordination ledger и **подменяет только сетевые ответы GitHub**
через `httpx.MockTransport`. Покрыты:

| Участок | Ожидаемый результат |
| --- | --- |
| двухстраничный Issue/PR/comment poll | данные дочитаны до конца до cursor advance |
| GitHub HANDOFF → существующая Kanban-карточка | одно сообщение, source_event_id и delivery receipt |
| PR/CI → несколько карточек | отдельный receipt, без дублирования |
| запись во вторую карточку падает | `pending_events`, затем recovery после restart |
| поздний bind после `since` cutoff | ledger backfill, ровно одна доставка |
| Kanban status/blocker/branch → та же GitHub Issue | один versioned comment, без feedback loop |
| GitHub 401/rate limit при publish | не терять cursor; повтор после восстановления |
| merge и CI есть, acceptance отсутствует | `close` = отказ |
| acceptance есть, статус != done | `close` = отказ |
| все условия соблюдены в мок-транспорте | `close` допустим в тестовой имитации |

Фактическая зелёность этих проверок должна быть подтверждена **на последнем
SHA PR #235** в GitHub Actions, а не по прошлым зелёным PR #231/#232.

## Что этот checkpoint НЕ доказывает

Эти тесты **не** удостоверяют двустороннюю работу с настоящим Hermes
`~/.hermes/kanban/boards/me/kanban.db` на операторском хосте и live GitHub
API; не проверяют реальный host daemon/systemd, отсутствие ошибок файловой
системы, права токена конкретного исполнителя и реальную независимую приёмку.
Не был выполнен live оплачиваемый LLM-запрос; инструмент разработки не входит
в пользовательский runtime AI Multi Agent Workflow.

В runbook [§11.2](../github-kanban-sync-runbook.md) приведён операторский
прогон с существующей карточкой, отдельной тестовой Issue, sign-off, проверкой
доставки/дедуп/отказов и повтором после restart. Публиковать только ID,
SHA и обезличенные журналы; не раскрывать токены, query credentials или
реальные конфиденциальные тексты комментариев.

**Definition of Done #192 остаётся открытым** до подтверждения этого live
прогона, независимого review, merge **одного интегрированного PR** и аудита
финальных CI checks. Результат настоящего прогона добавляется отдельной
датированной записью evidence, не исправляется задним числом.
