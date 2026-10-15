# Native Worker: доверенная точка запуска (этап #54)

Первый этап отделяет **проверку конфигурации и конечный запуск** от
будущего операторского daemon/Compose процесса.

Реализация: `orchestration_server.native_worker_bootstrap`.

## Предусловия

- `MAW_NATIVE_WORKER_ENABLED=1` — обязательное явное включение.
- `MAW_NATIVE_WORKER_LEASE_REQUIRED=1` — не допускать legacy
  unauthenticated tool runner.
- `MAW_NATIVE_WORKER_SERVER_URL` — чистый HTTPS origin без credentials,
  path, query и fragment.
- `MAW_NATIVE_WORKER_API_KEY_FILE` — абсолютный путь к приватному файлу
  с правами 0600 и владельцем процесса. Symlink и hardlink запрещены.
- `MAW_NATIVE_WORKER_AGENT_ID` — доверенная идентичность агента.
- `MAW_NATIVE_WORKER_MAX_POLLS` — 1–1000, обязательно.
- `MAW_NATIVE_WORKER_POLL_SECONDS` — 0.01–3600, обязательно.
- `MAW_NATIVE_WORKER_BATCH_SIZE` — 1–100, по умолчанию 1.

Только для явного локального теста: `MAW_NATIVE_WORKER_DEV_LOOPBACK_HTTP=1`
допускает HTTP на `127.0.0.1` или `::1`, но не на произвольном IP.

`config_from_env()` проверяет эти условия, не создавая HTTP клиент,
не запуская provider и не расходуя токены. Значение ключа не должно
печаться в логах или `repr` конфигурации.

`run_trusted_worker(config, leased_runner=..., stop_event=...)`
принимает **только доверенный явно переданный** `leased_runner`,
использует `NativeHttpWorker(require_lease=True)` и уже существующий
конечный `NativeWorkerSupervisor`. Отсутствие ready задач не
создаёт модельных запросов. Исключения исполнения не проглатываются,
поэтому после сбоя нельзя автоматически продолжить расходы/side effects.

## Не реализовано этим этапом

Это **не** самостоятельный CLI daemon. Provider и gateway runner пока
требуют доверенной инъекции. Opt-in Compose с TLS, OS-политикой
изоляции, собственным startup/shutdown, readiness и cross-process
crash тестами остаётся задачей #54.

Не объявлять #33/#38 закрытыми до полного Compose E2E и проверки
неоднозначных `CLAIMED` после restart.

## Операторская предварительная проверка

После подготовки приватного ключа и обязательных переменных окружения
можно выполнить **только локальную валидацию**, не включая выполнение:

```sh
python -m orchestration_server.native_worker_cli preflight
```

Команда возвращает код `0` при корректной **локальной** конфигурации
либо `2` при ошибке. Сообщение об ошибке не содержит ни токена, ни
путей к приватным файлам. Для Windows CMD команда аналогична, если
Python и зависимости установлены: `python -m orchestration_server.native_worker_cli preflight`.
`preflight` **не обращается к API**, не проверяет доступность gateway,
не запускает provider и не выполняет задачи. Команды `run` здесь нет:
нельзя ошибочно обойти требование доверенной инъекции runner.

Это контрольная точка, а не завершение #54: последующему этапу
необходим изолированный исполняемый worker + gateway, TLS и Compose E2E.
