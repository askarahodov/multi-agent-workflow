# #11 — автоматический независимый QA-контроллер

## Продуктовый путь

Отдельный, доверенный процесс `python -m quality_gates.native_qa_controller run`
выполняет QA **после** реального Git-коммита native worker. Он не запускает
платные модели и не зависит от Hermes. Контроллер не устанавливается и не
запускается внутри native LLM worker: пользовательские задачи, сообщения модели
и tool-call данные не содержат ADMIN-ключей QA.

Автоматический проход ограничен настройками оператора и делает следующее:

1. Читает из Orchestration REST API только `running` runs, ищет их
   `completed` tasks со статусом независимого QA `pending`.
2. Получает Git evidence задачи, **независимо** перепроверяет ref
   `refs/maw/attempts/<task-id>-<attempt-id>`, SHA, изменённые файлы,
   структуру коммита и блобы через `TrustedGitWorktreeStore.verify_artifact`.
3. Создаёт новый операторский detached Git checkout именно проверенного SHA.
   Не использует каталог, доступный для записи модели, как источник доверия.
4. Отдельным ADMIN-ключом запускает **три реальных** Quality Gates:
   `tester` (команда задана оператором), `reviewer`, `security`.
   Каждый QA run привязан к серверным task/attempt/SHA. Изменения tracked
   файлов в ходе проверки приводят к отказу.
5. Только после всех успешных QG gates получает HMAC-подписанный receipt,
   передаёт его в Orchestration API под своим другим ADMIN-ключом и
   перепроверяет сохранённое состояние `verified`.
6. Удаляет временный Git worktree. Красный gate, отсутствующий SHA, отказ API
   или ошибка очистки — **FAIL_CLOSED**: следующая зависимая стадия остаётся
   заблокированной. После рестарта уже подтверждённые задачи пропускаются.

При следующем poll native dispatcher продолжает семистадийный SDLC. Последняя
стадия тоже требует независимого QA, прежде чем run получит `completed`.

## Безопасная конфигурация

Необходимо три независимых компонента: Orchestration, Quality Gates и этот
QA-контроллер. QG и Orchestration должны работать с `AUTH_ENABLED=true` и
одинаковым секретом `QG_QA_ATTESTATION_KEY` /
`ORCH_QA_ATTESTATION_KEY`, скрытым от worker. Контроллер использует два
**разных** ADMIN-ключа сервисов, сохранённых в отдельных регулярных файлах
владельца процесса (`0600`, без symlink/hardlink).

Операторский Git repository и каталог QA checkout должны быть локальными,
иметь доверенное владение, а каталог QA — режим `0700`. QA-контроллер и QG
обязаны видеть **одинаковые абсолютные пути** внутри своих filesystem
namespace: при запуске в разных контейнерах обеспечьте отдельные mounts.
Готовый dev `docker-compose.yml` с `AUTH_ENABLED=false` не является
безопасным профилем этого режима; не направляйте его в общую сеть.

Тестовый subprocess QG получает отфильтрованный набор env без signing/API
credentials. Это **не** OS sandbox: тестируемый код должен работать в
отдельном доверенном контейнере с изолированным UID, без доступа к
секретам или Docker socket. До изоляции не используйте этот контроллер
для непроверенных многоарендных репозиториев.

Команда теста статична и принадлежит оператору, а не модели; в ней нельзя
передавать секреты. Для произвольных языков настройте реальную test matrix,
а не подменяйте тесты пустой командой.

## Пример для доверенной Linux-среды

Установите локальные first-party пакеты `shared`, `agent-management`,
`quality-gates`, настройте приватные сертификаты для HTTPS API. Создайте
каталог QA checkout вне рабочего каталога gateway.

