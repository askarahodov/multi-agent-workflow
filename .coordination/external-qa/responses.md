# Ответы внешнего независимого QA (OWNER: ChatGPT)

Этот файл обновляет **только внешний QA через GitHub connector**. Ответы добавляются в конец и ссылаются на ID запроса в `requests.md`. Никакие записи сами по себе не изменяют локальный Kanban.

## QA-RSP-20261013-BOOTSTRAP
- request: NONE (информационный стартовый checkpoint)
- local_review_task: t_2eaa57b1 (EXT-REVIEW-001)
- verdict: INFO
- verified_against: GitHub `main` commit `c08057be75f61032cfdd6cd0b22a806b700816c5`; сообщения координатора в чате по локальному `b2b31736f0044a768dae7abdc5573b6588b7c7ef`
- scope: read-only, без доступа к локальной Kanban-БД, текущим незапушенным файлам, `gateway.log`, `/tmp`, `~/.hermes/config.yaml`

### Текущие выводы

1. **QA-01 / HTTP 429: OPEN.** Координатор сообщил, что раньше повторялись `spawned=1 → reaped zombie`. Настройки cooldown и mock 429 тест (`exit 0`) добавлены, но реальное прекращение respawn не подтверждено. Требуется проверка журнала живого диспетчера и поведения после восстановления квоты.
2. **Архитектура t_005a92be: REVIEW, НЕ ПРИНЯТА.** Статус `review` подтверждён только отчётом координатора. Для независимого verdict нужны доступные Git diff, контракты компонентов, ADR и тестовые доказательства.
3. **Продуктовая автономность без Hermes: НЕ ДОКАЗАНА.** На GitHub `main` `tools/agent-orchestration/scripts/spawn-agent.sh` и `tools/agent-orchestration/orchestration_tools/kanban_tools.py` содержат зависимости от Hermes. Необходимо определить, входят ли они в продуктовый runtime; затем проверить запуск конечной платформы в среде без Hermes.
4. **Риск конфликтующих источников истины.** `PLAN.md` описывает CAL с отдельными scheduler/kanban/store, тогда как `orchestration-server/` уже реализует собственный lifecycle задач. Нужен архитектурный контракт о границе инструментария разработки и конечного продукта.
5. **Риск противоречивых требований к хранилищу.** `docs/domain-architecture.json` предполагает обязательный PostgreSQL, но `orchestration-server/orchestration_server/config.py` и `agent-management/agent_management/config.py` по умолчанию используют SQLite. Обязательность PostgreSQL в локальном MVP необходимо согласовать.

### Что передать для следующего полноценного ответа

- Внести в `requests.md` `QA-REQ-20261013-001`.
- Указать реальные ветку и SHA артефактов `t_005a92be`, либо дать санитизированный diff.
- Добавить ссылку на run CI и релевантные тестовые логи.
- Для QA-01 приложить санитизированные выдержки `gateway.log` **после применения конфигурации и перезапуска/перечитывания dispatcher**, плюс число spawn за окно наблюдения и время проверки.

Следующий статус `APPROVED` или `CHANGES_REQUESTED` будет выдан только после проверки запрошенных доказательств. Не менять автоматически статусы локального Kanban.

---

## QA-RSP-20261013-HANDOFF-BLOCKED
- request: `QA-REQ-20261013-001` (сообщён координатором, **отсутствует в удалённом `requests.md`**)
- local_review_task: `t_2eaa57b1` / `EXT-REVIEW-001`
- architecture_task: `t_005a92be`
- verdict: **BLOCKED — evidence not published**
- verified_against: GitHub `askarahodov/multi-agent-workflow`, ветка `coord/external-qa`; GitHub `main` на `c08057be75f61032cfdd6cd0b22a806b700816c5`
- mode: независимый read-only review, без изменений локального Kanban, архитектурной ветки и active worktrees

### Проверенные факты

1. `.coordination/external-qa/requests.md` в удалённой ветке содержит только начальный шаблон и **не содержит** записи `QA-REQ-20261013-001`. Отчёт о локальном файле на 101 строку не означает успешный `git push`.
2. Коммит служебного worktree `275bcc1`, указанный координатором, GitHub не находит: он пока локален либо не доступен удалённому репозиторию.
3. Реф `wt/t_005a92be` отсутствует в GitHub (404). Коммит `b2b31736f0044a768dae7abdc5573b6588b7c7ef` доступен, однако GitHub compare показывает, что он **предок текущего main**, отстающий на 2 коммита (не содержит отдельного видимого delta worktree относительно main).
4. Статус `review` в локальной Kanban и mock-тест HTTP 429 известны лишь из предоставленного координатором отчёта; live-диспетчер и локальные логи непосредственно не проверены. `QA-01` остаётся **OPEN**.

### Минимальное действие координатора

Опубликовать **только `requests.md`** поверх реального удалённого `coord/external-qa`, не затрагивая `responses.md`, README, main или агентские worktrees.

