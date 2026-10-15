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

## QA-RSP-20261014-SUBSTANCE-ROOT-CAUSE
- request: coordinator report of unstable substance hash and unresolved P1 retention
- verdict: CHANGES_REQUESTED
- verified_against: published sync/render.py, sync/main.py, QA_DASHBOARD.md and index/current.md on coord/external-qa
- finding: existing normalize() already replaces UTC snapshot IDs; that is NOT the root cause. It leaves the current coordination branch SHA untouched in the Russian Dashboard row "ветка обмена (coord/external-qa)", Dashboard bullet "ветка обмена:", and index/current.md field "inbox_revision". Replacing only that SHA changes normalized dashboard and index text, but not normalized status/current.md.
- fix: normalize exactly those three coordination-only representations before calculating substance. Do NOT normalize repo_main_sha, whose change must trigger a new snapshot. Add regression tests: same Kanban, changed coordination SHA => same substance; changed main SHA => changed substance; changed actual Kanban status => changed substance; 3 empty cron runs => zero commits.
- retention: archive/requests-index.json currently points to archive/2026101/ while the canonical duplicate sits in archive/2026-10/. Fix path consistency. Current build_archive() constructs new shard content for a reused daily path, risking overwrite instead of immutable append; do NOT approve cutover before write-once/content-addressed verification and crash/restart tests.
- P0A: still requires published Hermes patch/test evidence and a separate controlled live test; keep ESTOP unchanged.
- scope: independent read-only QA findings; no coordinator-owned source, Kanban or product main modified.

## QA-RSP-20261014-ARCHIVE-OVERWRITE
- request: QA-REQ-20261013-P1B
- verdict: CHANGES_REQUESTED
- verified: reproducing current build_archive algorithm with successive delivered A, then B: both use the same day shard path. Second output contains only B; index claims both A and B. publish.py would replace the file, losing A.
- root_cause: files={} in each call; old remote shard never read.
- acceptance: immutable unique shard per batch OR verified remote-content append; all indexed IDs remain retrievable; fix malformed archive/2026101 paths; repeat no-op and recovery tests. Cutover denied.

## QA-RSP-20261014-P0A-REVIEW
- request: QA-REQ-20261013-P0A
- verdict: CHANGES_REQUESTED
- scope: local Hermes patch and 10 tests are coordinator-reported, not externally verified; sanitized diff and live gateway evidence unavailable. Six-hour cooldown may precede daily quota reset, and workspace validation at creation is not proven.
- acceptance: publish sanitized patch and regression evidence; validate quota reset-aware parking, workspace creation and persistence. Controlled live test requires separate authorization. ESTOP not changed.

## QA-RSP-20261014-P2C-REVIEW
- request: QA-REQ-20261013-P2C
- verdict: PASS (Russian localization and snapshot consistency only)
- verified_against: QA_DASHBOARD.md and status/current.md both have UTC-20261014T084506Z, matching task_counts and ESTOP. No product E2E claim.
- follow_up: latest QA verdict column shows missing labels; show clear verdicts and model cost_budget=UNKNOWN until configured.

---

## QA-RSP-20261014-P1-ARCHIVE-INDEX-INTEGRITY
- request: follow-up validation for QA-REQ-20261013-P1B and coordinator's A-to-B verification matrix
- verdict: CHANGES_REQUESTED
- scope: independent inspection of current remote files and published sync code; not an execution of private cron or Hermes
- verified_snapshot: UTC-20261014T091512Z (published status has source_status=PARTIAL and ESTOP engaged)

### Blocking integrity finding

Remote `archive/requests-index.json` contains **19 entries**. Of these, 12 resolve to `archive/2026101/requests-20261013.md` and are present there (non-canonical path); 7 resolve to `archive/2026-10/requests-20261014.md` but that remote shard contains **only three entries**: `QA-REQ-20261014-015`, `-016`, `-017`. Missing from the indexed shard: `QA-REQ-20261013-P0A`, `-P1B`, `-P2C`, `QA-REQ-20261014-013`. All four still exist in active `requests.md`; this is currently an **index integrity failure**, not irreversible content loss.

`sync/retention.py` now attempts cross-run reads using relative filesystem paths under `.worktrees/coord-external-qa`, not a verified fresh remote Git blob. This is not a stable source in cron or after concurrent commits; its fallback to new shard content can overwrite the older shard. The index was already updated to include missing blocks. Do not perform cutover.

### Additional dashboard root cause

Published `sync/respond.py::_field` uses a regex anchored to `^verdict:` (without optional Markdown list prefix). Real QA response bodies use `- verdict:`, so `respond._field(body, "verdict")` returns empty and `QA_DASHBOARD.md` prints `—`. Fix with a parser that accepts both plain and `- verdict:` fields, with a regression test using real response examples. Distinguish technical ACK from QA verdicts and open-case closure.

### Required acceptance

1. Archive A in pass 1, B in pass 2 in separate processes, using **the same published remote branch**. The second commit must preserve A and B, with verified block sha256 and no duplicate ID. Prefer a unique immutable shard filename for new batches; never overwrite an earlier immutable shard.
2. Audit all 19 index IDs; each reference must resolve to an existing remote file and match its block hash. Normalize `archive/2026101/` paths without discarding historic content; no irreversible deletion.
3. Test full `substance`: service-branch SHA change alone => same digest; main SHA or Kanban status change => different digest. Prove 3 consecutive steady-state cron runs result in `skip`, zero commits and unchanged remote SHA (the previously reported 3 PUBLISHED runs do not pass).
4. Dashboard must show actual PASS / CHANGES_REQUESTED, `cost_budget: UNKNOWN` when unset, and the correct ESTOP state; snapshot and counts must still match `status/current.md`.
5. P0A remains separately pending: publish the actual sanitized Hermes diff and unit evidence. A reported 22-minute period with 0 new spawn is useful but alone does not demonstrate quota reset-aware parking, especially while ESTOP is engaged in the latest snapshot. Confirm timing/ESTOP state and error counter context without automatically resuming.

