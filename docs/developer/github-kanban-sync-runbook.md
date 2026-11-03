# Runbook: двусторонняя синхронизация GitHub ↔ локальный Kanban (`github-kanban-sync`)

> Инструмент разработки (Issue #192). Это **не** runtime‑зависимость продукта
> AI Multi Agent Workflow (ref #11): ни один модуль продукта
> (`orchestration-server/`, `agent-management/`, docker‑образы) его не импортирует.
> Изоляция `coord/external-qa` не затрагивается; области, зарезервированные под
> #182 (`frontend/`, `.github/workflows/*`, `Makefile`, `README.md`, …), не
> изменяются.

## 1. Что это и зачем

Локальный Kanban (`~/.hermes/kanban/boards/me/kanban.db`) — исполнительная
очередь локальных агентов. GitHub Issues в репозитории — публичный журнал задач.
Инструмент держит между ними **одно уникальное соответствие** и переносит
изменения в обе стороны, не создавая второй очереди и не дублируя комментарии.

```
GitHub Issues/PR/CI ──(ingest: poll или webhook)──► карточка Kanban (комментарий владельцу)
      ▲                                                        │
      └──────(publish: версионированный комментарий)◄──────────┘
```

Компоненты (`tools/github_kanban_sync/`):

| Модуль | Роль |
| --- | --- |
| `links.py` | Контракт ID: `repo + issue_number` ↔ `board + task_id`, PR/branch/SHA/owner/changed_paths/status |
| `store.py` | Локальный журнал (SQLite, отдельная БД `coordination-sync.db`): события, доставки, курсоры, снапшоты, резервации |
| `github.py` | Клиент GitHub REST: ETag/304, обработка rate‑limit, backoff, редактирование секретов |
| `kanban.py` | Чтение карточек и запись комментариев/событий в `kanban.db` |
| `ingest.py` | GitHub → Kanban (Issues/PR/CI) с идемпотентностью по `source_event_id` (журнал **и** маркер на доске) |
| `ci_evidence.py` | Общая fail-closed классификация CI и подтверждение каждого настроенного required check |
| `publish.py` | Kanban → GitHub: статус/assignee/blocker/branch/PR/evidence в **связанную** Issue; закрытие только по merge+CI+acceptance |
| `conflict.py` | Пересечения `changed_paths`, резервации, устаревший `main` — только отчёт |
| `webhook.py` | Проверка `X-Hub-Signature-256` + приёмник (опциональный ускоритель) |
| `scheduler.py` | Автозапуск: цикл `sync` по интервалу, экспоненциальный backoff, учёт rate-limit, pidfile, корректное завершение по сигналу |
| `observability.py` | health/status/lag/pending/retries, журнал доставки, correlation id, состояние планировщика |
| `cli.py` | Операторские команды |

Инварианты безопасности: инструмент **наблюдает и уведомляет**, он никогда не
делает `rebase/reset/merge/checkout/delete` чужих веток и worktree, не пишет вне
`~/.hermes/kanban/boards/me/` и файлов синхронизации, не хранит токен в логах и
коммитах.

## 2. Контракт ID (Issue #192 §1)

Соответствие `repo + issue_number` ↔ `board + task_id` хранится в таблице
`issue_link` (уникально по обоим направлениям) со полями:
`pr_number`, `branch`, `base_sha`, `head_sha`, `owner`, `changed_paths`,
`status`, `source_event_id`, `updated_at`.

* Повторная привязка той же пары — идемпотентное обновление полей.
* Привязка уже занятого Issue/карточки к другому контрагенту — ошибка
  (`LinkConflict`, rc 23); чтобы перепривязать явно, нужен `--force`.
* **Ручная привязка существующих карточек** — командой `bind`; активные карточки
  не клонируются и не создаются автоматически.

## 3. Настройка

### 3.1 Зависимости

Требуется Python ≥ 3.12 (репозиторий использует `httpx`, который уже в
зависимостях) и авторизованный `gh` CLI **либо** токен в переменной окружения.

```bash
# из корня репозитория
python -m pip install -e ./tools      # httpx и pytest; сам пакет синхронизации входит в tools
```

### 3.2 Переменные окружения

| Переменная | Назначение | Обязательна |
| --- | --- | --- |
| `GKS_REPO` | `owner/repo` (по умолчанию `askarahodov/multi-agent-workflow`) | нет |
| `GKS_BOARD` | slug доски (по умолчанию `me`) | нет |
| `GKS_COORD_DB` | путь к журналу синхронизации | нет |
| `GKS_KANBAN_DB` | путь к `kanban.db` | нет |
| `GKS_GITHUB_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN` | токен GitHub. Если не задан — берётся `gh auth token` | да |
| `GKS_WEBHOOK_SECRET` | секрет для проверки подписи webhook (только при использовании webhook) | нет |
| `GKS_REQUIRED_CHECKS` | имена **всех** обязательных checks активного ruleset для `main`, разделённые запятой; без настройки `close` запрещён | только для `close` |

> Токен никогда не логируется и не коммитится. Минимально необходимые права:
> чтение Issues/PR/CI — всегда; запись (комментарии, закрытие Issue) — только если
> используется `publish`/`close`. Дополнительных прав инструмент не требует.

### 3.3 Linux

```bash
export GKS_REPO=askarahodov/multi-agent-workflow
export GH_TOKEN="$(gh auth token)"
python -m tools.github_kanban_sync.cli health
```

### 3.4 Windows (PowerShell)

```powershell
$env:GKS_REPO = "askarahodov/multi-agent-workflow"
$env:GKS_GITHUB_TOKEN = (gh auth token)
python -m tools.github_kanban_sync.cli health
```

CLI одинаков на обеих платформах; отличаются только способ установки переменных
(`export` против `$env:`).

## 4. Ежедневная эксплуатация

### 4.1 Проверить состояние

```bash
python -m tools.github_kanban_sync.cli status     # связи, курсоры, pending, журнал доставки, health
python -m tools.github_kanban_sync.cli health     # 0 — здоров, 1 — нездоров (lag/errors), 2 — ошибка инструмента
python -m tools.github_kanban_sync.cli reconcile  # найденные связи, карточки без Issue, Issues без карточки
python -m tools.github_kanban_sync.cli dedupe --task <task-id>   # удалить дубли ingest-комментариев на карточке
```

`health` показывает `lag_seconds` (возраст последнего снапшота), `pending_events`
(события без доставки) и `errors` (неудачные доставки).

### 4.2 Один полный цикл

```bash
# GitHub -> Kanban (Issues + PR + комментарии связанных Issue + CI по SHA)
# и Kanban -> GitHub (связанные Issue), включая retry pending
python -m tools.github_kanban_sync.cli sync

# только приём, только отправка
python -m tools.github_kanban_sync.cli ingest --all
python -m tools.github_kanban_sync.cli publish

# сухой прогон (без записи): состояние + конфликты
python -m tools.github_kanban_sync.cli sync --dry-run
```

### 4.3 Привязать карточку к Issue (ручная привязка существующей задачи)

```bash
python -m tools.github_kanban_sync.cli bind --issue 192 --task t_02d18f3e \
    --owner sdlc-developer --branch wt/t_02d18f3e
python -m tools.github_kanban_sync.cli unbind --issue 192
```

Ошибка `already linked ... pass force=True` (rc 23) означает, что одна из сторон
уже привязана; используйте `--force`, только если действительно нужно
перепривязать.

### 4.4 Publish обратно в связанную Issue

При `publish` в **ту же** Issue пишется один версионированный комментарий с
маркером `<!-- gks:v1 issue=<N> channel=publish rev=<R> -->`; повторный запуск
**обновляет** его, а не добавляет новый. Если содержимое не изменилось — записи
нет вовсе (`unchanged`). Частота ограничена (`--force` игнорирует и дедуп, и
rate‑limit). Номер ревизии `rev` монотонно растёт; после полного сброса журнала
он восстанавливается из живого маркера Issue, поэтому сброс **не откатывает**
`rev` назад. Поиск уже опубликованного маркера тоже обходит **все** страницы
GitHub comments через общий безопасный paginator: сброс локального журнала
и большой поток обсуждений не должны создавать второй статус-комментарий.

Обычный `sync`/daemon также публикует **начальное состояние** явно привязанной
существующей карточки, даже если её последние события были обработаны до
выполнения `bind`. Инструмент обновляет только уже связанную Issue, никогда не
создаёт новую. **Курсор Kanban task_events сдвигается только после успешной
обработки всех изменений**. При GitHub 401/403/5xx или rate-limit публикация
остаётся в очереди до следующего цикла; уже опубликованные карточки проходят
дедуп через стабильный хеш тела и `rev`. При rate limit результат
`publish.cursor_advanced=false`; после восстановления — `true`.
Отдельный тест `test_gks_publish.py` проверяет оба отказа.

### 4.5 Удалить задублированные ingest-комментарии

Доставка GitHub→Kanban идемпотентна на уровне доски (маркер несёт полный
`source_event_id`), поэтому повторов быть не должно. Если карточка уже была
загрязнена прошлыми прогонами, дубликаты убираются командой:

```bash
python -m tools.github_kanban_sync.cli dedupe --task <task-id>          # оставить по одному на тело
python -m tools.github_kanban_sync.cli dedupe --task <task-id> --all    # удалить все ingest-комментарии (чистая доставка заново)
```

Команда идемпотентна, трогает только комментарии своего инструмента
(`channel=ingest`) и синхронно чистит соответствующие `comment.added` события.

## 5. Webhook (опционально, ускоритель)

Poll остаётся авторитетным; webhook лишь ускоряет доставку и обязан сходиться с
poll по тому же `source_event_id`.

```bash
# приёмник на локальном порту (для теста; публичный ingress не требуется)
python -m tools.github_kanban_sync.cli webhook-serve --host 127.0.0.1 --port 8765 \
    --secret "$GKS_WEBHOOK_SECRET"
```

В GitHub: Settings → Webhooks → Add webhook, Payload URL = ваш endpoint,
Content type = `application/json`, Secret = `GKS_WEBHOOK_SECRET`, события:
`issues`, `issue_comment`, `pull_request`, `push`, `workflow_run`, `check_suite`.
Подпись `X-Hub-Signature-256` **обязательна**: без неё и при неверной подписи
запрос отклоняется (HTTP 401) без побочных эффектов.

Если endpoint недоступен (частый случай — приватный хост без публичного
ingress), webhook не нужен: poll каждые 5 минут полностью покрывает потребность.

## 6. Автозапуск (scheduler/daemon)

Публичного ingress у хоста нет, поэтому **авторитетный транспорт — poll**, а
`webhook` (§5) остаётся опциональным ускорителем. Команда `daemon` крутит один и
тот же цикл `sync` (**Issues → PR → comments/HANDOFF у связанных карточек → CI на привязанных PR/merge SHA → retry pending → publish**) по интервалу, без ручных шагов:

* **инкрементально** — каждый цикл переиспользует курсоры/ETag журнала
  (`store.cursor`). Для одностраничного фида неизменённая страница может
  ответить `304`. Для многостраничного фида `ETag` **первой** страницы не
  сохраняется; ETag также не сохраняется, если единственная страница уже
  заполнена ровно 100 записями и может перейти в две страницы без изменения
  первой. Даже неизменная первая страница не доказывает, что дальше нет
  новых событий. Все страницы Issues/PR/comments/check-runs сначала читаются
  полностью; только затем курсор сдвигается. Сбой страницы №2+ не фиксирует
  частичные данные и не продвигает курсор;
* **комментарии + CI автоматически** — вручную привязанные Issue обследуются
  на каждом цикле на новые комментарии, в том числе `MIGRATION_182_HANDOFF`;
  CI проверяется по уникальным корректным 40-символьным Git SHA из связей,
  а результат доставляется **каждой** карточке, связанной с SHA. Некорректные
  SHA пропускаются и видны в `linked.invalid_shas`; излишних обращений к GitHub
  по неподтверждённым SHA нет;
* **durable retry** — ошибки доставки из SQLite (`pending_events`) повторяются
  независимо от high-water cursor. После повторного просмотра ранее
  «unlinked» Issue новый `bind` запускает backfill без новой карточки;
  маркер `source_event_id` предотвращает повтор комментария на доске;
* **backoff** — временные сбои GitHub (5xx/транспорт) и исчерпанный rate-limit
  поглощаются экспоненциальной паузой; `RateLimited.reset` уважается (с потолком
  `backoff_cap`), бесконечного спиннинга нет;
* **ограничен и управляем** — `--once`/`--max-iterations` ограничивают прогон,
  pidfile не даёт запустить второй демон, `SIGINT`/`SIGTERM` и `--stop`
  останавливают его корректно (никакого «вечного» процесса без способа остановки).

### 6.1 Включить

```bash
cd /path/to/repo
export GKS_REPO=askarahodov/multi-agent-workflow
export GH_TOKEN="$(gh auth token)"          # или GKS_GITHUB_TOKEN
python -m tools.github_kanban_sync.cli daemon --interval 300 &
# либо под systemd (см. 6.5), либо в foreground без '&'
```

Каждый цикл пишет одну JSON-строку в stdout (`event=cycle.ok|cycle.transient_error|
cycle.rate_limited|cycle.github_error|cycle.error|daemon.start|daemon.stop`) с
`correlation_id`, счётчиками `new_events`/`published`, `next_in` и `healthy`.

Переменные окружения планировщика (все необязательны):

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `GKS_SYNC_INTERVAL` | `300` | секунд между успешными циклами (`--interval`) |
| `GKS_SYNC_JITTER` | `0` | случайная добавка `0..jitter` секунд к интервалу |
| `GKS_SYNC_BACKOFF_BASE` | `5` | первый шаг backoff после сбоя |
| `GKS_SYNC_BACKOFF_CAP` | `900` | максимальная пауза / ожидание rate-limit |
| `GKS_PIDFILE` | `~/.hermes/kanban/boards/me/gks-daemon.pid` | pidfile (один писатель) |

### 6.2 Выключить

```bash
python -m tools.github_kanban_sync.cli daemon --stop          # SIGTERM по pidfile
# либо: kill -TERM "$(cat ~/.hermes/kanban/boards/me/gks-daemon.pid)"
```

`--stop` ждёт завершения (до `--stop-timeout`, по умолчанию 10 с) и убирает
pidfile; устаревший pidfile (процесса нет) также очищается. Демон завершает
текущий цикл, закрывает соединения и пишет `daemon.stop` — состояние остаётся в
`coordination-sync.db`, ничего не теряется.

### 6.3 Диагностика

```bash
python -m tools.github_kanban_sync.cli status   # блок "scheduler": status/iteration/next_run_at + health
python -m tools.github_kanban_sync.cli health   # 0 здоров, 1 нездоров (lag>max_lag или errors), 2 ошибка
python -m tools.github_kanban_sync.cli daemon --once   # один ручной цикл (см. 6.4)
```

`health` показывает `lag_seconds` (возраст последнего снапшота; растёт, пока
циклы не проходят), `pending_events`, `errors`, `consecutive_failures` и
`scheduler_status`. Если демон упал, `scheduler_status` остаётся последним
(`running`/`degraded`), а `lag_seconds` превысит `max_lag` — это и есть сигнал.

### 6.4 Ручной прогон

```bash
python -m tools.github_kanban_sync.cli daemon --once     # ровно один цикл, затем выход
python -m tools.github_kanban_sync.cli daemon --max-iterations 3
python -m tools.github_kanban_sync.cli sync              # тот же цикл без демона (совместимо)
```

Ручной прогон идемпотентен: повторная доставка не создаёт дублей (§4.5).

### 6.5 Резервный вариант — cron (без долгоживущего процесса)

Если долгоживущий демон нежелателен, тот же цикл запускается из cron; backoff и
rate-limit в этом случае обеспечиваются внутри одного вызова (`github.py`), а
инкрементальность — журналом между запусками:

```cron
*/5 * * * * cd /path/to/repo && GH_TOKEN="$(gh auth token)" \
  python -m tools.github_kanban_sync.cli sync >> ~/.hermes/logs/gks-sync.log 2>&1
```

### 6.6 Откат

* **Остановить автозапуск:** `daemon --stop` (или убрать cron-запись) — состояние
  остаётся в `coordination-sync.db`, события копятся как `pending`.
* **Возобновить:** снова запустить `daemon` (или вернуть cron) — pending‑события
  доставятся, дублей не будет (дедуп на уровне журнала **и** доски).
* **Полный сброс:** см. §9 — удаление журнала безопасно для доски (маркер
  ingest-комментария несёт полный `source_event_id`, `rev` publish‑комментария
  восстанавливается из живого маркера Issue).

Устойчивость (для обоих вариантов): журнал в отдельной БД (WAL) и идемпотентность
по `source_event_id` позволяют безопасно перезапускать цикл после offline/restart —
повторные события не доставляются дважды. Дедуп двухуровневый: уровень журнала
(`coord_event`) **и** уровень доски — маркер ingest-комментария несёт полный
`source_event_id`, поэтому даже потеря журнала не приводит к повторной доставке
комментария на карточку.

### 6.7 Проверка полноты Github poll (Issue #192)

GitHub отдаёт до 100 элементов на одну страницу. Раньше успешная первая
страница могла скрыть последующие Issues, PR, комментарии владельцу или
check-runs: синхронизатор считал выгрузку завершённой и сохранял курсор.
Теперь клиент обходит `Link: rel="next"` по номерам страниц, **не использует
URL из ответа как место назначения** (защита токена). Официальный алиас
`/repositories/{id}` разрешён лишь после сверки ID через запрос к
своему `/repos/{owner}/{repo}`. Контролируются хост, путь, page/per_page.
Лимит составляет 1000 страниц за вызов; превышение — ошибка, не потеря.

Доставка в Kanban после полного чтения сохраняет дедупликацию
`source_event_id`. Изменения во время чтения могут сдвигать страницы: если
ID повторяется, клиент начинает выгрузку заново; при повторной нестабильности
отказывает без изменения курсора. Даже без дублей смещение может пропустить
запись. Поэтому многостраничный Issues poll продвигает курсор только до
**максимального updated_at первой страницы минус 1 секунда** (перекрытие для
совпадающих времён). Следующий poll повторно охватит границу; для комментариев
с разным порядком создания/редактирования многостраничный cursor вообще
не продвигается до одностраничной выгрузки. Это дороже по API, но предотвращает
невосполнимую потерю HANDOFF. Если GitHub/сеть возвращают 5xx на поздней
странице, backoff выполняется с прежним курсором. Для check-runs итоговый
`total_count` сверяется с полученными записями: неполный набор не зелёный.

```bash
cd tools
python -m pytest tests/test_gks_github.py tests/test_gks_ingest.py -q
python -m pytest tests/test_gks_*.py -q
python -m tools.github_kanban_sync.cli status
```

**Обновление со старой версии:** прежняя реализация сохраняла `ETag`
первой страницы и могла продвинуть `since` мимо невидимых страниц.
Новая версия один раз на каждый feed (Issues, PRs, comments конкретной Issue)
выполняет **полный** обход без старого `ETag` и `since` — даже если прежняя
высокая отметка была записана ошибочно. Все события проходят прежнюю
идемпотентную доставку. После успешного полного чтения SQLite хранит
маркер `gks:paginated-etag:v2:...`; только тогда допускается использование
нового безопасного `ETag` для короткой одностраничной выборки. Если страница
содержит 100 элементов или страниц больше одной, старый `ETag` **явно
очищается** (`clear_etag=True`), а не сохраняется через `None`.
Если многостраничный комментарий не даёт безопасную границу,
унаследованный `since` тоже **явно очищается** (`clear_cursor=True`).
Передача `None` без флага сохраняла бы старое значение и могла вновь
пропускать HANDOFF. Аналогично очищается небезопасный старый cursor Issues,
если первую страницу нельзя использовать для надёжной отсечки.
Если проход прерван, маркер не появляется и следующий цикл повторит
восстановление. Первое обновление может потребовать больше API-запросов;
проверяйте GitHub rate limit и запланируйте запуск на доверенном хосте.

Проверяйте `pending_events`, `last_error`, `delivery_journal` и точный
`source_event_id`. Не добавляйте реальные токены и URL с авторизацией в
документируемые логи. Пагинация и offline-тесты **не являются доказательством**
live локальной двусторонней приёмки Kanban на доверенном хосте. Для #192
нужен отдельный подтверждённый operator-run с настоящей карточкой, переходом
состояния и проверкой после перезапуска.

## 7. Конфликты и ручное разрешение

```bash
python -m tools.github_kanban_sync.cli conflict --live-main "$(git rev-parse origin/main)"
python -m tools.github_kanban_sync.cli reserve --scope frontend/ --issue 182   # резервация владельца
```

* `critical` (`path_overlap` с точным путём, `reservation`, `stale_main`) → задания
  по этому пути не выдаются до разрешения;
* `warn` (та же чувствительная директория) — информация для владельца.

**Разрешает владелец ветки, не инструмент.** Порядок: владелец синхронизирует
свою ветку с `main` самостоятельно (rebase/merge своей ветки), затем повторно
запускает `conflict`; `stale_main` устраняется свежим `git fetch` + новым `sync`.
Инструмент **никогда** не делает rebase/reset/merge/delete чужих worktree.

## 8. Закрытие GitHub Issue — строгая проверка CI

**Без явного списка обязательных checks автоматическое закрытие выключено**
(`ci_unconfigured`). Список берётся из **живого** GitHub ruleset `main`, а не
из локального YAML. На 03.11.2026 действующий ruleset имеет ID `26129824`:
перед каждым rollout проверьте, не изменился ли он или перечень contexts.

```bash
# Linux: прочитать актуальные required contexts (read-only)
gh api repos/askarahodov/multi-agent-workflow/rulesets/26129824 \
  --jq '.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context'
# Затем перенести ВСЕ выведенные имена в одну строку через запятую.
# Например, только как синтаксис (не полный список для этого репозитория):
export GKS_REQUIRED_CHECKS="quality gate,gitflow policy validation,..."
python -m tools.github_kanban_sync.cli close --issue 192
```

Windows CMD: выполните ту же команду `gh api`, затем задайте полный перечень
без кавычек вокруг отдельных имён: `set "GKS_REQUIRED_CHECKS=check1,check2,..."`.
Запись `...` выше — **плейсхолдер**, запускать с ним нельзя. Имена должны
совпадать с GitHub **точно**, включая регистр и пробелы. Список также можно
вывести через `gh api repos/askarahodov/multi-agent-workflow/rulesets` и найти
активный `main` ruleset при смене ID.

Issue переводится в `closed` только после merge связанного PR, подтверждённого
зелёного состояния **каждого** настроенного required context на **merge SHA**,
наличия acceptance evidence и завершённой карточки. Каждый элемент
`acceptance_tests` должен содержать непустую `command` и подтверждённый
успешный `result` (`passed`, `success`, `ok`, `pass` либо
положительный pytest summary); хотя бы один `failed`, `pending`, `skipped`,
пустой или некорректный результат блокирует закрытие с причиной
`invalid_acceptance_evidence`. Синтаксическая проверка локальной записи
не является независимой аттестацией — оператор обязан проверить артефакты
и все критерии Issue перед выдачей `GKS_CLOSE_APPROVED_ISSUES`.
Статусы `skipped`,
`cancelled`, `failure`, `neutral`, `pending` и `unknown` не дают
закрывать Issue. Клиент запрашивает **все страницы** check-runs (по 100 на запрос),
сопоставляет итог с `total_count` и отказывает при несовпадении;
неполный, сбойный или неоднозначный ответ GitHub — не зелёный CI.

```bash
python -m tools.github_kanban_sync.cli close --issue 192
# Возможные причины отказа: ci_unconfigured, ci_unknown, ci_pending,
# ci_failure, pr_not_merged, no_acceptance_evidence,
# invalid_acceptance_evidence, closure_not_approved, task_not_done
```

Код завершения команды: **0 только после фактического закрытия Issue**,
**1 при отказе по правилам гейта** (результат и причина в JSON);
**2 при ошибке вызова/среды**. Это важно для скриптов агентов:
не считайте отсутствие traceback подтверждением закрытия.

Один только `done` в Kanban **не** закрывает Issue. Не переносите список
из другого репозитория и не включайте `close` до проверки актуальных
required checks (Issue #192, §3). Код не подтверждает независимый review и
не подменяет проверку правил GitHub администратором.

## 9. Отключение и восстановление потока

* **Приостановить:** удалите/закомментируйте cron‑запись. Ничего не ломается —
  состояние остаётся в `coordination-sync.db`, следующие события просто накопятся
  как `pending`.
* **Возобновить:** верните cron и один раз выполните `sync` — pending‑события
  доставятся, дублей не будет.
* **Полный сброс:** остановите cron, удалите файл журнала `coordination-sync.db`
  (связи `issue_link` при этом теряются — их нужно привязать заново через `bind`).
  Сброс **безопасен для доски**: маркер ingest-комментария несёт полный
  `source_event_id`, поэтому повторный `sync` не создаёт дублей на карточках, а
  `rev` published-комментария восстанавливается из живого маркера Issue.

## 10. Наблюдаемость

`status` печатает: список связей, курсоры фидов, `pending_events` (с `attempts` и
`last_error`), `delivery_journal` (последние доставки с `correlation_id`) и
`health`. Для разбора конкретного события:

```bash
python -m tools.github_kanban_sync.cli trail \
  --event-id "askarahodov/multi-agent-workflow:issue_comment:192:6519063860"
```

## 11. Проверка (acceptance)

```bash
cd tools && python -m pytest tests/test_gks_*.py -q
```

Негативные пути покрыты: неверная подпись webhook, rate‑limit, 5xx‑backoff,
утечка токена в сообщениях об ошибке, отсутствие прав (401), запрет закрытия
Issue без merge/CI/acceptance, дедуп poll↔webhook, дедуп на уровне доски после
сброса журнала, очистка дублей ingest‑комментариев, защита от feedback‑loop.

Планировщик покрыт отдельно (`test_gks_scheduler.py`): один цикл ingest+linked comments/CI+retry+publish
со снапшотом (реальные `last_sync`/`lag`), экспоненциальный backoff и его потолок,
учёт `RateLimited.reset`, остановка по запросу, защита pidfile от второго запуска,
`daemon --stop` без/с устаревшим pidfile, устойчивость цикла к неинициализированной
доске, и блок `scheduler` в `status`/`health`.

### 11.1 Интеграционный offline E2E (все части одного цикла)

```bash
python -m pytest tools/tests/test_gks_integrated_flow.py -q
```

Тест использует **настоящие SQLite-таблицы локального Kanban и журнала**, но
GitHub HTTP заменён на `httpx.MockTransport`. Дополнительный сценарий
проверяет PR/CI, связанные сразу с двумя карточками, отказ SQLite при
доставке второй карточке и возобновление без дублей после restart. Он проверяет двухстраничные
Issues/комментарии, доставку HANDOFF, CI в карточку владельца, обратную
публикацию в ту же Issue без feedback loop, восстановление после перезапуска,
backfill позднего bind и запрет закрытия до merge + всех required CI + evidence
+ `done`. Это **не** независимый live E2E на Hermes-хосте и не санкция на
запись в production GitHub Issue.

### 11.2 Как подтвердить live приёмку на операторском хосте

1. На действующем доверенном хосте откройте **текущую** карточку Kanban;
   не создавайте дубликат. Сначала `sync --dry-run` и `status`, затем
   `bind --issue <TEST_ISSUE> --task <EXISTING_TASK>` с согласия владельца.
2. В отдельной тестовой GitHub Issue создайте и отредактируйте комментарий
   `TEST_HANDOFF`; `daemon --once` должен записать событие и один
   комментарий в карточке. Повторение цикла не добавляет дублей.
3. Измените status/blocker/branch **в существующей карточке** и запустите
   `daemon --once`; убедитесь, что обновился **один** `gks:v1 ... channel=publish`
   комментарий в той же Issue (не новая Issue).
4. Создайте тестовый PR и дождитесь полного набора required CI. Убедитесь,
   что CI-событие дошло до владельца; `close --issue` с незавершённой
   карточкой возвращает **rc=1**. Никаких реальных `close` на продуктивной #192.
5. Остановите демон, перезапустите его и повторите `daemon --once`.
   Проверьте `status`, `trail`, `pending_events`, отсутствие повторных
   комментариев и факт доставки в журнале. Сохраните IDs/SHA, скриншоты и
   обезличенные логи в отдельной записи evidence. Не публикуйте токены.
6. Только после независимого sign-off владельца, QA и CI решается merge PR
   и закрытие #192. **Зелёный offline CI не равен live acceptance.**

Демонстрация автозапуска **без ручных шагов** — `tools/github_kanban_sync/daemon_probe.py`
(герметично: фейковый GitHub + временная доска); транскрипт —
`docs/developer/evidence/github-kanban-sync-daemon-2026-10-30.md`.


## Автоматическая независимая проверка миграции #182 (экспериментальный контракт)

Этот режим включается **только** на локальном хосте оркестратора, где есть
работающая доска Hermes. GitHub Actions не имеют доступа к локальной базе
Kanban и не запускают локальных агентов.

1. Через **поддерживаемый Hermes Kanban CLI/API** создайте или выберите одну
   независимую QA-карточку (исполнитель `sdlc-tester`, не `sdlc-developer`),
   переведите её в `ready`. Не изменяйте `kanban.db` вручную.
2. На локальном хосте задайте `GKS_MIGRATION_QA_TASK_ID=t_...` — идентификатор
   существующей карточки. Запустите обычный `python -m
   tools.github_kanban_sync.cli sync` либо существующий cron/poll.
3. При новом коммите в PR, ссылающемся на #182, синхронизатор отправляет
   **один** запрос с точным 40-символьным SHA в эту карточку и фиксирует
   `review_requested`. Ошибка доставки не должна помечать PR-событие
   обработанным. Маркер `gks:qa-request` предотвращает повторное сообщение.
4. Диспетчер Hermes должен отдельно подтвердить `claimed → spawned → running`.
   Доставка комментария **сама по себе не запускает воркер**; завершённая
   (`done`) карточка не перезапускается самостоятельно. Для следующего SHA
   локальному диспетчеру требуется поддерживаемый механизм requeue.
5. Агент публикует `MIGRATION_182_ACCEPTANCE: APPROVED` или
   `CHANGES_REQUESTED` с точным SHA в Issue #182. При проверке одобрения
   задавайте список доверенных GitHub-логинов QA: комментарии других авторов
   не являются независимым вердиктом. При изменении SHA старый результат
   утрачивает силу.

**Пока не реализовано:** автоматическое создание/requeue карточки через
локальный Hermes API, реальное подтверждение запуска и привязка вердикта
к обязательной GitHub branch-protection check. Поэтому этот режим нельзя
считать полностью автономным и нельзя автоматически сливать PR по факту
доставки сообщения. В частности, секрет GitHub не следует передавать
в задачу агента или её комментарии.

### Read-only gate for the live PR head

After the independent QA agent posts its receipt, an operator or a locally
scheduled job can run:

```bash
python -m tools.github_kanban_sync.cli review-check \\
  --issue 182 --pr 194 --trusted-author YOUR_QA_GITHUB_LOGIN
```

Exit code `0` means a trusted QA author has approved the **current** GitHub
PR head SHA; `1` means no valid approval (missing, rejected, or outdated), and
`2` indicates a tool/API error. This is **read-only** and does **not** merge,
change a Kanban task, or install any GitHub required status check. It is not a
substitute for CI, branch protection, or local worker start evidence.