Безопасный способ при divergence:
- Сохранить копию подготовленного локального `requests.md` вне worktree.
- `git fetch origin coord/external-qa`.
- Создать **новый временный служебный worktree** на `origin/coord/external-qa` с уникальной временной веткой, не переписывая существующий worktree.
- Перенести в нём только безопасно очищенный от секретов `QA-REQ-20261013-001` в `requests.md`, добавить и зафиксировать `requests.md` одним коммитом.
- Выполнить обычный fast-forward push `HEAD:coord/external-qa`, **без force**.
- Проверить полученный файл на GitHub. После успешной передачи перейти на актуальную удалённую ветку для следующих handoff.
- Опубликовать отдельную review-ветку или санитизированный diff/архитектурные артефакты, если они есть только в локальном worktree. Не перезаписывать `main`.

### Условия возобновления ревью

- Запрос `QA-REQ-20261013-001` действительно виден в GitHub;
- артефакты, актуальный git diff и результаты тестов доступны по указанным источникам;
- для закрытия `QA-01` приложены данные live-проверки отсутствия циклов `spawn/reap` после применения cooldown.

**Не переводить `t_005a92be` в `done` на основании данного сообщения.** Этот ответ — обнаружение блокера публикации, не приёмка архитектуры.

---

## QA-RSP-20261013-INDEPENDENT-DEVELOPMENT-CHECKPOINT
- request: direct owner authorization in ChatGPT (local agents rate-limited)
- mode: isolated GitHub development; no access to local Kanban/worktrees
- verdict: **CI and packaging improvements integrated; Compose smoke pending**

### Merged work
1. PR #12 `https://github.com/askarahodov/multi-agent-workflow/pull/12` -> main commit `91d032c813c1e8fa0f9d1830ba2b9610f8600575`. Fixes malformed backend pip installation and includes OpenAPI validator; GitHub Actions run `38386526197` passed all 9 jobs.
2. PR #14 `https://github.com/askarahodov/multi-agent-workflow/pull/14` -> main commit `cfdc94e397c7c2656161d66eeb29501b17d35fb5`. Removes absolute host path from Python packaging, explicitly declares local `maw-shared` dependency, declares `cryptography`, adds packaging CI job and Windows CMD/Linux installation docs; run `38401064741` passed all 10 jobs, including packaging install and `pip check`.

### Pending work
- PR #6 `https://github.com/askarahodov/multi-agent-workflow/pull/6`: Compose localhost ports, Vite proxy and local settings; added `.github/workflows/compose-smoke.yml` on head `3fe121ad5f5b29801e134ade65d3c9589b8c79b3`. Smoke execution not yet verified; **do not claim Docker Compose works until actual build/health check passes**.
- Product autonomy/E2E and QA-01 HTTP 429 remain unverified; no local runtime changes made.
- No local tasks, Kanban state or active agent worktrees were changed.

### Handoff
Coordinator: reflect these two completed GitHub changes in the local Kanban if they overlap existing CI/packaging tasks; do not duplicate tasks. For architecture approval, still publish `QA-REQ-20261013-001` and versioned artifact evidence.

---

## QA-RSP-20261013-COMPOSE-GREEN
- request: direct user authorization to develop independently while local agents are rate-limited
- local_review_task: t_2eaa57b1 (read-only QA handoff)
- verdict: **PASS for portable Python packaging, CI setup, and Linux Docker Compose smoke; NOT a pass for autonomous SDLC**
- verified_against: GitHub `main` commits `91d032c813c1e8fa0f9d1830ba2b9610f8600575`, `cfdc94e397c7c2656161d66eeb29501b17d35fb5`, `d3b9cacdc24a48f48aed571135c394677fcae86d`; CI runs `38386526197`, `38401064741`, `38402962928`

### Implemented and merged
1. PR #12: repaired malformed pip installation and added OpenAPI validator to backend CI; 9/9 jobs PASS.
2. PR #14: made first-party Python package dependencies portable (no absolute `file:///mnt/data/...`), established `maw-shared==0.1.0`, fixed cryptography dependency, added clean packaging CI and Windows CMD/Linux instructions; 10/10 jobs PASS.
3. PR #15: rebuilt local Compose fixes from clean main, localhost-only configurable ports (Orchestration host :18000 by default), corrected Vite upstream and backend DB URLs, and fixed a verified missing `shared` dependency in quality-gates Dockerfile and pyproject. Added conditional Compose smoke as required CI job.
4. PR #6 is **closed as superseded by PR #15**, without merge.

### Verified Compose evidence
- GitHub Actions Quality Gate run `38402962928`: **11/11 jobs success**.
- Docker configuration validated; six Docker services built and started.
- Job `115315044076` printed: `All six Compose services are healthy`.
- HTTP smoke passed on 127.0.0.1:18000, :8001, :8002, :8003, :5173.
- CI ran on a GitHub-hosted Linux runner, **NOT Windows**, so Windows Docker Desktop/CMD requires a separate host validation.
- No paid provider/LLM requests, local Kanban writes or Hermes runtime calls were made.

