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