```bash
export MAW_QA_CONTROLLER_ENABLED=1
export MAW_QA_ORCH_URL=https://orchestration.example
export MAW_QA_SERVICE_URL=https://quality.example
export MAW_QA_ORCH_ADMIN_KEY_FILE=/run/secrets/qa_orch_admin
export MAW_QA_SERVICE_ADMIN_KEY_FILE=/run/secrets/qa_service_admin
export MAW_QA_GIT_REPOSITORY=/srv/maw/operator-source
export MAW_QA_WORKTREE_HOME=/srv/maw/qa-worktrees
export MAW_QA_GIT_EXECUTABLE=/usr/bin/git
export MAW_QA_TEST_COMMAND_JSON='["python","-B","-m","pytest","-q","-p","no:cacheprovider"]'
export MAW_QA_MAX_POLLS=100
export MAW_QA_POLL_SECONDS=2
python -m quality_gates.native_qa_controller preflight
python -m quality_gates.native_qa_controller run
```

`preflight` проверяет локальную конфигурацию, но не сообщает об успешном
end-to-end. `run` ограничен конечным количеством проходов; не выполняет
автоматический бесконечный replay красных QA или платных tool-calls.

## Подтверждение

- `tests/native_agent_e2e/test_auto_qa_controller.py`: семь SDLC стадий,
  реальный Git и отдельный QG сервис, signed receipt, рестарт control-plane,
  отсутствие ручного JSON handoff, no replay и cleanup временных worktrees.
- `quality-gates/tests/test_tester_env_isolation.py`: тестовый subprocess
  не наследует подписывающий, операторский или провайдерский ключ.
- `tests/native_agent_e2e/test_signed_qa_handoff.py`: базовые негативные
  тесты signed QA и контрактных переходов.

Это **offline приёмка scripted модели**. Исходная #11 не может быть закрыта
без санкционированного live OpenRouter smoke, полноценного UI/Compose
доказательства на чистой машине и production sandbox тестового кода.


### Включение через Compose

Для отдельного подтверждённого TLS/QA профиля используйте [документ о native QA Compose](issue-11-secure-compose-ru.md) и `compose.native-qa-runtime.yml`. Базовый dev Compose с отключённым auth не допускается.


## Привязка QA evidence к Git attempt (#148, #149)

Автоматический QA-контроллер принимает успешный ответ `POST /api/v1/runs`
только при точном совпадении `task_id`, `gate`, `attempt_id` и `commit_sha`.
Quality Gates читает `attempt_id` и `commit_sha` из сохранённой
`GateRunGitScope` и включает их в ответ scoped run; неподписанные,
несовпадающие или неполные результаты не разблокируют следующий этап.

Перед отправкой независимого подписанного receipt в orchestration контроллер
повторно проверяет `task_id`, `attempt_id` и `commit_sha` receipt против
проверенного Git artifact. Сверка не заменяет серверную криптографическую
проверку подписи и независимые результаты трёх QA gates.


## Изоляция чтения QA run и evidence (#151)

`GET /api/v1/tasks/{task_id}/runs/{run_id}` возвращает данные только если сохранённый `GateRun.task_id` совпадает с `task_id` из URL. При несовпадении либо неизвестном `run_id` возвращается одинаковый HTTP 404 без evidence, Git attempt scope или commit SHA. Проверяется отдельно на уровне pipeline и настоящего ASGI HTTP API. Аутентификация не заменяет проверки принадлежности записи задаче.


## Терминальное состояние ошибочных GateRun (#153)

После фиксации `running` в БД любой exception во время исполнения gate, проверки Git HEAD/чистоты после выполнения либо сохранения evidence переводит созданную запись в `failed` с `finished_at` и безопасным обозначением класса ошибки в `summary`. API сохраняет ошибку HTTP 500 для вызывающего клиента, но `GET /api/v1/tasks/{task_id}/runs` позволяет увидеть окончательный failed run. Такие записи не могут использоваться для подписания независимого QA receipt. Ошибки до создания записи не создают ложный run; обрывы процесса вне Python exception требуют отдельного timeout/recovery механизма.
