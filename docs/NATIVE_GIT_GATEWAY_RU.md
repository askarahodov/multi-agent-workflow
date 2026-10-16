# Git artifacts в Native Worker: приёмка #11

## Включение отдельным профилем

Штатная установка **по умолчанию ничего не коммитит**. Новый Git-контур включается только совместным использованием файлов:

```cmd
docker compose -f compose.trusted-sqlite-control.yml -f compose.native-worker-runtime.yml -f compose.trusted-git-artifacts.yml --profile trusted-sqlite-control --profile native-worker-runtime config --quiet
```

Работает в Linux-контейнерах (команду можно выполнить из Windows CMD). Не объединять с основным небезопасным dev Compose. Настроить `MAW_GATEWAY_GIT_SOURCE_HOST_DIR` (предварительно проверенный локальный Git репозиторий с настоящим `.git`, принадлежащий service UID 10002) и `MAW_GATEWAY_GIT_WORKTREE_HOST_DIR` (существующий приватный каталог `0700` для UID 10002), а также ключи, CA и настройки ограниченного native worker из `docs/NATIVE_WORKER_ACCEPTANCE_RU.md`. Git-пути монтируются **только** в trusted-gateway, не в worker, не в модель и не в контейнер оркестратора. Предусмотрен pinned `/usr/bin/git` внутри gateway-образа.

### Порядок работы

1. NativeHttpWorker получает от оркестратора task, claim и lease.
2. TrustedLeasedGatewayRunner с явным `MAW_TRUSTED_GIT_ENABLED=1` вызывает аутентифицированный HTTPS `/v1/git/provision`, передавая **только** серверные run/task/attempt/agent IDs и lease.
3. Gateway подтверждает живой lease через `TrustedSqliteAttemptFence`, создаёт единственный detached worktree этой попытки под операторской директорией. Повторный provision запрещён.
4. Модель видит прежние `read_file`/`write_file`. Gateway привязывает `write_file` к `out/**` конкретной попытки и к тому же durable tool ledger; модель не может выбрать другой workspace или вызвать Git-команду.
5. После успешного Agent Loop (не после произвольного model tool-call) trusted runner запрашивает `/v1/git/commit`. Gateway в рамках SQLite fence выполняет проверку файлов, at-most-once Git commit и фиксирует отдельный ref `refs/maw/attempts/<task>-<attempt>`. Перед переводом durable ledger в `SUCCEEDED` gateway повторно читает **Git ref и сохранённые объекты**: проверяет SHA, ровно одного родителя, изменённые пути только в `out/**`, допустимые blob modes и суммарный размер не более 4 MiB. При несовпадении остаётся `CLAIMED` и требуется ручной разбор; повтор commit запрещён.
6. SHA и имена файлов из trusted gateway передаются worker в отдельном поле `git_artifact` при `submit` — **не внутри JSON модели**. После положительного Contract Gate оркестратор атомарно сохраняет запись в таблицу `task_git_evidence`. При отклонённом контракте SHA в таблицу не переносится.
7. `GET /api/v1/tasks/<task-id>/git-evidence` возвращает SHA, список путей и `provenance: worker_reported`. Это только отчёт trusted worker, **не** независимое подтверждение Git SHA сервером. Нельзя использовать как release approval, QA attestation или факт публикации в remote.

### Отказы и безопасность

- По умолчанию `MAW_GATEWAY_GIT_ENABLED` не задан: `/v1/git/*` возвращает 404, модель не получает Git tool.
- Для всех операций нужен доверенный HTTPS origin и приватный `X-Gateway-Key`. Lease должен быть активен. Ни Git argv, ни путь к репозиторию, ни текст commit не принимаются от модели.
- При разрыве соединения после commit, тайм-ауте, сбое чтения Git-объектов или записи в ledger попытка остаётся неоднозначной. **Никаких автоматических повторов**.
- `TrustedGitWorktreeStore.verify_artifact(task_id, attempt_id, expected_sha=..., expected_paths=...)` выполняет read-only проверку сохранённого Git объекта, даже если detached worktree уже удалён. Это локальная проверка **в том же доверенном gateway**, не server-side аттестация: `provenance: worker_reported` не меняется, `release approval` из неё не следует.
- Опасные имена, ссылки, специальные файлы и превышение лимитов отклоняются; никакого push, fetch и merge в основной проект.
- Таблица `task_git_evidence` аддитивная, старые задачи и неизменный API работают в режиме без Git.
- Режим co-located SQLite, не PostgreSQL и не многомашинный production trust.

### Проверка в CI

```sh
python -m pytest tests/native_agent_e2e/test_git_worktree_commit.py tests/native_agent_e2e/test_remote_git_artifact_flow.py -q
python -m pytest tests/native_agent_e2e -q
python -m pytest tests/native_agent_e2e/test_seven_stage_native_sdlc.py -q
```

Тест использует настоящий Git, file-backed SQLite, аутентифицированный API и HTTP transport, но предсказуемый offline streaming model. Не требует Hermes или оплаченного OpenRouter.

**Семистадийный offline acceptance (добавлено в #11):** `test_seven_stage_native_sdlc.py` создаёт run через аутентифицированный REST API, с настоящими lease, SQLite, worktree, HTTPS ASGI gateway и Git. NativeHttpWorker по очереди выполняет семь стадий `research → architecture → implementation → tests → review → security → release-prep`; на каждой стадии модельный сценарий вызывает `write_file`, trusted gateway создаёт отдельный commit, сервер выполняет JSON Schema Contract Gate. Между третьей и четвёртой стадией control plane пересоздаётся поверх той же БД, а затем GET API подтверждает сохранение статусов, handoff и worker-reported SHA. Это **не** проверка реальной модели, браузерной автоматизации, самостоятельного QA-runner или одобрения релиза человеком: поток LLM намеренно scripted, а отдельные независимые testing/review/security gates остаются незавершёнными.

**Открытые критерии #11/#8:** независимые test/review/security gates, release-prep и подтверждение человеком, реальный санкционированный OpenRouter smoke, полная воспроизводимая многосоставная SDLC приёмка и криптографическая/server-side Git ref verification. Этот этап не равен `SDLC_MVP_ACCEPTED`.
