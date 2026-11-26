# Сопровождение веток GitFlow

GF-06/GF-07/GF-10: немедленная очистка после принятого merge без потери уникальных коммитов. Отсутствие upstream не является доказательством squash merge.

- `cleanup-branches.py` проверяет локальные ветки относительно опубликованных origin targets. Только достижимый точный tip допускается к условному удалению; missing upstream с уникальной историей только выводится для разбора. Защищены main/master/develop, release/*, hotfix/*, coord/*, текущая ветка и дополнительные --protect. При ошибке fetch применение отменяется. Git не удаляет ветку из активного worktree.
- `audit-remote-branches.py` через gh CLI с read-only token перечисляет **все** удалённые ветки и PR (с pagination), учитывает открытые PR, включая stacked base, и точный head закрытого merged PR с достижимым merge SHA. Не удаляет ничего.
- Существующий Branch Cleanup Audit запускается ежедневно и после push в main, выводит remote inventory и выполняет тесты. GitHub native Automatically delete head branches остаётся предпочтительным механизмом удаления обычных веток после merge.
- Для squash-merged локальной ветки с уникальной историей требуется точный PR receipt, сохранение работы, проверка отсутствия локальных изменений и отдельная подтверждённая процедура. Никогда не используйте upstream gone как единственный аргумент для -D.

## Команды

```sh
git fetch --prune origin
python scripts/git/maintenance/cleanup-branches.py --dry-run
python scripts/git/maintenance/audit-remote-branches.py --repo askarahodov/multi-agent-workflow
python -m pytest scripts/git/maintenance/tests -q
```

Реальное локальное удаление только подтверждённых достижимых веток: `python scripts/git/maintenance/cleanup-branches.py --yes --maintenance-window --prune-remotes`. На агентском хосте сначала проверить worktree и статус, затем пользоваться штатным lifecycle. Cron только dry-run; старые apply-записи удалить. Удаление remote-tracking ref не удаляет ветку на GitHub. Результаты cleanup проверять повторным инвентарём, не по успешному exit code одного шага.

## Разбор старых веток

Сначала проверить точный HEAD, открытые PR как source/base, связь с исходной задачей, историю и принятую замену. Для ветки старше 24/48 часов — актуализация/эскалация по GF-03; старше 7 дней — явное решение по GF-08. Не обновлять дату коммитом без полезной работы. Не открывать новый PR вместо старого без обоснования. Никогда не удалять release/hotfix/служебную ветку автоматически. Данные external QA хранятся отдельно от product main.

### Безопасность штатного worktree lifecycle

`scripts/git/worktree-lifecycle.py cleanup` больше не использует принудительное удаление веток/worktree, даже с устаревшим параметром `--force-guard`. Хук post-merge только сообщает о pending cleanup. Проверяются фактическая принадлежность worktree задаче, неотслеживаемые и игнорируемые пользовательские файлы, достижимость коммита из опубликованного origin/main (свежий fetch), а также отсутствие remote ref через ls-remote. При сохранённой удалённой ветке, недоступном origin, уникальном squash tip без доказательства или неизвестном результате сохраняются данные и возвращается BLOCKED. Обычный remote cleanup обеспечивает GitHub auto-delete после принятого merge; оставшиеся refs разбираются аудитом с учётом PR dependencies. Локальный lifecycle не удаляет remote refs без возможности проверить эти зависимости. Полный squash-cleanup остаётся отдельным проверяемым операторским действием, не обходить его force-флагом.

Штатный `.agent-gitflow.env` распознаётся только при точном соответствии содержимому policy bundle текущей задачи и ожидаемым путям, без выполнения shell-кода. Изменённый файл, symlink, временный `.agent-gitflow.env.tmp` и произвольные env-файлы остаются пользовательскими/неподтверждёнными данными и блокируют cleanup. Регрессионная проверка использует тот же `claim --emit-env`, что dispatcher.

## Очистка подтверждённых исторических refs через GitHub Actions

После принятия этого PR в main открыть Actions → Branch Cleanup Audit → Run workflow (main). Обычный PR, push и schedule остаются read-only. Для разовой уборки зафиксирован набор 10 exact SHA из аудита 26.11.2026 (#345, включая комментарии 7184903726 и 7185017187). Не расширять список автоматически.

1. На время операции согласовать окно без параллельной работы/изменений refs и PR; остановить конкурирующих агентов, проверить **все** авторитетные локальные клоны и worktree. Повторно подтвердить актуальность семантического аудита относительно main; если перенос больше не доказан, не продолжать.
2. Запустить mode=archive на main. Job с read-only token проверяет exact SHA, защиту, open PR head/base, полный checkout и baseline ancestry. Создаёт bundle и manifest с SHA256, сохраняет artifact reviewed-branch-archive. Ничего не удаляет.
3. Скачать artifact успешного запуска, проверить manifest, `git bundle verify` и восстановление всех refs в отдельном пустом репозитории; сохранить в долговременном доверенном архиве вне GitHub Actions (retention ограничен). Репозиторий публичный: artifact содержит историю уже публичных refs; если выявлены чувствительные данные, не запускать archive и использовать согласованное приватное архивирование.
4. При неизменном main и после подтверждения всех worktree и сохранения архива запустить mode=apply на main, указать ID успешного archive run и строку `ARCHIVE_SAVED_WORKTREES_CHECKED`. Только этот manual job запрашивает contents: write. Он скачивает проверенный artifact, сверяет run identity, main SHA, manifest, checksum, bundle refs, перечень открытых PR, protection и exact tips, выполняет единый atomic push с explicit leases. Нет fallback на force/unleased/non-atomic deletion. При любой ошибке или неизвестном результате не повторять запись до новой проверки.
5. Проверить отсутствие всех 10 remote refs (ls-remote), затем отдельно привести локальные клоны/worktree в порядок по GF-07. CI не видит хостовые worktree, не подтверждает их отсутствие и не закрывает Issues. GitHub rules/permissions могут запретить удаление; не обходить защиты.

Отдельно: Quality Gate уже выполняет backend/frontend/lint/security составляющие make check; это не утверждение о запуске полного локального make check, на integration checkpoint. Запуск archive/apply через UI или авторизованный gh workflow run; connector не предоставляет workflow dispatch. Никогда не запускать apply из PR-ветки.

`--no-fetch` допустим исключительно в `--dry-run`. Любое удаление (включая interactive) требует успешного fresh fetch --prune и повторной проверки опубликованных целей; ошибка прекращает операцию. Локальный dry-run с недоступным remote может быть устаревшим и не служит разрешением удаления.


### Защита от гонки при локальной очистке (GF-07)

`git branch -d` проверяет настроенный upstream и не связывает удаление с ранее проверенным SHA. Штатный lifecycle вместо этого проверяет точный tip и опубликованную цель и использует единую Git ref-транзакцию с verify target SHA и delete expected branch SHA. Любое изменение одного из refs блокирует удаление. Проверяются зарегистрированные worktree; detached, locked или prunable worktree считаются неизвестным состоянием и блокируют операцию. Настройки branch.* автоматически не удаляются без отдельной проверки. Это не force-delete и не разрешение на удаление squash/unmerged refs.

Git ref-транзакция не блокирует создание worktree/checkout сторонним процессом или изменение удалённого сервера. Применение только с явным `--maintenance-window` после остановки всех агентов и иных Git-писателей, проверки worktree и подтверждения отсутствия remote ref. Общая неблокирующая flock-блокировка в git-common-dir сериализует штатный lifecycle create/cleanup, bulk apply и spawn-agent. Конфликт блокировки возвращает BLOCKED; файл блокировки не удалять. Сторонние Git-команды и уже работающие агенты не обязаны брать lock: флаг является операторским подтверждением, а не автоматическим доказательством отсутствия процессов. Не передавать его из cron/post-merge. Не запускать apply до принятия PR. Точечная очистка: `python scripts/git/worktree-lifecycle.py cleanup --task t_1234abcd --maintenance-window --merge-sha <SHA>`.
