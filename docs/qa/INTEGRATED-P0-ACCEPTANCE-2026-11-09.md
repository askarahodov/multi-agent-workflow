# Интеграционная приёмка первого запуска и native SDLC (P0, 2026-11-09)

**Источник:** PR #310, единая интеграционная ветка `feat/integrated-p0-user-journey`.
Содержит взаимосвязанные изменения исходных PR #301, #305, #306,
#307, #308. Проверки на отдельных source-PR **не принимаются** как доказательство
этого объединённого дерева.

## Входной пользовательский сценарий (реальный Compose, без платного LLM)

1. Собрать и запустить локальный dev Compose, дождаться healthcheck всех
   зависимых сервисов и проверить same-origin `/api/v1` proxy.
2. Создать проект и workspace в первом запуске. При отказе API
   agent-management список проектов должен оставаться доступным, без ложного
   результата успешного подключения.
3. Создать синтетического provider и ModelProfile через **Настройки**.
   Проверить HTTP 201/GET и сохранность после reload; ни один
   `/completions` не должен быть вызван. Проверить отрицательный POST 5xx и
   независимый сбой последующего GET, не показывая сохранённое как неуспешное.
4. Создать ограниченные ToolPolicy и отдельные developer/reviewer AgentDefinition.
   Проверить versioned PATCH/409 и запрет выбора write/shell/git/network policy
   для независимого reviewer. Проверить, что редактор подставляет закреплённые
   model/policy и блокирует отсутствующие ссылки.
5. В редакторе сохранить/publish immutable workflow и пройти серверный
   preflight. Дефектный контракт/graph не должен создавать run.
6. Выполнить подтверждённый POST опубликованной версии сначала из редактора,
   затем через **Запуски**. Проверить server run ID, задачи, reload.
   После успешного POST сбой независимого GET не должен отображаться как
   ошибка создания или вызывать автоматический повтор. Неизвестный результат
   POST требует сверки истории и идемпотентного ключа, не повторного платного
   вызова наугад.
7. Проверить журнал событий: по умолчанию существующий dev-mode; затем только
   для disposable CI явно включить **оба** ticket-флага, получить одноразовые
   WS/SSE билеты, событие, replay denial и запрет `api_key` в URL.
   При ошибке защищённого режима не переходить на long-lived URL credentials.

Сценарий: `apps/frontend/e2e/compose-acceptance.spec.ts` плюс локальный
`.github/workflows/quality-gate.yml`, backend pytest и frontend Vitest.
Работа с существующей базой пользователя, реальный OpenRouter ключ и расходы
**не входят** в этот сценарий.

## Offline native worker и независимое решение о выпуске

`tests/native_agent_e2e` использует настоящий HTTP leased worker, Git worktree,
SQL fencing, trusted gateway, серверный Contract Gate, отдельные QA subprocesses
и signed QA receipts. Модель **scripted**, а не живой OpenRouter. Положительный
семистадийный тест подтверждает checkpoint/restart и отдельный операторский
release approval.

Отрицательный тест провала tester обязан доказать сохранённое evidence именно
для правильной пары attempt/Git SHA и код завершения subprocess `1`.
Следующая зависимая задача остаётся pending; живой worker не делает второй
tool/model вызов; QA receipt выдавать нельзя, release approver получает 409,
worker/QA/admin — 403. После рестарта control plane блокировка сохраняется.

## Отдельные блокеры для настоящего production signoff

- **Не разрешено:** автоматический платный OpenRouter вызов без согласования
  с оператором, реальным credential и заранее заданным бюджетом.
- **Не доказано:** защищённый live Compose с OpenRouter → инструмент → Git
  artifact → Contract Gate → tester/reviewer/security → операторское разрешение
  релиза, включая отказ/переподключение и изменение прав во время попытки.
- **Не доказано:** что исправлен HTTP 500 именно в уже установленной базе
  пользователя; нужны резервная копия, redacted server logs, schema audit
  без модификации данных и проверка после deployment.
- **Нужно:** независимое review объединённого diff и security/QA approval,
  управление ключами, HA ticket-store и журналами proxy, rollback без
  long-lived credentials в URL. `main` и production не изменять до release gate.
- Исходные issue #11, #254, #256, #209 и #8 остаются OPEN до фактической
  приёмки их полных критериев; интеграция PR не означает их закрытие.

## Обязательный технический checkpoint

Все обязательные checks должны быть **SUCCESS на точном SHA интеграционного
PR**: `CI`, `Quality Gate` с Compose/Chromium, `Native agent cross-service E2E`,
`GitFlow Policy`, image/security и документационные проверки. Нельзя
использовать зелёный старый SHA, отложенный/пропущенный job либо результат
из отдельного PR как доказательство принятия интеграции.