### Outstanding
- QA-01 rate-limit respawn on **local Hermes developer dispatcher** remains unverified; this CI work does not address it.
- Architectural task `t_005a92be` not independently approved; local worktree diff and request `QA-REQ-20261013-001` still need successfully published evidence.
- The **autonomous end-to-end software development loop** is not verified by these health checks; full SDLC E2E remains open.
- Local coordinator should reconcile its own Kanban task assignments with these merged changes once provider quota returns; do not duplicate or auto-close local tasks merely from this message.

---

## QA-RSP-20261013-HERMES-DISPATCHER-INCIDENT
- request: coordinator incident report provided by project owner in ChatGPT
- category: independent QA / emergency mitigation recommendation
- verdict: **P0 — STOP USELESS SPAWNS FIRST; then minimal root-cause fix and regression tests**
- scope: локальный Hermes dispatcher для команды разработки, **НЕ** runtime конечного продукта AI Multi Agent Workflow
- note: данная запись — QA-рекомендация. Изменение локального gateway/config/board должно быть санкционировано владельцем и выполнено локальным координатором; внешний ChatGPT их не изменял.

### Основания: подтверждено координатором, непосредственно не проверено внешним QA
- `suppress_respawn_on_rate_limit` и `rate_limit_retry_after_seconds` не читаются работающим Hermes-кодом; `rate_limit_cooldown_seconds` используется как переменная окружения `HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS`, а не как заявленный YAML-ключ.
- `dispatcher_rate_limit_fix.py` находится только в `/tmp` и не интегрирован в активный dispatcher.
- `gateway.log`: `spawned=1 → reaped zombie` каждые ~5–6 мин при `HTTP 429 free-models-per-day-high-balance`; нет роста consecutive_failures.
- `t_26938b85`: `workspace_kind=dir`, `workspace_path=None`, 2824 неуспешных прогона; отдельная бесконечная петля, которую восстановление OpenRouter-квоты не исправит.
- На момент отчёта локальный gateway был запущен до изменения конфигурации; reload/restart с новыми настройками не доказан.

### Рекомендуемый санкционируемый план в строгом порядке
1. **Немедленная обратимая mitigation (локальный координатор):** сохранить конфигурацию и снимок активных задач/воркеров; проверить, какой реальный параметр кода отключает **только автоматический dispatcher**. При отсутствии работающих важных процессов временно отключить dispatch, безопасно перечитать конфиг или перезапустить gateway, если это обязательно. Не отключать всё без проверки и не уничтожать worktree.
2. Проверить `gateway.log` на отсутствие новых циклов `spawn/reap` в течение минимум 20 минут; приложить метрики `spawn_count`, `rate_limited`, состояние gateway и число активных задач до/после. Отсутствие новых событий должно быть обусловлено реально отключённым dispatch, а не падением всего gateway.
3. Для `t_26938b85` при разрешении владельца установить `blocked` с явной причиной `invalid_workspace: dir requires workspace_path`. Перед изменением сохранить исходный статус и запись для возможного восстановления.
4. **Минимальный долговременный фикс:** при `quota_exhausted` парковать соответствующую работу без нового spawn до доказанного времени восстановления квоты, если оно известно, или до явной проверки; различать quota/auth wall, обычные transient 429 и execution failure. Не переключать на платный провайдер без разрешения. На создании/назначении задачи валидировать `workspace_kind=dir` ↔ `workspace_path`; не пытаться spawn при некорректной конфигурации. Удалить недействующие config-ключи либо документировать только реально читаемый механизм.
5. **Регрессионная приёмка:** fake provider с дневным free-cap, запуск 3+ циклов без нового spawn; восстановление провайдера и **ровно одна** повторная попытка без дублирования побочных эффектов; `dir + NULL` reject при создании; перезапуск с сохранением состояния и worktree.
6. Возобновить dispatch **только** после тестов/проверки квоты, вручную подтверждённой оператором. Не предполагать, что точное время сброса всегда совпадает с заявленным временем 03:00 МСК.

### Архитектурное ограничение
Изменения `kanban_db_dispatch.py` относятся к **внешнему инструменту разработки Hermes**, не к автономному продукту. Не переносить Hermes API, профили, БД или gateway в целевой runtime. Если требуется много работы в чужом диспетчере, предпочесть восстановление минимальной работоспособности и продолжить разработку собственного dispatcher.

### QA статус
- Исправление циклов rate_limit **OPEN/FAIL** до live-проверки.
- Невалидная задача `t_26938b85`: отдельный **P0**.
- Архитектурная приёмка `t_005a92be`: **не принята** без опубликованных delta/ADR/tests.
- Содержимое прежнего QA-01–QA-05 и обозначения в новом отчёте отличаются; координатор должен использовать **ID локальной задачи + точное название дефекта**, чтобы избежать переназначений по совпадающему номеру QA.

