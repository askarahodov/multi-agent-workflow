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


## Этап 3: контролируемый supervisor для HTTP-worker

`NativeWorkerSupervisor` — библиотечный асинхронный контроллер
`NativeHttpWorker`, не отдельный сервис и не бесконечный демон.

```python
import asyncio
from orchestration_server.native_worker_supervisor import NativeWorkerSupervisor

shutdown = asyncio.Event()
supervisor = NativeWorkerSupervisor(
    trusted_remote_worker, max_polls=10,
    max_attempts_per_poll=1, poll_interval_seconds=10,
)
report = await supervisor.run(shutdown)
```

Свойства: каждый запуск имеет конечный лимит проходов (1–1000);
каждый проход ограничен попытками (1–100); при пустой очереди
не запускается runner; при первом `verification_failed` или ошибке
выполнение прекращается. Транспортные ошибки не поглощаются и не
вызывают автоматический повтор. `asyncio.Event` завершает
ожидание между проходами, `CancelledError` не перехватывается.

Этот этап **не** подключает платный LLM самостоятельно. Запуск
отдельного процесса, сетевые ключи, выделение доверенного workspace,
подписание полномочий и recovery остаются ответственностью будущего
native worker service. Внешний cron/оператор должен явно разрешить
каждый новый запуск; длительное автономное исполнение до #33/#38
не считается готовым.

```bash
cd orchestration-server
python -m pytest tests/test_native_worker_supervisor.py tests/test_native_http_worker.py -q
```


## Fairness ограниченной выборки workflow (#11)

NativeHttpWorker хранит непривилегированный server-issued pagination cursor между polls и сканирует следующую страницу активных workflow при каждом вызове `run_once`, сохраняя лимит `max_runs` на один poll. По достижении последней страницы цикл возвращается к первой. Это устраняет постоянное голодание задач вне первой страницы при большом количестве активных workflows. Некорректные cursor/pages отклоняются до claim/provider. Cursor не поступает из задачи или model tool call и не сохраняется между рестартами; после рестарта scan начинается с первой страницы.


## Опциональная автоматическая обработка новых задач (#11)

Дополнительный `compose.native-autonomous-dispatch.yml` заменяет preflight-only команду worker на явный `dispatch`: проверенная конфигурация вызывает собственный native leased worker, который опрашивает `GET /workflows/runs`, делает `claim` готовых задач, запускает native OpenRouter tool loop и передаёт результат Contract Gate. Сессия и суммарные успешные исполнения имеют жёсткие пределы (`MAW_NATIVE_DISPATCH_MAX_SESSIONS` 1..100 и `MAW_NATIVE_DISPATCH_MAX_COMPLETIONS` 1..100); в режиме dispatch batch size принудительно 1, а supervisor останавливается при достижении общего лимита и на первом failed/ambiguous attempt. При явном STOP сессия прекращается; нет безлимитного расходования LLM-токенов или автоповтора после неизвестного результата. Для запуска требуются защищённые private keys, gateway и включённые lease/contract/Git/QA режимы соответствующих overlays. Это opt-in эксплуатационный путь, а не доказательство live OpenRouter или полного UI acceptance.


## UI и native leased contracts (#11)

В разделе «Запуски и результаты» пользователь выбирает существующий контракт своего проекта или создаёт `summary` JSON Schema Contract Gate. UI передаёт `contract_id` с каждой задачей в `POST /workflows/runs`. Строгий leased orchestration отклоняет попытки запуска без контракта; это ожидаемое поведение, а не повод ослаблять backend-проверку. Само создание запуска не доказывает наличие запущенного worker: необходим включённый `compose.native-autonomous-dispatch.yml`, доверенная настройка provider и все защищённые overlays. Live OpenRouter и чистая UI-приёмка пока не подтверждены.


### Исправление starvation между диспетчерскими сессиями

В опциональном `dispatch` один `NativeHttpWorker` и его server-issued cursor живут на протяжении всех ограниченных сессий процесса: короткие сессии (`max_polls=1`) больше не сбрасывают обзор активных workflow на первую страницу. Единственный HTTP-клиент открывается после проверки лимитов и закрывается при выходе или ошибке. Глобальный бюджет успешных попыток и остановка на первом failed/ambiguous результате сохраняются. Перезапуск процесса обнуляет курсор, но не durable состояние задач в orchestration SQLite.


## Регрессионная приёмка UI-shaped native SDLC (#11)

`orchestration-server/tests/test_ui_native_restart_acceptance.py` исполняет настоящий FastAPI REST + file-backed SQLite сценарий: POST проекта, создание проектного JSON Schema Contract Gate, регистрация worker, запуск последовательных research→architecture задач тем же API, что использует UI, затем native leased dispatcher и чтение задач через REST после создания нового приложения/SQLite engine. Отдельный негативный тест доказывает, что leased запуск без `contract_id` отклоняется до работы модели. Scripted leased runner в тесте означает **offline integration**, а не вызов настоящего OpenRouter, настоящий Git tool-call или подтверждение UI браузером. Эти отдельные acceptance критерии остаются открытыми до реального операторского запуска с ключом и доказательствами.


### Task-page fairness внутри workflow (#11)

Помимо ротации страниц активных workflow, NativeHttpWorker сохраняет отдельный cursor просмотра задач для каждого обнаруженного run: на каждом poll запрашивается не больше `max_tasks_per_run` задач, следующий poll продолжает со следующей страницы. По достижении конца списка cursor сбрасывается. Это устраняет повторное сканирование первых N завершённых/заблокированных задач и позволяет достигнуть поздней pending задачи. Неизвестный, повторяющийся или malformed cursor приводит к fail-closed до claim и provider invocation. Как и прочие offline-тесты, это не заменяет фактический live OpenRouter E2E.


## UI native seven-stage SDLC template (#11)

Кнопка `Заполнить 7 стадий SDLC` в разделе «Запуски и результаты» формирует последовательный граф Research → Architecture → Implementation → Tests → Review → Security → Release preparation. Каждая стадия использует выбранный `contract_id`, а `depends_on` для каждой стадии после первой строго ссылается на предыдущую стадию. UI не генерирует QA-signature или human release approval: они остаются отдельными серверными/операторскими gate. Создание шаблона **не** запускает OpenRouter само по себе: для исполнения нужен явно запущенный native dispatcher и защищённый provider; полная live Compose приёмка остаётся отдельным критерием.
