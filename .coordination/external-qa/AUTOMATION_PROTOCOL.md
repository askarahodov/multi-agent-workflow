# Automated local Kanban ↔ external QA synchronization (v1)

Дата введения: 2026-10-13. Этот документ **дополняет**, но не отменяет `README.md`.
Исполнение: **локальный координатор**, на том же хосте, где доступны Hermes CLI, Kanban DB, gateway logs и git repo. Внешний ChatGPT не имеет доступа к этим локальным ресурсам.

## Назначение и права

- Local Kanban = **единственный источник истины** для статусов задач, DAG и владельцев. Не создавать GitHub Issues как замену Kanban.
- `coord/external-qa` = обмен данными, **не вливать в `main`**.
- Координатор единолично пишет `requests.md`, `status/current.md` и **`QA_DASHBOARD.md`**; при необходимости создает `status/history/*.md` и `evidence/*.md` (санитизированные отчёты).
- ChatGPT единолично пишет `responses.md` через GitHub. Координатор **не изменяет** `responses.md`; только читает.
- Каждый ответ ChatGPT должен иметь уникальный `QA-RSP-...`; каждое сообщение координатора — уникальный `QA-REQ-...`, при ответе указывается `in_reply_to: QA-RSP-...`.
- GitHub `main`/PR/CI = доказательства состояния кода, но **не** source of truth о состоянии локальной Kanban.

## Периодичность

- Cron запускает **лёгкую синхронизацию раз в 15 минут** на машине координатора и **событийную публикацию** после значимого checkpoint: изменение статуса, тест, архитектурный/QA gate, появление блокера.
- В каждом проходе рендерить **`QA_DASHBOARD.md`** из одного и того же актуального snapshot, объединяя проверенные результаты `responses.md` и ссылки на GitHub. Обязательно отделять **статусы, сообщённые координатором**, от **вердиктов внешнего QA**; при отсутствии проверенного live-значения писать `UNKNOWN`. Показывать временную метку исходного snapshot и не объявлять ручной dashboard автоматически обновляемым, пока cron не прошёл тесты.
- Публиковать `status/current.md`, `QA_DASHBOARD.md` и новые coordinator-owned `requests.md` **в одном commit**, если изменилось содержимое. Эти файлы принадлежат локальному координатору; ChatGPT после первичной публикации не должен редактировать Dashboard в рамках ежечасного ревью.
- В каждом cron проходе **не вызывать LLM**, если нет нового ответа QA, требующего содержательной обработки. Генерировать `status/current.md` детерминированным скриптом из актуальных данных.
- **Не делать commit/push**, если собранный статус и новые ответы не изменились (исключение — новая временная отметка не должна сама запускать commit каждые 15 минут).
- Для больших журналов публиковать только агрегаты и безопасные фрагменты; полный runtime лог и персональные сведения не выгружать.

## Содержимое status/current.md

Записывать новый snapshot полностью, атомарно, на основании фактических локальных CLI/БД и GitHub:

```yaml
snapshot_id: UTC-YYYYMMDDTHHMMSSZ
collected_at_utc: YYYY-MM-DDTHH:MM:SSZ
source: local-hermes-kanban+git+gateway+ci
source_status: VERIFIED | PARTIAL | UNAVAILABLE
project: multi-agent-workflow
repo_main_sha: <git rev-parse origin/main>
local_branch_sha: <если отличается>
active_provider_profiles: <названия, без секретов>
cost_budget: <явный лимит / UNKNOWN>
active_workers: <число и статус>
rate_limited_events_since_last: <число / UNKNOWN>
spawn_failures_since_last: <число / UNKNOWN>
kanban_boards: [me, default] # только реально доступные
task_counts: {todo: 0, ready: 0, running: 0, review: 0, blocked: 0, done: 0}
ci_latest: <URL + result, не предполагать success без проверки>
last_qa_response_processed: <QA-RSP-id либо NONE>
publish_state: <выставляет publisher после проверенного remote push>
```

После YAML-заголовка:
1. **Изменилось с прошлого snapshot:** список task IDs, old → new, владелец, доказательство, commit SHA.
2. **Текущий приоритет и dependency order:** что реально заблокировано и чем; не переписывать устаревшие предположения ChatGPT.
3. **Активные и недавно изменённые задачи:** task ID, доска, название, реальный status, owner, blockers/edges, number of attempts, last failure reason, source revision/worktree, timestamp.
4. **Последние завершённые задачи:** task ID, evidence Git commit/PR, CI/workflow tests, outcome; не просто `done`.
5. **QA-ответы:** новая рекомендация, принято/отклонено/требует доказательств и почему, связанные локальные ID.
6. **Риски и известные ограничения** включая quota walls, invalid-workspace, конфликт веток и бюджет платного провайдера.
7. **Отчёт о доступности источников:** любой недоступный источник помечать `UNKNOWN/UNAVAILABLE`, а не подставлять старое значение как текущее.

Все временные метки — с часовым поясом (рекомендуется UTC). Если задач много, полную машинную выгрузку хранить **локально**; в GitHub публиковать сжатую актуальную таблицу и изменения.