Ответ исполнителя должен содержать конкретные действия, изменённые файлы, diff, тесты, журналы до/после, сведения о безопасном рестарте и статус `t_26938b85` / `t_005a92be`. Не выдавать `mock exit 0` за доказанный live fix.

---

## QA-RSP-20261013-PAID-PROVIDER-RECOVERY
- trigger: пользователь сообщил, что вручную переключил локальных агентов на платную модель, выполнение возобновилось.
- verdict: **WORKERS UNBLOCKED (по сообщению владельца); ROOT-CAUSE FIXES NOT PROVEN**.
- scope: рекомендации координатору для локальной команды; ChatGPT не читал локальную БД, не перезапускал gateway и не менял task/worktree.
- github-main-snapshot: `ca77e4565f071f95049541193ad655914677a9f7` (после 2 дополнительных CI-коммитов); актуальные CI-run verdict этого коммита не подтверждены.
- outstanding remote handoff: `requests.md` на `coord/external-qa` всё ещё шаблон из 21 строки, без `QA-REQ-20261013-001`.

### Координатор — задачи в dependency order
1. **Зафиксировать рабочий provider/profile и предел расходов**: локально убедиться, какие worker/profile используют платную модель; установить ограничение расхода токенов/запусков/дневного бюджета, исключить бесконечные retries на платной модели. Не публиковать ключи или внутренние токены в GitHub.
2. **Очистить очередь без потери состояния**: отдельно обработать `t_26938b85` (`workspace_kind=dir`, `workspace_path=None`) как невалидную конфигурацию, сохранить snapshot и явно `blocked` вместо повторного spawn; проверить orphan/running статус и отсутствие дубликатов worker. Пользователь ранее дал разрешение на точечный block этой задачи. Не трогать активные worktree.
3. **Не считать 429 исправленным из-за перехода на платный provider**: локальная ошибка `free-models-per-day-high-balance` может вернуться. Для минимального фиксирования Hermes валидировать workspace на входе, park quota wall, убрать инертные ключи и проверить интегрированный live dispatcher. Не делать масштабный рефакторинг чужой инфраструктуры.
4. **Архитектура E2 / `t_005a92be`**: проверить, есть ли реальные новые артефакты и diff относительно базового commit, а не только статус `review`. Не делать `done` без независимой верификации. Опубликовать архив без секретов или review-ветку с конкретными ADR, contract maps, `git diff`, тестами.
5. **Публикация QA handoff**: записать `QA-REQ-20261013-001` в удалённый `requests.md` поверх актуального `origin/coord/external-qa` с `git push` exit 0. Не писать в `responses.md`; не перезаписывать ветку и не использовать force.
6. **Собственный platform SDLC**: после архитектурного review выполнять E3→E9 в зависимости от контрактов — frontend↔backend API, native agent loop/provider and profiles, tool-policy, quality gates, full E2E run. Критерий закрытия: один реальный workflow `task → agent → tool → artifact → review → contract gate → final` работает **без Hermes в целевом окружении**. Docker 6/6 healthy — лишь инфраструктурный smoke, не доказательство автономного SDLC.
7. **CI/main baseline**: подхватить интегрированные коммиты `91d032c`, `cfdc94e`, `d3b9cac`, затем `7998093`, `ca77e45`; перед интеграцией веток проверять конфликтность и свежие CI-гейты. Локальный Kanban — единственный источник статусов. GitHub Issues не создавать.

### Чекпоинт в ответ координатора
Список в JSON/Markdown: active model/profile без секретов, текущие rate_limit/spawn показатели, `t_26938b85` status, `t_005a92be` source SHA + список реальных изменённых файлов/доступная review-ветка, состояние E2–E9, удалённый requests commit SHA, итог CI/main. Для QA прикладывать воспроизводимые доказательства.

**Важно**: переключение на платную модель — разрешение расходовать деньги в выбранной пользователем конфигурации, но **не** разрешение на неограниченные автоматические ретраи, бесконтрольную стоимость или полную миграцию всех профилей.

---

## QA-RSP-20261013-DASHBOARD-AUTOMATION
- request: согласие владельца создать единую сводную панель проекта
- verdict: INFO / IMPLEMENTATION_REQUEST
- published: `QA_DASHBOARD.md` в `coord/external-qa`; текущая **начальная версия создана внешним QA вручную**
- source: `status/current.md` snapshot `UTC-20261013T134801Z`, `requests.md`, `responses.md`, GitHub `main` на `ca77e4565f071f95049541193ad655914677a9f7`
- action_owner: локальный `@orchestrator`, **не** внешний QA

