# Реальный семистадийный native SDLC: read-only аудит доказательств (#11 / #8 / #254)

**Статус gate: NOT EXECUTED / NOT ACCEPTED.** Это runbook и исполняемый read-only verifier, не доказательство вызова OpenRouter. Автоматический CI использует scripted models и одноразовое состояние; он не доказывает платный live provider, проверенный Git object, защищённый restart или release signoff.

## Полномочия оператора и расходы

**Не запускать provider calls**, пока в защищённой среде оператора независимо не подтверждены все условия:

- Оператор явно согласовал конкретный live run и числовой максимум расходов **в USD**. Лимит токенов не равен денежному лимиту; native worker пока не резервирует USD атомарно между конкурентными workers. Настроить и независимо проверить лимит расходов учётной записи/ключа у провайдера, сохранить payment/usage evidence вне репозитория.
- OpenRouter key хранится только в приватном файле root/worker вне checkout (UID 10001, mode 0600). Отдельные orchestration key и gateway key, оба TLS CA files обязательны. Не передавать секреты в чат, CLI args, GitHub comments, скриншоты, traceback, отчёты или env dumps.
- Ограничить dispatch, provider tokens и tool calls. Первый trial — одна session и одна завершённая попытка; семь стадий — последующие отдельно наблюдаемые trials. Не использовать большие defaults autonomous dispatch overlay для первой платной проверки.
- Control и gateway работают в opt-in authenticated leased TLS deployment, а не dev Compose. Provider egress overlay разрешён реальным операторским egress allowlist; Docker bridge сам по себе не ограничивает выход только OpenRouter.
- Опубликованный граф — ровно семь упорядоченных пар Agent → automatic Contract Gate: research, architecture, implementation, tests, review, security, release-prep, с реальными контрактами и trusted profile bindings. Worker/gateway не подписывают независимый QA или human release approval. Native snapshot-backed worker сейчас отказывает в Git grants; отдельный operator-pinned Git worker — документированный opt-in путь к verified artifacts. Не ослаблять ограничение ради демо.

## Независимая подготовка без платных вызовов

На машине с защищённым checkout, Docker, Git и приватными credentials:

1. Выполнить документированный native worker CLI preflight для protected Compose overlay. Проверить отдельные secrets orchestration, gateway и provider, lease, TLS, profile bindings; provider requests не выполняются.
2. Выполнить preflight приватной конфигурации QA-controller и gateway, подготовить проверенный repository/attempt-worktree checkout отдельной read-only QA identity. Worker изолировать от прямого Git и QA signing credentials.
3. Подтвердить отказы backend: отсутствующие контракты, несовпадающие profile bindings, неавторизованный attempt lease, неподписанный QA, неавторизованный release approval.
4. Создать и опубликовать версионированный семистадийный граф в UI. Проверить preflight точного project/version и независимо сохранить ссылки run/version/contract в приватных записях оператора.
5. Только после подтверждённого hard spending cap провайдера и явного разрешения оператора запустить ограниченный native worker с малыми session, completion, total-token, tool-call и poll limits. Наблюдать реальные OpenRouter tool requests в аудите provider/account, trusted gateway ledger и server attempts. Не повторять автоматически аварийную попытку.
6. Провести независимые tester/reviewer/security QA отдельными service identities. Реальный человек отдельно разрешает release; completion и сообщённый worker Git SHA не могут его разрешить.

## Read-only проверка после запуска без доступа к провайдеру

Когда оператор выполнил предыдущие шаги и получил конкретные protected run ID и project ID, использовать существующий **native worker container**, в который уже смонтированы приватный orchestration read credential и trusted CA:

    python -m orchestration_server.native_live_acceptance \
      --run-id <OPERATOR_RUN_UUID> --project-id <OPERATOR_PROJECT_UUID>

CLI загружает только native orchestration TLS/key configuration через native_worker_bootstrap. Выполняет исключительно authenticated HTTPS GET; не импортирует/создаёт OpenRouter provider, не запускает worker, не вызывает tools, не подписывает QA, не разрешает release и не тратит tokens. Отклоняет plaintext HTTP, недоверенные TLS/proxy, неверную пагинацию, несовпадающие scopes и отсутствующие записи. Не передавать secrets в CLI args; IDs не являются секретами.

Auditor проверяет сохранённую опубликованную версию строго исполняемого линейного графа, все семь stage nodes и их contracts, ровно семь серверных completed tasks с исходными profile bindings и dependency handoffs, завершённую попытку Contract Gate на каждой стадии, Git artifact worker, связанный с completed attempt, совпадающее неизменяемое verified QA receipt с **тремя различными подписанными gate-run IDs** на задачу и отдельное approved release receipt обязательного оператора. Любой отказ — ненулевой exit и статический очищенный код без server payload.

Успешный машинный вывод намеренно помечен REVIEW_REQUIRED_EVIDENCE_PRESENT. Три поля остаются NOT_PROVEN_BY_READ_API: реальный provider request, trusted Git object readback и protected Compose/service restart. Даже успешный аудит не доказывает эти факты, payment/budget enforcement, Windows Docker Desktop support или безопасность production. Добавить независимые операторские evidence недостающих фактов, human/security review и CI SHA.

Только затем reviewer оценивает #11, #8, #254 и #256; read-only аудит никогда не выполняет merge, не закрывает Issues и не разрешает deployment.

## Offline регрессии

    python -m pytest services/orchestration-server/tests/test_native_live_acceptance.py -q

Негативные тесты моделируют чужой project, ручной/неопубликованный run, неверную version, некорректный graph, отсутствующие/повторные tasks, неверную dependency chain, непроверяемый Contract Gate, поддельный attempt/Git SHA, неподписанный QA, повторное использование gate-run IDs, отсутствие operator approval, неверную пагинацию и transport errors с secrets. Сеть, Docker, OpenRouter key и provider calls не нужны.

Read-only CLI также отправляет неаутентифицированный TLS GET и требует HTTP 401 до чтения run evidence: auth-disabled dev нельзя принять за защищённый стенд. Смешанные Git evidence rows разных run и циклические курсоры отклоняются, даже если одна запись выглядит валидной.
