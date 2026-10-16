# Native Agent Loop — журнал и Contract Gate (Issue #21)

Штатный bounded Agent Loop расположен в `agent-management/agent_management/agent_loop.py`. Поток OpenRouter собирается `providers/streaming.py`; непроверенные вызовы инструментов передаются только через `NativeFilesystemDispatcher` и его доверенные дополнительные инструментальные executor'ы. Задача оркестрации **не закрывается** самим LLM-ответом.

## Последовательность выполнения

1. Доверенный worker выбирает профиль роли, workspace и параметры модели и вызывает `run_agent_loop` с лимитами `max_turns`, `max_total_tokens`, `max_tool_calls`, `timeout_seconds`.
2. Провайдер возвращает полный поток с обязательными `usage` и `done` до любого инструментального действия. Оборванные потоки и неверный учёт токенов блокируют исполнение.
3. Инструмент проверяется на execution boundary; ledger фиксирует correlation ID и отклоняет повторы. Отказ инструмента преобразуется в безопасный tool-result.
4. Итоговый ответ возвращается в `orchestration_server.native_bridge.run_native_task_attempt`; только `OrchestrationEngine.submit` проводит Contract Gate и может перевести task в completed.
5. При невалидном JSON и ошибке выполнения bridge вызывает fail_attempt. Восстановление и retry определяет engine, а не модель.

## Журнал событий

Опциональный `AgentEventJournal` записывает в доверенный SQLite-файл вне workspace минимальный след выполнения по `run_id`: номер turn, тип события, нормализованный результат, число provider-токенов и `cost='UNKNOWN'`. Не сохраняются prompt, сырой текст модели, содержимое инструментов, пути файлов, URL, ключи или сообщения ошибок. Журнал открывается повторно после рестарта. Он **не заменяет** per-tool `SqliteToolLedger`, persistent orchestration attempt или Contract Gate.

Для установки журнала control plane создаёт его в каталоге, недоступном для изменения агентом, и передаёт экземпляр через `run_agent_loop(..., journal=journal)`. Поставщик/LLM не может указывать путь к базе или `run_id`.

## Проверки (Linux / Docker)

```sh
python -m pytest agent-management/tests/test_agent_loop.py agent-management/tests/test_agent_journal.py -q
python -m pytest orchestration-server/tests/test_native_bridge.py -q
```

При использовании Windows CMD выполняйте этот набор внутри Linux-контейнера Docker Compose: POSIX filesystem safety boundary не переносится в native Windows режим путём ослабления policy.

Онлайн-проверка с настоящим OpenRouter ключом не включена в бесплатный CI: её следует запускать только по отдельному разрешению и с ограниченным бюджетом.


## Streaming hardening и достоверность usage

Клиент OpenRouter использует `POST /chat/completions` с SSE и `stream_options.include_usage=true`. `StreamAssembler` собирает fragments инструмента только после завершения потока; перед диспетчером действует ограничение размера SSE-события и аргументов, запрет повторного `usage`, дублирующихся JSON-ключей, `NaN/Infinity`, конфликтующих `finish_reason` и невалидных идентификаторов. Ответ и параметры инструмента не являются доверенной командой до policy enforcement.

`AgentEventJournal` записывает **проверенную** информацию об использовании токенов при получении события `usage`, а не только после `[DONE]`. Если OpenRouter затем вернул ошибку 429/5xx, оборвал SSE-поток или вызов отменён, токены, уже подтверждённые провайдером, сохраняются в SQLite с cost=`UNKNOWN`; состояние попытки остаётся ошибочным, task не переводится в completed. Если провайдер не прислал `usage`, точный расход неизвестен — число токенов нельзя выдумывать.

Текст ответов, аргументы инструментов, prompt, HTTP body с ошибкой и секреты в telemetry не сохраняются. Полноценное списание средств и онлайн-приёмка требуют отдельного ключа и разрешённого бюджета; offline-тесты не утверждают, что запрос к настоящему OpenRouter состоялся.

Для воспроизведения streaming и failure-сценариев:

```sh
python -m pytest agent-management/tests/test_streaming.py agent-management/tests/test_agent_journal.py agent-management/tests/test_agent_loop.py -q
python -m pytest tests/native_agent_e2e -q
```