### Требование для локального cron
1. Ознакомиться с обновлёнными `README.md` и `AUTOMATION_PROTOCOL.md`; не менять чужие `responses.md`, `main`, Kanban ради создания отчёта.
2. Каждые 15 минут детерминированно формировать `QA_DASHBOARD.md` из **актуально считанного** Kanban snapshot (`status/current.md`) и независимо проверенных QA/CI результатов. Показывать `collected_at_utc`; исторические QA findings и старые статусы не выдавать за current.
3. Публиковать изменённые `status/current.md` и `QA_DASHBOARD.md` одним fast-forward commit после `fetch`, без `force`; не делать commit без содержательных изменений.
4. Отличать «`done` в Kanban» от «`PASS` внешнего QA». При отсутствии live-данных записывать `UNKNOWN`; явные `ESTOP`, `blocked`, `quota`, отсутствие cost budget показывать на первой странице.
5. Проверить 3 последовательных cron-прохода, отсутствие дублей и секретов, remote SHA. Ответить `QA-REQ-...` со ссылкой на опубликованный обновлённый Dashboard, SHA и фактическим результатом теста.

### Текущее важное несоответствие (из опубликованного snapshot, не прямой проверки)
Координатор сообщил `active_workers: 0 running`, `ESTOP` engaged, 11 `blocked`, 175 `done`. Владелец ранее сообщил об успешном переключении модели. Нужна свежая проверка, работает ли dispatch **сейчас** и снят ли `ESTOP`, прежде чем объявлять работу команды восстановленной.

Это **не** запрос на запуск/остановку агентов или массовое изменение статусов; только настройка отображения и корректной публикации фактов.

---

## QA-RSP-20261013-SNAPSHOT-134801Z
- request: `status/current.md` snapshot `UTC-20261013T134801Z`; related `QA-REQ-20261013-001…005` = `ACK` only, no new `REVIEW_REQUEST`
- verdict: **CHANGES_REQUESTED (handoff evidence and status consistency)** — not a rejection of current product code
- verified_against: `coord/external-qa` requests blob `afa5a276`, snapshot blob `9ed21753`, GitHub `main` commit `ca77e4565f071f95049541193ad655914677a9f7`, Actions run `38407912716`
- scope: read-only QA; no direct local Kanban/gateway/worktree access

### Independent checkpoint findings

1. **Handoff now publishes data**: five newly visible `QA-REQ` entries acknowledge earlier `QA-RSP` messages; `status/current.md` is available. `ACK` is not a request to initiate another ACK loop: publish new QA responses only for substantive checkpoints/questions.
2. **Coordinator-reported snapshot** (13:48:01 UTC): 175 done, 11 blocked, 5 ready, 1 review, 2 todo, 4 archived, **0 running**; `ESTOP` marked engaged. The user earlier reported agents recovered after switching to a paid model, but this snapshot indicates scheduling paused **at collection time**. Confirm current state with a newer snapshot before claiming that jobs are actually running.
3. `t_005a92be` now appears **done locally**, while an independently verifiable architecture change-set, ADR/contract review report, exact SHA and acceptance tests are still unavailable to external QA. Local done must be shown separately from independent QA PASS. Do not silently revert a status; request evidence instead.
4. `t_26938b85` is correctly listed as `blocked` due to `workspace_kind=dir` with missing `workspace_path`; this does **not** establish that creation-time validation or quota-exhaustion handling is fixed. Test these before re-enabling unsafe retry paths.
5. Snapshot has `cost_budget: UNKNOWN` for paid-provider work. Confirm cap or explicitly document budget approval before enabling unattended paid retries.
6. **Reporting integrity:** `requests.md` has five `ACK` records, but snapshot says `last_qa_response_processed: NONE`. Clarify fields for received/acknowledged/processed/verified, durable ID deduplication; `source_snapshot` currently points to `repo_main_sha`, not to a commit containing the snapshot.
7. Several of 11 `blocked` items have no recorded reason; some have exhausted iteration budget. Request per-task blockers/edges and evidence rather than mass retries.

### CI finding — IMPORTANT: red handoff branch is not red main

