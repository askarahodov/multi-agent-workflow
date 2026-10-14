# Native worker — ограниченный первый этап (#33)

**Назначение:** платформа самостоятельно находит зарегистрированную задачу в БД и
передаёт её доверенному runner. `OrchestrationEngine` остаётся единственным
владельцем claim, retry и Contract Gate. Hermes не используется.

## Сценарий

1. `NativeWorker.run_once()` проверяет, что агент idle, и считывает ограниченное
   число запущенных workflow и pending tasks через `OrchestrationQueries`.
2. Задачи с ещё не наступившим `retry_at` игнорируются, как и terminal и
   занятые задачи. Пустая очередь не создаёт runner и не обращается к LLM.
3. Trusted `runner_factory(task)` создаёт замыкание с контрольной политикой,
   моделью, разрешённым workspace и отдельным durable tool ledger; поля task
   не могут повышать привилегии.
4. `run_native_task_attempt()` атомарно claim'ит задачу до начала runner,
   проверяет строгий JSON и передаёт его через Contract Gate в движок.
5. `run_batch(max_attempts=N)` ограничен N≤100. При первом неуспешном ответе
   прекращает проход, предотвращая быстрый цикл вызовов при quota wall, ошибке
   провайдера или некорректном output. Повтор возможен только новым
   вызовом из доверенного планировщика с учётом engine policy.

## Ограничения

- **Нет фонового daemon/polling через authenticated REST API.** Этот первый
  этап работает в процессе backend с контролируемым доступом к engine/queries.
  Переход к отдельному worker — следующая часть #33.
- **Нет shell/Git/HTTP:** current native tool dispatcher остаётся file-only до
  отдельного security gate #20.
- **Нет возможности самому создать workspace:** provisioning и разрешения
  должны быть доверенно определены до вызова runner.
- **Нет продвинутой recovery:** при отмене/краше восстановлением занимается
  `OrchestrationEngine.recover()`, но неоднозначные `CLAIMED` в tool-ledger
  требуют отдельной сверки side effects; они не повторяются автоматически.
- **Нет live LLM acceptance:** тесты используют fake runner и реальный SQLite.
  Они доказывают worker discovery/claim/contract semantics, не производственный
  непрерывный SDLC.

## Проверить

```bash
cd orchestration-server
python -m pytest tests/test_native_worker.py -q
```

Критерий слияния: CI и Quality Gate зелёные, нет нового вызова provider при
пустой очереди, две competing worker-instance не исполняют одну задачу дважды,
ошибка контракта останавливает текущий batch.


## Этап 2: аутентифицированный REST-клиент worker

`orchestration_server.native_http_worker.NativeHttpWorker` осуществляет один
**явно вызванный** HTTP-проход по стабильному API:

- `GET /api/v1/workflows/runs?status=running`
- `GET /api/v1/workflows/runs/{id}/tasks`
- `POST /api/v1/tasks/{id}/claim` с доверенным `agent_id`
- `POST /api/v1/tasks/{id}/attempts/{attempt_id}/submit` или `fail`

Клиент требует API-ключ и HTTPS; HTTP допускается только при явно
включённом режиме loopback на `127.0.0.1` или `::1`.
Перенаправления и окруженческие прокси отключены; не передаются URL
с userinfo/параметрами. Пагинация, количество задач и `run_batch()`
ограничены, `retry_at` возвращается через публичный TaskResponse.
Два worker конкурируют атомарным `claim` на стороне сервера.
Нет нового `runner` до подтверждения успешного claim.

Доверенное приложение передаёт корутину `runner(task, attempt_id)`.
Она обязана самостоятельно выделить контролируемый workspace, настроить
права, persisted tool ledger, лимиты и модель. Запрос от модели НЕ
может выбрать runner или расширить доступ.

Клиент по умолчанию **не запускает постоянный цикл**, не содержит
провайдерских ключей, Docker socket или фоновых таймеров. Его нельзя
использовать как готовый production-демон без аутентифицированного
provisioning/recovery (#33). Результаты ошибок обезличены; при
неудачном запросе не проводится автоматический повтор выполнения
побочного действия. После отмены/краша `CLAIMED` reconciliation
остаётся отдельным gate. Значение стоимости LLM: UNKNOWN до
достоверного учёта расходов.

Проверить:

```bash
cd orchestration-server
python -m pytest tests/test_native_worker.py tests/test_native_http_worker.py -q
```

Тесты запускают **настоящий FastAPI сервер внутри ASGITransport** с
SQLite-БД, выполняют Contract Gate через HTTP и проверяют пустую
очередь, попытку до срока retry, конкуренцию, недействительный JSON,
ошибки провайдера, 401, 307 и запрет незащищённого HTTP.