Cutover authorization: **BLOCKED** until all remote archive ID/hash checks and steady-state cron tests pass. Coordinator owns requests/index/archive code; external QA owns responses.md. No changes to Kanban, `main`, active worktrees or ESTOP in this QA entry.

## QA-RSP-20261015-REMOTE-MAIN-FRESHNESS
- request: NONE (проактивная независимая проверка целостности QA snapshot; связано с GitHub Issue #44)
- verdict: CHANGES_REQUESTED
- severity: HIGH
- reviewed: remote GitHub main, coord/external-qa status/current.md, QA_DASHBOARD.md, sync/collect.py, sync/render.py
- product_main_at_review: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- local_agents: NOT_MODIFIED; ESTOP: NOT_MODIFIED

### Проверенный дефект
Snapshot `UTC-20261015T083008Z` (`collected_at_utc=2026-10-15T08:30:08Z`) объявляет `source_status: VERIFIED`, `repo_main_sha: eb3860b9514649ff8deea771d45c363dc6ab6b98`. Однако GitHub `GET /repos/askarahodov/multi-agent-workflow/branches/main` указывает `a8f7e4be33218dbba1e60f9c3756fcbaa7477621` с временем коммита `2026-10-15T08:25:02Z`, то есть удалённый `main` был новее уже за пять минут до сбора snapshot. Русская `QA_DASHBOARD.md` повторяет устаревший SHA как «главная ветка (main)».

### Root cause
Опубликованный `sync/collect.py::collect_git()` читает `git rev-parse origin/main` (локальный remote-tracking ref, который не обновляется сам) и помечает `git.state=VERIFIED`, если ref существует. Для `coord/external-qa` код уже выполняет `git ls-remote`, но для product `main` удалённый ref не проверяет. `sync/render.py::_source_status()` доверяет этому статусу. Следовательно, даже зелёный CI не доказывает, что внешний QA смотрит на актуальный product SHA.

### Требуемый минимальный фикс и проверка
1. Считывать **реальный удалённый** `refs/heads/main` через ограниченный по времени read-only `git ls-remote --exit-code origin refs/heads/main` либо GitHub API; валидировать SHA. Локальный `origin/main` отображать отдельно и не называть подтверждённым удалённым `main`.
2. При невозможности получить remote `main`, при несоответствии источников или отсутствующих подтверждениях выводить `PARTIAL/UNKNOWN`, а не `VERIFIED`; не подставлять локальный SHA как подтверждение. При оценке CI связывать `head_sha` успешного запуска с проверенным remote main SHA.
3. Регрессионные тесты без сети/LLM: stale local `origin/main` + advanced remote main => snapshot сообщает новый SHA; remote lookup failure => `PARTIAL`; повторный неизменный remote SHA => no-op; изменение remote SHA => substantive update; dashboard/index/status сохраняют одинаковую ревизию.
4. Доказать результат опубликованным diff, тестами и новым remote snapshot. Только после этого использовать `source_status=VERIFIED` для решения о приёмке.

### Границы
Это отдельный QA finding, **не** разрешение на merge, повторный spawn, снятие ESTOP, активацию branch protection или архивный cutover. Issue #44 остаётся OPEN: после сбора inventory локальных пишущих агентов правила GitHub включает только уполномоченный владелец. Не менять worktrees, локальный Kanban, product main и coordinator-owned файлы.

## QA-RSP-20261015-LIVE-RECOVERY-FENCING
- request: NONE (проактивная независимая проверка Issue #38; product main @ a8f7e4be33218dbba1e60f9c3756fcbaa7477621)
- verdict: CHANGES_REQUESTED
- severity: P0 / HIGH (safety of already running side effects)
- verification: static code-path audit at immutable product main SHA; **live concurrency test NOT executed**; published CI green does not cover this race
- inspected: orchestration-server/orchestration_server/{api.py,engine.py,native_http_worker.py,native_bridge.py,native_worker.py}; orchestration-server/tests/test_safe_recovery.py; docs/architecture/safe-worker-recovery.md
- local_agents: NOT_MODIFIED; ESTOP: NOT_MODIFIED; Kanban/worktrees/product main: NOT_MODIFIED

### Риск: recovery помечает живую попытку как прерванную без fencing executor

**Проверенный путь кода:**
1. `api.py:536-539`: защищённый по RBAC `POST /admin/recover` без precondition «workers stopped / drained» вызывает `eng().recover()` даже при потенциально активном исполнителе.
2. `engine.py:698-750`: `recover()` без проверки живости runner, worker generation/lease или его подтверждённой остановки помечает **все** `running` attempts как `interrupted`, **все** `in_progress` tasks как `blocked`, а **всех** `busy` agents как `idle`. Это атомарный переход в БД, а не сигнал остановки живого runner.
3. `native_http_worker.py:190-224`: после успешного HTTP claim исполнитель ожидает `self.runner(task, attempt_id)`, не проверяя перед продолжением статус attempt / fencing epoch. `native_bridge.py:109-126` аналогично вызывает `await runner(...)` после claim. Нет очевидной проверки живости попытки перед каждым потенциальным side effect.
4. `tests/test_safe_recovery.py`: существующий тест вызывает `recover()` после одного `claim_task()`, но не удерживает реальный running runner на asyncio barrier и не вызывает `/admin/recover` конкурентно. Проверка, что **новый** worker не берёт blocked task, не останавливает **старый** worker.

**Возможный воспроизводимый сценарий:** A получил claim и ожидает внешнего ответа перед write_file; администратор вызывает /admin/recover; БД отмечает A interrupted, task blocked и agent idle; A возвращается из await и делает write_file. В этот момент evidence/ledger, проверенные администратором ранее, могут оказаться устаревшими; новый claim на того же idle agent тоже становится допустим. Это логически допустимо по опубликованным путям кода, но не заявляется как наблюдавшийся production-инцидент.

### Запрашиваемый safety fix / acceptance evidence
1. Fail closed для ручного `/admin/recover`: отклонять операцию, когда нет **достоверного** подтверждения quiescence всех затронутых executors. Просто чтение `TaskAttempt.status` недостаточно: БД после crash может сохранять статус `running`. Для recovery после рестарта/внешних HTTP workers нужна durable owner-generation/lease fencing или эквивалентная проверяемая остановка.
2. До side-effect-инструментов (особенно write_file / shell / git / HTTP) executor проверяет действительность attempt lease/fence; при отзыве старой эпохи не допускается новый побочный эффект. Различать ещё выполняющийся запрос в tool и инструмент с уже завершившимся side effect; запрещать аттестацию `CONFIRMED_NO_SIDE_EFFECT` как безопасную при неустранённой неопределённости.
3. Не освобождать Agent так, чтобы он мог быть повторно назначен конкурентно со старым executor, пока не обеспечено fencing/termination и безопасное переиспользование.
4. Регрессия с управляемым `asyncio.Event`/двумя исполнителями: claim A → A внутри runner до side effect → admin/restart recovery → release A → **нулевые новые побочные эффекты от A**, отсутствие параллельного claim для того же исполнителя, сохранение blocked и журнал аудита. Отдельный E2E через NativeHttpWorker и тест падения канала/fence.
5. Опубликовать diff, negative tests, результат CI и runbook условия допустимого admin recover; не выдавать просто успешный `test_safe_recovery.py` за гарантию fencing.

### Границы
Не снимаем ESTOP, не запускаем оплачиваемые LLM, не перезапускаем агентов, не объявляем #38/#11 закрытыми. Это отдельный safety finding для владельца server/runtime; модификации делать в изолированной агентной ветке с тестами, не через QA service branch. Никакого auto-replay старой попытки.

## QA-RSP-20261015-PAID-LIMIT-OWNER-HANDOFF
- request: NONE (информирование локального @orchestrator по прямому поручению владельца продолжить разработку без расходования платного лимита)
- verdict: INFO
- source_snapshot: coord/external-qa/index/current.md @ UTC-20261015T090006Z (исторический snapshot; live state не подтверждён)
- product_main_at_handoff: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- paid_provider_usage: NONE; OPENROUTER/API_KEYS: NOT_MODIFIED
- local_agents: NOT_TOUCHED; ESTOP: NOT_MODIFIED; Kanban/worktrees: NOT_MODIFIED
- coordinator_action: INFORMATIONAL_ACK_ONLY; no paid agent dispatch, no automatic merge, no Kanban status changes

### Что независимо разработано и проверено без платных моделей
1. **[PR #45](https://github.com/askarahodov/multi-agent-workflow/pull/45)** — `fix/recovery-ledger-enforcement` @ `f6875be38f60148719b30e2a1cb22d84b751f6dd`: без доверенного read-only Tool Ledger direct admin POST reconciliation больше не принимает `CONFIRMED_*`, даже если evidence SHA-256 совпал; `UNKNOWN` разрешён. CI, Quality Gate, Native E2E, Coordination isolation SUCCESS: runs 38708962991 / 38708963388 / 38708963305 / 38708963085. OPEN, Ready for review, NOT merged.
2. **[PR #46](https://github.com/askarahodov/multi-agent-workflow/pull/46)** — `fix/issue-38-recovery-guard` @ `9c788e67076eb97a74ccc3015c9fdbfb750c8fa1`: crash recovery теперь `busy→inactive`, claim атомарно разрешает только `idle` (ранее `!=busy` допускал даже terminated), ручной `POST /admin/recover` fail-closed HTTP 409 до доказанной quiescence. Новый asyncio concurrency regression, тесты non-idle agent и актуализированный русский runbook. Полученный [Codex review P2](https://github.com/askarahodov/multi-agent-workflow/pull/46#discussion_r4281118809) исправлен: `ConflictError` выдаёт RFC 9457 ProblemDetail, OpenAPI в двух alias и checked-in spec показывают только 409; тест OpenAPI больше не переписывает проверяемый checked-in файл. Reply опубликован, review thread закрыт. CI 38711386944, Quality Gate 38711386923, Native E2E 38711387004, Coordination Isolation 38711387021 — SUCCESS. OPEN, Ready for review, NOT merged.
3. **[Issue #38](https://github.com/askarahodov/multi-agent-workflow/issues/38#issuecomment-6188530448)** содержит handoff предыдущего этапа. Не создано дублирующих локальных Kanban задач, не изменены PR/ветки локальных агентов.

### Запрос на дальнейшее действие от владельца после восстановления лимита
- Прочитать **этот handoff перед возобновлением локальной разработки**, не создавать параллельные ветки с тем же scope #38 и не перезаписывать `fix/*` PR #45/#46.
- Следовать dependency order: независимый код-ревью и интеграционная проверка #45 → #46, только затем аккуратное squash merge в main с перепроверкой GitHub CI на новом SHA. Эти PR не включены в main и НЕ считаются production accepted.
- P0 remains **OPEN**: restart API не гарантирует остановку ранее живого worker. Даже `inactive` agent identity не отменяет уже начатый `runner` / tool side effect; операторское CONFIRMED_NO_SIDE_EFFECT не является доказательством exactly-once. Нужны durable worker generation/lease fencing, защита executor перед side effects, shutdown/drain protocol и негативный cross-host/runtime E2E.
- Ранее открытая проблема **stale remote main SHA** (QA-RSP-20261015-REMOTE-MAIN-FRESHNESS) по опубликованному `sync/collect.py` всё ещё требует отдельной проверки исправления; не принимать `VERIFIED` на основании одного локального `origin/main`.
- Не включать платные профили/снимать ESTOP без отдельного решения владельца; не вмешиваться в сохранённые worktree/Kanban и не запускать автоматическую повторную попытку старых tool calls.

### Что не заявляем
CI green подтверждает offline test suite и CI-проверки только для указанного SHA; live paid OpenRouter, production quiescence и exactly-once не проверялись. Изменения пока только в изолированных GitHub PR, product main не изменён.

## QA-RSP-20261015-NATIVE-ATTEMPT-GUARD-HANDOFF
- request: NONE (owner-authorized offline development handoff to local @orchestrator, no paid model calls)
- verdict: INFO
- product_main_at_handoff: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- paid_provider_usage: NONE; ESTOP/paid profiles/local Kanban/worktrees: NOT_MODIFIED
- task_scope: GitHub #33, #38, #11; local task statuses NOT_CHANGED
- responsible_branch: security/native-tool-attempt-guard
- implementation_pr: https://github.com/askarahodov/multi-agent-workflow/pull/47
- implementation_sha: 12f0210444f0c0fd272f873595d5e242096bf070
- github_issue_comment: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6188824758

### Независимая реализация (только офлайн)
- Trusted `NativeFilesystemDispatcher(attempt_active=...)` при durable `SqliteToolLedger` теперь отклоняет **новый** read/write до выполнения, если control-plane callback не возвращает literal `True` или выдаёт ошибку. Ответ `ATTEMPT_FENCED` не раскрывает traceback/путь/secret, ledger фиксирует `DENIED`.
- Regression: revoked / stale guard, неожиданное truthy-значение, ошибка guard с секретами, смена allow→deny между вызовами, повторный tool ID.
- Cross-service offline E2E в `tests/native_agent_e2e/test_native_contract_pipeline.py`: реальная orchestration SQLite переводит попытку в `interrupted`; callback доверенного runner читает это состояние; следующий write_file не создаёт файл, ledger `DENIED`, задача `blocked`.
- Docs: `docs/architecture/native-tool-ledger.md`, русская секция об ограничениях.

**На PR #47 head все GitHub workflows SUCCESS:** CI 38712411177, Quality Gate 38712411134, Native E2E 38712411069, Coordination isolation 38712411097. PR OPEN / Ready for review / NOT merged. Codex review после Ready ещё может работать: не объявлять внешнее одобрение до получения review.

### Dependency order / точные предупреждения
1. Сверить независимый review по PR #45 → #46 → #47, разрешить только подтверждённые замечания. Все три PR НЕ слиты в main. Зафиксировать мержи и CI на **итоговом main SHA** после каждого этапа; не дублировать их scope в Kanban.
2. Guard **опционален** и пока **НЕ подключён** к реальному production NativeHttpWorker/native runner; нельзя принимать его тест как доказательство готового durable fencing.
3. При гонке `guard()→revoke→write_file` уже запущенный I/O всё ещё возможен. Для #38/#33 нужно спроектировать server-owned generation/lease, защищённую передачу executor, атомарный revoke/barrier, worker quiescence/drain и кросс-хостовые negative E2E.
4. Не закрывать #33/#38/#11 и не включать платные модели/снимать ESTOP; не менять local worktree владельца и не перезапускать прежние tool calls. Сведения о состоянии локального Kanban — только из опубликованных snapshots, не live доступ.

## QA-RSP-20261015-SQLITE-FENCE-HANDOFF
- request: NONE (owner-authorized, offline development handoff)
- verdict: INFO
- product_main_at_handoff: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- owner_issue: https://github.com/askarahodov/multi-agent-workflow/issues/38#issuecomment-6189171429
- implementation_pr: https://github.com/askarahodov/multi-agent-workflow/pull/48
- implementation_sha: 4d45b5be93cae981c34e7f74a48016db851e1c5d
- paid_providers: NOT_USED; ESTOP/local worktrees/Kanban/main: NOT_MODIFIED
- coordinator_action: READ_ONLY_HANDOFF; do not spawn paid agents or auto-merge

### Что сделано без платных моделей
В `shared.attempt_fence.TrustedSqliteAttemptFence` появилась server-owned проверка состояния attempted claim в настоящей SQLite orchestration DB: run/task/attempt/agent идентичности и статусы, актуальный номер попытки, приватность файла DB. `NativeFilesystemDispatcher` при явно переданном доверенном `attempt_fence` удерживает `BEGIN IMMEDIATE` оркестрационной SQLite транзакции через весь защищённый filesystem tool I/O. `recover()/submit()/fail()` не могут завершить SQL-переход, пока уже начатая защищённая запись не завершилась; после перехода новые записи старой попытки отклоняются `ATTEMPT_FENCED`, ledger `DENIED`. Тесты межсервисной конкурентности и негативных сценариев выполнены без реальных LLM.

**GitHub checks SUCCESS (PR #48 HEAD):** CI [38714734547], Quality Gate [38714734593], Native E2E [38714734630], Coordination isolation [38714734403]. PR #48 OPEN, Ready for review, base=main лишь для полного PR CI; содержит унаследованные коммиты [PR #47](https://github.com/askarahodov/multi-agent-workflow/pull/47), поэтому merge order #45 → #46 → #47 → #48 (с финальным CI на main).

### Что НЕ реализовано / что требуется дальше
Никакого expiry/renewal TTL, PostgreSQL или distributed lease, удалённого tool gateway, production NativeHttpWorker enforcement, полноценного drain для HTTP/Git/shell и exactly-once. Неподключённые исполнители обходят opt-in fence; привилегированный SQLite доступ нельзя выдавать untrusted worker. `CLAIMED` после crash остаётся неоднозначным. Не считать issue #38/#33/#11 закрытыми; не снимать ESTOP и не запускать paid worker ради перепроверки. Следующий технологический этап — trusted authenticated tool gateway для удалённых исполнителей с durable server-issued generation, revocation ordering, PostgreSQL transaction/lock semantics и cross-host E2E.

## QA-RSP-20261015-DURABLE-ATTEMPT-LEASE-HANDOFF
- request: NONE (direct owner-authorized offline development handoff)
- verdict: INFO
- implementation_pr: https://github.com/askarahodov/multi-agent-workflow/pull/49
- implementation_sha: 82333a799ba7c5c777f552065bbf2013a3ac03b3
- issue_comment: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6189587597
- product_main_at_handoff: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- models: NO_PAID_LLM_USED
- local_agents, ESTOP, Kanban, local_worktrees, main: NOT_MODIFIED
- intended_coordinator_action: READ_ONLY_HANDOFF; do not spawn paid workers / reset local state / auto-merge

### Выполнение
В [PR #49](https://github.com/askarahodov/multi-agent-workflow/pull/49) самостоятельно реализованы server-owned Attempt Lease: durable `attempt_leases` с однократным выдаваемым криптографическим секретом и только SHA-256 в БД; opt-in флаг `ORCH_ATTEMPT_LEASE_ENABLED=0` по умолчанию, TTL 5–300 секунд, renew до истечения и невозможность оживить revoked/expired token, admin revoke, claim-only HTTP token и `Cache-Control: no-store`. Добавлены обязательные проверки token/generation/TTL внутри доверенного локального SQLite `BEGIN IMMEDIATE` fencing barrier, который сериализует отзыв и уже исполняющийся файловый I/O. API/OpenAPI на обоих aliases, русская документация, серверные и межсервисные negative tests. Никаких реальных LLM вызовов.

**PR #49 HEAD GitHub CI success:** CI 38717650452, Quality Gate 38717650468, Native E2E 38717650485, Coordination Isolation 38717650498. PR Open / Ready for review / NOT merged, review feedback проверить до интеграции. Таблица `attempt_leases` добавляется через действующий `create_all`; production schema migration/rollback и upgrade chain нужно проверить отдельно, особенно PostgreSQL.

### Dependency и оговорки для локального оркестратора
**НЕЛЬЗЯ сливать не по порядку:** PR #45 → #46 → #47 → #48 → #49 с recheck итогового diff/checks после каждого. Ветки #48/#49 включают изменения родительских PR; до merge main ещё НЕ защищён branch rules. Не дублировать scope и не переписывать занятые агентные worktree.

**Не закрыты #33/#38/#11.** HTTP NativeWorker всё ещё не подключён к токену/автоматическому renewal/trusted remote tool gateway. Сама выдача и проверка токена перед I/O без transaction fence остаётся TOCTOU. Для remote PostgreSQL/межхостового режима нужен gateway с проверяемым owner+generation, fenced write boundary, истечением/отзывом и drain, cross-host негативные тесты и приватность секретов. Включать opt-in режим удалённым worker **запрещено до полной интеграции**. Уже выполняемый I/O при истечении TTL сам собой не отменяется; ожидающий SQL revoke не может закоммититься до окончания ко-локальной защищённой операции, но не контролирует внешние shell/Git/HTTP side effects. Утерянный HTTP claim token или ledger CLAIMED не восстанавливать автоматическим replay.

Примечание: статусы местного Kanban/ESTOP взяты только из ранее опубликованных snapshot; управление ими не производилось и live подтверждения нет.

## QA-RSP-20261015-HTTP-LEASE-RENEWAL-HANDOFF
- request: NONE (owner-authorized offline engineering checkpoint)
- verdict: INFO
- implementation_pr: https://github.com/askarahodov/multi-agent-workflow/pull/50
- implementation_sha: 3eb5d395cb3cd5e99d9e4681e10131129c9ed54b
- dependency_pr: https://github.com/askarahodov/multi-agent-workflow/pull/49
- review_fix_sha: 128f030d7422c69eedc1b984a201e82b99bd0d12
- task_comment: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6190293445
- product_main_at_handoff: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- paid_llm: NOT_USED; ESTOP/worktrees/local Kanban/main: NOT_MODIFIED

### Scope выполненного
В PR #49 исправлен Codex P2/OpenAPI: claim-only `lease_token` теперь `readOnly` (реально доступен generated response model), входной renew token `writeOnly`; OpenAPI checked-in contract и regression обновлены, CI/Quality Gate на fix SHA SUCCESS. В PR #50 реализован **opt-in**, без paid LLM, `NativeHttpWorker(require_lease=True, leased_runner=trusted_runner)`: строгая валидация claim token/generation/UTC expiry до вызова trusted runner; периодические HTTP renew во время runner; финальный renew до submit. При revoked/expired/missing token, недоступном remote renew или forged generation клиент fail-closed, пытается отменить coroutine, не отправляет submit/fail и не делает auto-replay. Токен не вкладывается в task/LLM payload и не появляется в repr/error. Legacy HTTP worker не изменён по умолчанию. Документ `docs/architecture/server-attempt-leases.md` на русском обновлён. Интеграционные тесты ASGI+SQLite проверяют renewal success, revoke while in flight, missing token, HTTP 503 и подмену поколения.

**PR #50 HEAD checks SUCCESS:** [CI 38722626531](https://github.com/askarahodov/multi-agent-workflow/actions/runs/38722626531), [Quality Gate 38722626631](https://github.com/askarahodov/multi-agent-workflow/actions/runs/38722626631), [Native E2E 38722626527](https://github.com/askarahodov/multi-agent-workflow/actions/runs/38722626527), [Coordination isolation 38722626547](https://github.com/askarahodov/multi-agent-workflow/actions/runs/38722626547). PR OPEN Ready for review / NOT merged. Independent Codex PR review launched; outcome not yet confirmed.

### Список работ оркестратору после возобновления лимита
- Сначала независимое review и точный diff, затем последовательная интеграция #45 → #46 → #47 → #48 → #49 → #50. Родительские коммиты наследуются: проверять CI на конечном SHA main после каждого merge; не cherry-pick/merge out of order.
- **P0 открыт:** Не выполнена гарантия полного revoke внешнего I/O: HTTP cancellation — best effort; trusted remote tool gateway с server-authenticated attempt ownership, transactional PostgreSQL fencing, server submit/fail atomic lease guard и drain/quiescence ещё отсутствует. `NativeHttpWorker` opt-in heartbeat сам по себе не обеспечивает exactly-once и не гарантирует, что завершившийся старый HTTP/Git/shell вызов будет отозван.
- Не включать оплачиваемые профили/снимать ESTOP без решения владельца, не пересоздавать scope готовых PR в локальных worktrees, не auto-replay CLAIMED/recovered task, не активировать опциональные lease на проде до gateway acceptance.

## QA-RSP-20261015-ATOMIC-LEASE-PR51-INDEPENDENT-REVIEW
- request: NONE (independent QA under owner-directed dependency-order engineering)
- verdict: INFO / CONDITIONAL (CI final head must be checked)
- product_main_at_check: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- pr: https://github.com/askarahodov/multi-agent-workflow/pull/51
- reviewed_head: ccc53d34674f710950d1c8482ed1356806862a9a
- issue_handoff: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6190739632
- paid_agents_local_worktrees_ESTOPT: NOT_USED_OR_MODIFIED

### Статическое наблюдение
PR #51 уже реализует атомарный терминальный Lease gate для server `submit/fail`. Это совпадает с очередной задачей внешней разработки, поэтому не создавал конфликтующей ветки и не менял работу текущего владельца. На последнем HEAD `engine._consume_terminal_lease` фиксирует timestamp `checked_at` ПОСЛЕ `acquire_lease_write_fence`; `AttemptLeaseService.renew` также получает write fence перед текущим временем. В русской документации уже устранена устаревшая фраза про отсутствие terminal API atomic gate. Codex review P1/P2 `discussion_r4282217195`, `discussion_r4282217201` показываются `outdated=true`, `resolved=false`; координатору/владельцу необходимо ответить и доказательно закрыть после CI.

### Evidence и следующий gate
На exact SHA E2E 38725809985 SUCCESS, isolation 38725809988 SUCCESS. На момент проверки **CI 38725809950 и Quality Gate 38725809959 были QUEUED**, нельзя заявлять общий GREEN или merge. После завершения проверить все four checks, review, branch diff и интегрировать только в цепочке #45→#46→#47→#48→#49→#50→#51. Внешних платных вызовов не было, Kanban/ESTOP/local agents/main не изменялись.

### Остаточный P0
Remote tool gateway/remote side effect fence (Git/shell/HTTP), подтверждаемая quiescence и multi-host PostgreSQL still OPEN. Успех SQL submit/fail не доказывает отсутствие side effect в уже запущенном runner.

## QA-RSP-20261015-PR50-PR51-ALL-GATES-GREEN
- request: NONE (owner-directed independent development/review handoff)
- verdict: INFO / CHECKPOINT_ACHIEVED (all GitHub CI green on exact feature heads, NOT production release)
- supersedes_partial_evidence: QA-RSP-20261015-ATOMIC-LEASE-PR51-INDEPENDENT-REVIEW (older head ccc53d3 only; this is an updated checkpoint, not a deletion)
- product_main_at_check: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- PR50: https://github.com/askarahodov/multi-agent-workflow/pull/50
- PR50_head: 53683e62cb782b39c2330092794cdea240717c16
- PR51: https://github.com/askarahodov/multi-agent-workflow/pull/51
- PR51_head: 1ee27a08f9bcfa412d6959567750157501b97994
- issue_handoff: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6190850987
- paid_llm: NOT_USED
- ESTOP/local_Kanban/local_worktrees/product_main: NOT_MODIFIED
- coordinator_action: INFORMATIONAL_ACK_ONLY; do not trigger paid agents or automatically merge

### Выполнено и проверено
- PR #50 Codex P2 `discussion_r4282059842`: фактический путь Tool Ledger/SQLite orchestration DB проверяется относительно реального root рабочего каталога; symlinked ancestor недопустим. Исправление сохранено **и в PR #51**, чтобы зависимый merge не откатил защиту. Проверка existing error contract + regression с родительским symlink на agent workspace. Родительские каталоги должны быть управляемы trusted executor и не writable агентами — это staged guard, не безусловное same-inode proof против hostile rename.
- PR #51 Code review P1 `discussion_r4282217195`: `acquire_lease_write_fence` получает SQLite write-lock / PostgreSQL row-lock через условный SQL UPDATE **до** capture current timestamp для lease expiry. Условный terminal consumption `submit/fail` и `renew` не должны принимать разрешение, срок которого истёк пока запрос ждал за блокировкой. Регрессии запускают SQLite `BEGIN IMMEDIATE` и удерживают его за границей срока, ожидая 409 как для `submit`, так и `renew`. Code review P2 `discussion_r4282217201`: устранён устаревший текст документации о неприменяемой атомарной проверке terminal API.
- PR #51 сохраняет атомарный `X-Attempt-Lease` gate для submit/fail с проверкой token hash/owner/generation/current SQL state/TTL; `renew/revoke` CAS и crash quarantine token revocation; дополнительные негативные тесты для missing/forged/expired/revoked token, race revoke-vs-submit, task blocked/terminal, legacy mode.
- В обсуждения PR #50/#51 опубликованы ответы с SHA и подтверждением исправления; **review threads нельзя автоматически считать formally RESOLVED/APPROVED**, требуется финальный human/independent review.

### GitHub CI — EXACT final HEAD
PR #50 `53683e62`: CI SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726232539 ; Quality Gate SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726232586 ; Native agent E2E SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726232548 ; Coordination isolation SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726232516 .
PR #51 `1ee27a08`: CI SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726242334 ; Quality Gate SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726242399 ; Native agent E2E SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726242371 ; Coordination isolation SUCCESS https://github.com/askarahodov/multi-agent-workflow/actions/runs/38726242373 .

### Дальнейший dependency order и открытые угрозы
- Независимый review и staged интеграция **PR #45 → #46 → #47 → #48 → #49 → #50 → #51**, проверять каждый итоговый main SHA и remaining diff; не менять worktree локальных агентов, не force-push/merge out of order.
- #33/#38/#11 **OPEN**: ни HTTP heartbeat, ни terminal submit/fail atomic gate не могут отменить уже начатые чужие side effects без trusted remote tool gateway с подтверждённым worker identity, generation/lease, quiescence/drain и PostgreSQL multi-host fencing. SQLite проверка пути требует защищённых каталожных прав ОС. Без migration/rollback + cross-host E2E не объявлять production-ready.
- Не расходовать платные API, не снимать ESTOP, не авто-повторять прежние `CLAIMED` tool calls, не включать opt-in remote leases в живом workflow без gateway review.

## QA-RSP-20261015-TRUSTED-FS-GATEWAY-HANDOFF
- request: NONE (owner-authorized independent offline development and QA checkpoint)
- verdict: INFO / READY_FOR_REVIEW; production acceptance explicitly NOT_GRANTED
- pr: https://github.com/askarahodov/multi-agent-workflow/pull/52
- head: 87067920d50641b9195b361d0adab6b4297cda36
- branch: feat/trusted-filesystem-tool-gateway
- parent: https://github.com/askarahodov/multi-agent-workflow/pull/51 @ 1ee27a08f9bcfa412d6959567750157501b97994
- issue_comment: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6191148291
- main_at_check: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- paid_providers: NOT_USED; local_worktrees/Kanban/ESTOP/main: NOT_MODIFIED

### Выполнение / закрытая regression
Реализован отдельный opt-in `agent_management.trusted_fs_gateway` для удалённого HTTPS tool-call transport с отдельным `X-Gateway-Key`, `TrustedSqliteAttemptFence` для server-owned run/task/attempt/agent/lease, приватным `SqliteToolLedger` и `ScopedFilesystemExecutor`. Только `read_file` по `src/**` и `write_file` по `out/**`; запрет повторного call ID, внешних путей, недоверенных credentials, небезопасного HTTP и слишком большого payload. Python tool code выполняется на gateway, не на remote worker. SQLite write fence удерживается во время защищённого file I/O; revocation SQL commit ждёт ранее допущенную запись. Gateway не встроен в orchestration API и требует выделенного защищённого deployment.

Root cause старого RED: при first boot привилегированный SQLite ledger не существовал, а строгий existing file containment check требовал его наличия. Fix 87067920: precheck владельца/прав приватного parent, отсутствие symlinks, расположение вне workspace ДО создания, postcheck regular private file ПОСЛЕ создания. Новый `trusted_gateway_from_env` требует секрет из файла 0600 вне workspace. Offline E2E real SQLite+ASGI, включая revoke/inflight barrier; secrets masked. Русский runbook `docs/architecture/trusted-remote-filesystem-gateway.md`.

**Last head PR #52 all checks SUCCESS:** CI 38728361601; Quality Gate 38728361621; Native E2E 38728361611; Coordination isolation 38728361604. Ready for review but NOT MERGED. Automatic Codex review started; do not declare approved until review completes. Do not confuse green CI with successful remote production/multi-host acceptance.

### Dependency / next safe tasks
Strict integration order #45→#46→#47→#48→#49→#50→#51→#52. Branch #52 contains inherited parent changes, so check diff after prior merges and re-run checks on each main SHA; no force pushes/local worktree manipulations.

**P0 OPEN:** trusted `leased_runner` → gateway client adapter is not automatically wired, direct filesystem access from untrusted worker must be OS/container-denied, PostgreSQL/multi-host fencing not implemented, no safe Git/shell/HTTP remote execution and no production TLS secret rotation/cross-host E2E. No exactly-once claims; in-flight external side effect cannot be undone. No paid model runs, no ESTOP changes, no local task changes.

## QA-RSP-20261015-LEASED-GATEWAY-ENDTOEND-HANDOFF
- request: NONE (owner-authorized offline development checkpoint; external QA-owned channel)
- verdict: INFO / READY_FOR_INDEPENDENT_REVIEW; no production acceptance
- parent_pr: https://github.com/askarahodov/multi-agent-workflow/pull/52
- parent_head: 2987497d277cdc19a18d108ddaaf985ae2691411
- child_pr: https://github.com/askarahodov/multi-agent-workflow/pull/53
- child_head: 35cc468d76f30df04fd85bb915729af912d799ba
- issue_handoff: https://github.com/askarahodov/multi-agent-workflow/issues/33#issuecomment-6191556655
- product_main_at_checkpoint: a8f7e4be33218dbba1e60f9c3756fcbaa7477621
- paid_llm: NONE; local_worktrees, Kanban, ESTOP, main: NOT_MODIFIED

### Реализовано на отдельной независимой ветке
`TrustedRemoteFilesystemDispatcher` в `agent-management/trusted_fs_client.py` отправляет только разрешённые file tool_call на уже отдельный HTTPS gateway PR #52, без ambient proxies, redirects, retries, token exposure LLM. `TrustedLeasedGatewayRunner` используется как `NativeHttpWorker(require_lease=True, leased_runner=runner)`, передаёт server-owned task identity и TTL lease только на доверенный executor. `run_agent_loop` расширен строго двумя проверенными dispatcher types (native sync / trusted remote async). При `DUPLICATE_CALL`, `ATTEMPT_FENCED`, network errors, malformed transport response агент прекращает выполнение без submit или автоматического replay.
Полный offline ASGI E2E: Auth-enabled `NativeHttpWorker → Orchestration API → trusted lease → fake provider → run_agent_loop → HTTPS gateway → ScopedFS / SQLite lease fence / durable ledger → verified Contract Gate`. Создаётся файл, есть SUCCEEDED и verified task completion, секреты не в модельных сообщениях. Отрицательные тесты на revoked, redirect, 503, replay, bad origin, policy denial и expired token. Root cause первоначального RED: в новом межсервисном тесте отсутствовал WRITE API key при AuthMiddleware enabled, fixed `b312f1b` конфигурацией реального разрешённого test worker API key; не отключался auth.

### Срочные замечания авто-ревью родителя и их статус
PR #52 Codex P1 `discussion_r4282508870`: добавлена проверка всех каталогов предков orchestration SQLite и ledger; symlink/writable rejected, только sticky shared parent с 0700 service-owned child разрешён. PR #52 Codex P2 `discussion_r4282508880`: не-ASCII `X-Gateway-Key` возвращает sanitized HTTP 401, не 500. Оба исправления перенесены в PR #53; добавлены unit/E2E regression на небезопасные DB paths и raw non-ASCII bytes. Обоим замечаниям даны ответы; после exact HEAD CI **обе ветки review threads resolved=true**.

### GitHub Actions exact SHA evidence (все 4 SUCCESS на каждом PR)
PR #52 SHA `2987497d277cdc19a18d108ddaaf985ae2691411`:
- CI https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730724617
- Quality Gate https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730724906
- Native E2E https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730724598
- Coordination isolation https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730724659

PR #53 SHA `35cc468d76f30df04fd85bb915729af912d799ba`:
- CI https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730733068
- Quality Gate https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730733003
- Native E2E https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730733070
- Coordination isolation https://github.com/askarahodov/multi-agent-workflow/actions/runs/38730733111

### Orchestrator dependency order / manual guard
PR #53 OPEN, Ready for review, **NOT merged**; его Codex review после перевода READY ещё проверить. Ранее все #45–#52 открыты. **НЕ объединять вне dependency order:** #45→#46→#47→#48→#49→#50→#51→#52→#53; каждая stacked ветка содержит родительские коммиты, смотрите residual diff после каждого merge, перепроверяйте main SHA и 4/4 обязательных checks. Никаких платных моделей / Hermes / auto replay, изменения main/локального Kanban/worktree/ESTOP не выполнялись.

### P0 не закрыт
OS/container isolation, реальный remote host, PostgreSQL/multi-host atomic tool gateway, shell/Git/network effects, secure TLS rotation/deployment, crash quiescence и exactly-once пока не приняты. Модель/удалённый worker **не должны** получать DB RW, FS workspace или gateway API secret через prompt. QA acceptance offline ≠ production.