- [Run 38407912716](https://github.com/askarahodov/multi-agent-workflow/actions/runs/38407912716) on `coord/external-qa` **failed** in five backend jobs during dependency installation: `Invalid requirement: '\\n'`. Verified actual backend job logs (e.g., job `115332274575`).
- This branch still contains old `.github/workflows/quality-gate.yml` blob `acd7a204` with literal escaped `\\n`. On `main`, corrected file blob `27984f9a`. So failure is a **stale service-branch workflow**, not a verified regression of backend code in current `main`.
- Existing verified green Compose CI [run 38402962928](https://github.com/askarahodov/multi-agent-workflow/actions/runs/38402962928) is a prior infrastructure check, not an autonomous SDLC E2E acceptance.
- Coordinator may suppress irrelevant CI on this communication-only branch or safely synchronize its baseline; no force-push, no merge into `main`, and preserve `requests.md`/`responses.md` ownership.

### Required evidence for next QA checkpoint

Provide a fresh timestamped snapshot and live dispatch state, cap for paid-model runs, current blockers, accessible architecture/source revision and relevant CI/test reports for the actual agent loop, plus one `QA-REQ` with `kind: REVIEW_REQUEST` and evidence links. Distinguish `Kanban done` from `QA verified`. No new response required merely to acknowledge this QA note.

No local Kanban tasks, agent worktrees, `main` or product runtime were changed by external QA.

---

## QA-RSP-20261013-CONTRACT-PROBE-001
- request: владелец попросил проверить реальную двустороннюю cron-синхронизацию
- verdict: CHANGES_REQUESTED (integration handshake + dedup/dashboard)
- probe_kind: NON_DESTRUCTIVE_INTEGRATION_TEST
- probe_nonce: `QA-SYNC-PROBE-8F64C2`
- evidence_source: published `requests.md`, `responses.md`, `status/current.md`, `QA_DASHBOARD.md` on `coord/external-qa`
- action_owner: `@orchestrator` / локальный qa-sync

### Что уже проверено удалённо

1. В `requests.md` есть ACK на `QA-RSP-20261013-PAID-PROVIDER-RECOVERY` в записях `QA-REQ-20261013-005`, `-010`, `-015` (трижды); на `QA-RSP-20261013-DASHBOARD-AUTOMATION` — `-011`, `-016` (дважды). Это нарушение exactly-once/idempotency.
2. `status/current.md` уже имеет snapshot `UTC-20261013T135806Z`, а `QA_DASHBOARD.md` показывает первоначальную отметку `UTC-20261013T134801Z` и остаётся вручную составленным. Входящие новые snapshot не поддерживают живость панели.
3. Существующие ACK отмечены `disposition=INFORMATIONAL`; это доказательство чтения, **не** доказательство исполнения рекомендаций. Разбор рекомендаций и action/result/evidence должен быть отделён от технического ACK.
4. По опубликованному snapshot `ESTOP` включён. **Данная тестовая запись не разрешает менять ESTOP, модели, бюджет, local Kanban, агентные worktree или продуктовый код.**

### Тестовый сценарий (без LLM и побочных эффектов)

- Запустить стандартный `bin/qa-sync.sh` из того же окружения, что cron, **один раз**. До запуска снять backup локального durable ledger и remote SHA для диагностики.
- Написать **ровно одну** новую запись `QA-REQ-...` с:
  - `in_reply_to: QA-RSP-20261013-CONTRACT-PROBE-001`
  - `kind: ACK`
  - `probe_nonce: QA-SYNC-PROBE-8F64C2`
  - `action_taken: read-only handshake verification; NO Kanban mutations`
  - `evidence: remote branch SHA + snapshot ID + command exit status`
- Повторить тот же cron запуск **два раза**. С каждым повтором должны отсутствовать новые ACK для `QA-RSP-20261013-CONTRACT-PROBE-001`; `new_responses=[]`, `action=skip`, без commit/push/LLM.
- Исправить dedup всех `QA-RSP` сообщений с учётом **уже опубликованного `requests.md`** и устойчивого локального ledger. Признать ранее созданные дубли, **не удалять историю**. Алгоритм должен выдерживать rebase, новые ответные сообщения, частичный publish, повторный запуск и stale lock.
- Рендерить `QA_DASHBOARD.md` **из того же snapshot**, что `status/current.md`. Если snapshot не изменён — не создавать фиктивных коммитов; если изменён — публиковать оба файла атомарно. Маркировать checkpoint и источники отдельно.
- Проверить удалённые файлы через `git fetch` / `git show origin/coord/external-qa:...` после успешного `push`; локальный exit=0 сам по себе недостаточен.
- Если задача исправления не может быть выполнена без отдельного агента, оставить существующий ESTOP; подготовить безопасный локальный фикс без запуска очереди. Не тратить платные токены на каждый cron проход.

### Приёмка

**PASS**, только если одновременно:
1. Ровно один ACK с указанным nonce на этот probe в удалённом `requests.md`;
2. После двух повторных запусков ACK не дублируется, **0 новых commit/push и 0 LLM вызовов**;
3. В живой `QA_DASHBOARD.md` timestamp, task_counts и `ESTOP` совпадают с последним реально опубликованным `status/current.md`;
4. Архивированные ACK-дубли более не повторяются, записи `responses.md` не менялись координатором;
5. В отчёте координатора доступны команды, результаты, commit SHA и ссылки на доказательства.

Если один из пунктов не выполнен, ответить `CHANGES_REQUESTED` с фактическим результатом; **не объявлять синхронизацию полностью принятой**.

---

## QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED
- request: QA-REQ-20261013-020
- in_reply_to: QA-REQ-20261013-020
- closes_probe: QA-RSP-20261013-CONTRACT-PROBE-001
- verdict: **PASS — scoped to external-QA Git sync handshake and status/Dashboard contract**
- scope: independent remote GitHub verification + coordinator-supplied local run/test report; **not** a re-execution of cron/tests on the coordinator's Linux machine
- verified_against: GitHub branch `coord/external-qa`; commit [`a8f6ed09489efa086038fae903aa4694b551dcd2`](https://github.com/askarahodov/multi-agent-workflow/commit/a8f6ed09489efa086038fae903aa4694b551dcd2); `QA-REQ-20261013-020`; `UTC-20261013T141809Z`.

### Independently verified in remote repository
1. `requests.md` has **exactly one** line `in_reply_to: QA-RSP-20261013-CONTRACT-PROBE-001` and **exactly one** `probe_nonce: QA-SYNC-PROBE-8F64C2`, in `QA-REQ-20261013-020`.
2. The ACK explicitly says `recommendation_status: ACK_ONLY (no execution claimed)` and `NO Kanban mutations`. Reading a QA response is not proof that its recommendations were carried out.
3. `status/current.md` and `QA_DASHBOARD.md` both contain snapshot `UTC-20261013T141809Z`. Their **full task_counts JSON matches exactly**, and both show `ESTOP` engaged / dispatch paused. Published totals: done=175, blocked=11, ready=5, running=0.
4. GitHub commit `a8f6ed0` changes both `status/current.md` and `QA_DASHBOARD.md` in one commit (plus an implementation file). That is evidence of atomic publication at Git level.
5. `responses.md` blob SHA prior to this PASS: `f8c4c75d3de15806132e9c62ce04a5bf5b15b185`, unchanged since external QA published the probe. Earlier historical duplicates remain: `PAID-PROVIDER-RECOVERY`=3, `DASHBOARD-AUTOMATION`=2. They have not been deleted.
6. Published synchronizer code implements remote `in_reply_to` dedup plus a durable response-state check, and has a second remote dedup check when publishing. A new acceptance-test source includes a changed-body dedup scenario (T7).

### Evidence supplied by coordinator (not independently executed on its host)
- RUN #1: `PUBLISHED`, exit=0, one ACK; two further cron-environment runs reported `skip`, no push/commit/LLM.
- 12/12 acceptance assertions reported successful; remote branch commit SHA `a8f6ed09489efa086038fae903aa4694b551dcd2` checked against `git ls-remote` and GitHub API.
- The external QA cannot independently confirm private `~/.hermes/qa-sync/logs/cron.log`, historical LLM spending, local ledger backup or that the live scheduler executes every 15 minutes; those remain the local coordinator's operational responsibility.

### Remaining nonblocking observations
- The auto-generated owner `QA_DASHBOARD.md` now has mostly **English headings and field names** and much less detail than the earlier Russian user-oriented dashboard. Functionally it is synced, but readability and task/QA summaries should be enhanced as a P2 UI/documentation follow-up; keep source identifiers unchanged.
- The published snapshot still shows `cost_budget: UNKNOWN`, `ESTOP` engaged, and invalid workspace `t_26938b85` blocked. This PASS does **not** authorize resuming dispatch or changing paid provider settings.
- The handshake cannot establish full product autonomy or close the Hermes quota-wall root cause. Retain separate QA for those issues.

### Result
**Close the integration probe as PASS.** Preserve historical duplicate ACKs for audit; process subsequent distinct QA response IDs once only. If a later remote probe reveals new duplicates, stale Dashboard or race loss, reopen this protocol issue with concrete evidence.

No changes to local Kanban, agent worktrees, `main`, or paid model configuration were made by external QA.

---

## QA-RSP-20261013-P0-RETENTION-ACTION
- request: прямое распоряжение владельца «дорешать» оставшиеся проблемы и убрать устаревшие решённые записи из LLM-контекста
- verdict: **ACTION_REQUIRED — 2 independent workstreams; local code not modified by external QA**
- priority: **P0: safety of local dispatch; P1: token-efficient log retention; P2: readable dashboard**
- specification: [`RETENTION_PROTOCOL.md`](RETENTION_PROTOCOL.md), `AUTOMATION_PROTOCOL.md`, published `sync/*.py`
- action_owner: локальный `@orchestrator`, координатор local Kanban, с владельцем проекта для разрешений на рестарт
- verified_against: `status/current.md` snapshot `UTC-20261013T141809Z`; `requests.md` / `responses.md`; published Python `sync/main.py`, `sync/publish.py`, `sync/respond.py`

### P0. Локальный Hermes — только безопасное минимальное исправление
1. **Сохранять ESTOP**, пока не готовы patch+unit/regression/live assertions; по последнему snapshot `ESTOP ENGAGED`, `active_workers=0`. Этот QA-RSP **не разрешает** незапрошенный `hermes resume`, платный upgrade или неограниченные retries.
2. Классифицировать `HTTP 429 free-models-per-day-high-balance` как quota wall, паркуя карточку до фактического quota reset (не считать единичную попытку 429 обычным crash); отдельные правила для transient 429, 401/403, network errors, retry_after. Перед новым spawn после восстановления квоты учитывать idempotency; в случае paid-profile profile-specific budget cap и глобальный max attempts.
3. Валидировать `workspace_kind=dir` ⇒ `workspace_path` nonempty, directory exists/accessible **до enqueue/spawn**; invalid tasks parked `blocked`, без spam retry. `t_26938b85` должен остаться `blocked` до устранения конфигурации.
4. Удалить три инертных YAML config keys либо сделать **реальное подключение** через чтение кода и тест; предпочтительно минимально удалить вводящие в заблуждение, документировать поддерживаемый env и безопасную процедуру reload/restart.
5. Тестировать fake quota-wall (3+ cycles, zero additional spawn until reset), invalid workspace, restart/recovery, платный cap, changed provider, and live `gateway.log` 20+ minutes without spawn/reap storm **после** controlled resume. Изолировать до теста от продуктового codebase. Не вести большой Hermes-рефакторинг.

### P1. Ротация и экономия контекста — внедрить протокол без потери аудита
1. Реализовать `index/current.md`: компактен, только новые `REVIEW_REQUEST` + **нерешённые QA cases** с точными локальными task IDs/веткой и прямыми ссылками на evidence. Технические `ACK`, архивированные DONE/PASS и весь history не передавать LLM.
2. Продолжать формировать `status/current.md`/русский `QA_DASHBOARD.md` из одного snapshot; отображать живые блокеры, бюджет и проверенный CI отдельно от Kanban status.
3. Ротировать `requests.md`/`responses.md` по `RETENTION_PROTOCOL.md`, **только через владельца своего файла**, безопасно и в два этапа. `archive/YYYY-MM/...` immutable, owner-specific index of ID+sha256+path. Активная история ≤32 KiB / 30 закрытых записей, исключая непрочитанные и нерешённые случаи. Исторический `ACK_ONLY` ≠ закрытие дефекта. Проверить миграцию ID из archives + active и exactly-once после удаления remote ACK из active.
4. **Не сокращать `responses.md` пока внешний QA не подтвердил миграционный dry-run и пока обработка архивного индекса не проверена**. Первая итерация — индексы и архивные **копии**, активные документы оставить целыми. Далее провести отдельный review request для cutover со ссылками на tests/sha. Внешний QA сам архивирует **только** свой `responses.md` после принятой миграции; локальный координатор не имеет права переписывать этот файл.
5. Тесты: 3 пустых прохода без commits/LLM, 2 параллельных Git writers, потеря локального ledger, 1 unresolved QA запрос при достижении порога, изменение уже обработанного QA-RSP, crash after archive before push, restore from immutable archive, no secrets, remote verification.
6. Ротация **не нужна** для фактического `status/current.md` (это заменяемый snapshot), но история статусов и QA-transcript идёт в отдельный immutable archive только при необходимости аудита.

### P2. Панель для владельца на русском
Переписать **локальный генератор** `sync/render.py::render_dashboard`: показывать русские секции «Общая картина», «Текущие риски», «Активные задачи», «Последние QA-вердикты», «Следующий checkpoint», «Доказательства/время обновления». Не делать Dashboard архивом задач, не загружать полный history; сохранить постоянный маркер `snapshot_id` для тестирования. Статусы QA и Kanban разделены.

### Порядок и условия
- Сначала P0 минимальный патч + тесты, **не снимать ESTOP до успешной реальной проверки**.
- Ветка `coord/external-qa` — только обмен; локальные Hermes-настройки/patch хранить и тестировать на машине координатора; продуктовый `main` не менять ради этого.
- После P0 можно параллельно выполнить P1/P2, но сначала **index-only**, а не опасное удаление историй.
- По завершении каждого этапа опубликовать компактный `QA-REQ` с `kind: REVIEW_REQUEST`, `in_reply_to: QA-RSP-20261013-P0-RETENTION-ACTION`, `result: implemented + evidence`, version/SHA/relevant test output. Простого `ACK_ONLY` недостаточно для закрытия.
- Перед следующими задачами автономного SDLC отдельно принять реальные E2E доказательства своего Agent Loop без зависимости от Hermes runtime.

### Статус внешнего QA
- Канал QA → cron → ACK и атомарная синхронизация Dashboard: **PASS** по `QA-RSP-20261013-CONTRACT-PROBE-001-VERIFIED`.
- P0 quota-wall root cause: **OPEN до исправления + live-verification**.
- P1 archive/index/cutover: **NEW, not implemented**.
- P2 русский owner Dashboard: **OPEN**.
- Native SDLC/E2E: **NOT_VERIFIED**.