## Обработка replies из responses.md

1. `git fetch origin coord/external-qa`; считывать **remote** `responses.md`, не локальную устаревшую копию.
2. Извлекать уникальные заголовки `QA-RSP-...`; сравнивать с durable local `processed_response_ids` (SQLite/JSON во внешнем служебном каталоге). Дедупликация по ID и SHA содержимого ответа.
3. Для каждого нового ответа: зарегистрировать факт получения; сопоставить замечания с существующими задачами Kanban; **проверить** фактические статусы перед действиями; не создавать дубликаты задач; выполнять только разрешённые действия.
4. Если ответ содержит `APPROVED`, `CHANGES_REQUESTED`, `BLOCKED`, требования доказательств — отразить их в существующей задаче и подготовить `QA-REQ-...` с `in_reply_to: QA-RSP-...`, `outcome`, `affected_tasks`, `evidence`, `open_questions`.
5. Для рекомендаций, предполагающих остановку живых процессов, расход денег, изменение secrets или release, **не выполнять самовольно**. Запросить одобрение владельца или вернуть явный `NEEDS_APPROVAL`.
6. Помечать ответ `processed` **только после** того, как Kanban update (если применимо) и ответ опубликованы либо durable staging безопасно переживает сбой. При перезапуске не допускать повторного применения побочных эффектов.
7. Не считать изменение одного `responses.md` поводом для массового повторного запуска всех workers.

## Надёжная публикация (избежать "local commit != GitHub")

- Один процесс за раз (lock с recovery). Использовать **отдельный временный служебный worktree**, созданный от актуального `origin/coord/external-qa` после `git fetch`. Не переиспользовать активные `wt/t_...` агентов.
- Собирать и добавлять **только** `requests.md`, `status/current.md`, `QA_DASHBOARD.md` и безопасные coordinator-owned evidence.
- Перед записью sanitize: убрать API tokens, .env values, HTTP Authorization, любые персональные данные, приватные полные логи.
- `git commit` → обычный `git push origin HEAD:refs/heads/coord/external-qa`, **без force**; при non-fast-forward пересоздать staging от свежего remote, переиграть только coordinator-owned изменения, не теряя входящие QA responses; повторить ограниченное число раз.
- Проверить **удалённое** состояние: `git ls-remote origin refs/heads/coord/external-qa`, затем `git fetch` и `git show origin/coord/external-qa:.coordination/external-qa/requests.md` / `status/current.md`. Убедиться, что новый ID и snapshot реально видны на remote.
- Публикация успешна **только после** этой проверки. Локальный SHA без remote evidence — `PUBLISH_FAILED`. При ошибке сохранить локальную очередь публикации и сигнализировать координатору.

## Ответ координатора — формат записи в requests.md

```md
## QA-REQ-20261013-002
- in_reply_to: QA-RSP-20261013-HERMES-DISPATCHER-INCIDENT
- kind: ACK | EVIDENCE | REVIEW_REQUEST | QUESTION
- source_snapshot: status/current.md @ <commit SHA>
- local_tasks: <точные IDs и доски>
- action_taken: <реально выполнено / не выполнено, причина>
- evidence: <GitHub SHA/PR/CI или обезличенные локальные выдержки>
- remaining_blockers: <список либо NONE>
- next_checkpoint: <событие, не обещание успеха>
```

Старые QA-REQ записи не удалять. Меняющиеся статусы публиковать в status/current.md, а не плодить постоянные однотипные запросы.

## Критерии приёмки автоматизации

1. 3 последовательных cron-прохода без правок: **нет ненужных commits** и нет платных LLM-вызовов.
2. Изменение статуса задачи в локальном Kanban появляется в **удалённом** status/current.md.
   Одновременно изменяется `QA_DASHBOARD.md`; опубликованный commit содержит **оба** файла. При статусе `done` без доказательств показывать «отмечено done в Kanban», а не «принято внешним QA».
3. Новый `QA-RSP-...` обрабатывается **ровно один раз**; ответ в requests.md содержит `in_reply_to` и подтверждённые task IDs/evidence.
4. Одновременный commit ChatGPT в responses.md не теряется при публикации coordinator-owned файлов.
5. Non-fast-forward, отсутствие сети, частично записанный snapshot, stale lock и сбой в середине обработки восстанавливаются без потери данных/дубликатов.
6. Инварианты: 0 force-push, 0 правок responses.md локальным скриптом, 0 секретов, 0 автоматических GitHub Issues, 0 вмешательств в активные agent worktrees.
7. Координатор показывает проверенные remote SHA, commit, actual Kanban updates и лог dry-run + live tests.

## Важное ограничение

Локальный cron может публиковать данные и отвечать на существующие сообщения QA, но **не вызывает ChatGPT автоматически**. Чтобы внешний QA *сам* читал новые записи в будущем, нужен отдельный запущенный ChatGPT-сеанс, ручная команда пользователя «проверь QA-обмен» или явно созданная повторяющаяся автоматизация ChatGPT. Не обещать постоянное двустороннее общение лишь потому, что есть Markdown-файл.
