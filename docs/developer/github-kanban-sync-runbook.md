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
| `publish.py` | Kanban → GitHub: статус/assignee/blocker/branch/PR/evidence в **связанную** Issue; закрытие только по merge+CI+acceptance |
| `conflict.py` | Пересечения `changed_paths`, резервации, устаревший `main` — только отчёт |
| `webhook.py` | Проверка `X-Hub-Signature-256` + приёмник (опциональный ускоритель) |
| `observability.py` | health/status/lag/pending/retries, журнал доставки, correlation id |
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
# GitHub -> Kanban (Issues + PR) и Kanban -> GitHub (связанные Issue)
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
`rev` назад.

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

## 6. Планировщик (cron)

```cron
*/5 * * * * cd /path/to/repo && GH_TOKEN="$(gh auth token)" \
  python -m tools.github_kanban_sync.cli sync >> ~/.hermes/logs/gks-sync.log 2>&1
```

Устойчивость: журнал в отдельной БД (WAL) и идемпотентность по `source_event_id`
позволяют безопасно перезапускать `sync` после offline/restart — повторные
события не доставляются дважды. Дедуп двухуровневый: уровень журнала
(`coord_event`) **и** уровень доски — маркер ingest-комментария несёт полный
`source_event_id`, поэтому даже потеря журнала не приводит к повторной доставке
комментария на карточку.

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

## 8. Закрытие GitHub Issue

Issue переводится в `closed` **только** при подтверждённых: merge связанного PR +
зелёные required CI на merge‑commit + acceptance‑evidence в карточке:

```bash
python -m tools.github_kanban_sync.cli close --issue 192
# {"issue":192,"closed":false,"reason":"pr_not_merged|ci_failure|no_acceptance_evidence|task_not_done"}
```

Один только `done` в Kanban **не** закрывает Issue — это осознанный гейт (§3
Issue #192).

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
cd tools && python -m pytest tests/test_gks_*.py -q     # 67 тестов
```

Негативные пути покрыты: неверная подпись webhook, rate‑limit, 5xx‑backoff,
утечка токена в сообщениях об ошибке, отсутствие прав (401), запрет закрытия
Issue без merge/CI/acceptance, дедуп poll↔webhook, дедуп на уровне доски после
сброса журнала, очистка дублей ingest-комментариев, защита от feedback‑loop.


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
