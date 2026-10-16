# ADR-111: единый оркестратор, native worker и зависимости стадий

**Статус:** принято как промежуточное архитектурное решение для P0 #11. Не свидетельство завершения #11.

## Граница продукта

**Единый источник истины** для проектов, запусков, задач, попыток, контрактов, состояний и event log — `orchestration-server` и его собственная БД. Взаимодействие с моделью — `agent-management` / `Native Agent Loop`; выполнение файловых действий — отдельный защищённый gateway с отдельным durable tool ledger. Диспетчер `NativeHttpWorker` через HTTP опрашивает задачи и запрашивает атомарный claim; второй scheduler/kanban не создаём.

`tools/agent-orchestration/`, `hermes`, CAL и исторические скрипты `spawn-agent.sh` — **инструменты разработки самой платформы**. Они не импортируются, не собираются и не исполняются продуктовым native worker/сервером или UI. Их отдельная миграция может быть сделана без вмешательства в продукт. Сторонний CLI для конечного пользователя не требуется.

## Граф стадий

`POST /api/v1/workflows/runs` принимает `tasks[].depends_on` — индексы *ранее перечисленных* задач (0-based, максимум 16 на задачу), без циклов и дубликатов. Запуск атомарно сохраняет отдельные `task_dependencies` и задания внутри одного transaction. Эта **новая таблица** создаётся через `create_all` даже на ранее созданной SQLite базе и не требует разрушительной миграции колонок `tasks`.

После успешной контрактной проверки `submit` в **том же SQL transaction** добавляет к входу зависимых задач служебный список `_maw_upstream` с ограниченным summary и идентификатором предыдущей задачи. Этот список нельзя отправить через пользовательский `input_data`; некорректная или отвергнутая Contract Gate попытка не обновляет downstream. Это handoff metadata, а не доказательство независимого тестового gate или Git commit.

На этапе `launch_run` проверяются границы проекта: переданный `workspace_id` должен принадлежать `project_id` запуска; контракт задачи допускается только общий (`contract.project_id = null`) или принадлежащий тому же проекту. Чужой workspace/contract отвергается до commit, включая случай, когда чужой контракт обнаружен во второй или последующей стадии. В этом случае все уже подготовленные стадии и события откатываются одной транзакцией. Проверка существования ID без проверки его области действия недостаточна для native SDLC.

Только `OrchestrationEngine.claim_task` решает, можно ли захватить pending-задачу. Он отказывает до первого tool-call, если **любая** prerequisite-задача не завершена серверным Contract Gate со статусом `completed`, либо run не `running`. Назначения из браузера или модельного текста не могут снять это ограничение. Статусы `pending` для ещё закрытых зависимостью стадий показывают будущую работу; попытки не увеличиваются при отказе claim.

Пример стадий (демонстрационный, без автоматического заполнения контрактов):

```json
{
  "project_id": "<project ID>",
  "name": "SDLC",
  "tasks": [
    {"title": "Research", "contract_id": "<ID>"},
    {"title": "Architecture", "depends_on": [0], "contract_id": "<ID>"},
    {"title": "Implementation", "depends_on": [1], "contract_id": "<ID>"},
    {"title": "Tests", "depends_on": [2], "contract_id": "<ID>"},
    {"title": "Review", "depends_on": [3], "contract_id": "<ID>"},
    {"title": "Security", "depends_on": [4], "contract_id": "<ID>"},
    {"title": "Release preparation", "depends_on": [5], "contract_id": "<ID>"}
  ]
}
```

Доверенный worker получает на модельном **user**-уровне ограниченные `task.title`, `task.description`, `task.input_data` после успешного server claim. Ни lease, ни key, ни workspace root, ни tool policy, ни права на Git не берутся из данных задачи и не передаются в модель. Пользовательский текст не повышает уровень полномочий.

## Что не доказано и не реализовано этим этапом

- Нет полноценного per-task Git worktree и доверенного атомарного Git commit после файлового tool-call; `TrustedCommandExecutor` позволяет лишь read-only Git probes. Не выдавать простой file-write за Git commit.
- Handoff summary и порядок есть, но нет независимого Git diff/review/security evidence, human approval перед релизом. Каждый конкретный SDLC gate должен иметь серверный контракт, а не слепое доверие к заявлению модели.
- Нет гарантированного автономного live процесса в *основном* dev Compose: opt-in защищённый worker/gateway требует TLS, секреты и model budget. No paid smoke without operator approval.
- Путь `LLM → tool → LLM → Contract Gate` проверяется отдельным offline Native E2E; работа настоящего OpenRouter и полноценный unattended workflow до release-prep с commit остаются критериям открытого #11.
- Нельзя экспортировать существующие `tools/git_storage.py` с ambient env и unrestricted `git add/commit` в границу model-facing gateway без отдельного security-review.

## Validation

```sh
python -m pytest orchestration-server/tests/test_sdlc_dependencies.py agent-management/tests/test_trusted_fs_client.py -q
python -m pytest tests/native_agent_e2e -q
docker compose config --quiet
```

По умолчанию все компоненты работают без установки Hermes. Legacy каталоги разработческих инструментов остаются, но ни один из них не должен фигурировать в product Dockerfile entrypoint или native runner dependency closure.
