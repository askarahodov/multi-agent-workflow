# Сопровождение веток GitFlow

GF-06/GF-07/GF-10: немедленная очистка после принятого merge без потери уникальных коммитов. Отсутствие upstream не является доказательством squash merge.

- `cleanup-branches.py` проверяет локальные ветки относительно опубликованных origin targets. Только достижимый tip можно удалить через `git branch -d`; missing upstream с уникальной историей только выводится для разбора. Защищены main/master/develop, release/*, hotfix/*, coord/*, текущая ветка и дополнительные --protect. При ошибке fetch применение отменяется. Git не удаляет ветку из активного worktree.
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

Реальное локальное удаление только подтверждённых достижимых веток: `python scripts/git/maintenance/cleanup-branches.py --yes --prune-remotes`. На агентском хосте сначала проверить worktree и статус, затем пользоваться штатным lifecycle. Cron по умолчанию dry-run. Удаление remote-tracking ref не удаляет ветку на GitHub. Результаты cleanup проверять повторным инвентарём, не по успешному exit code одного шага.

## Разбор старых веток

Сначала проверить точный HEAD, открытые PR как source/base, связь с исходной задачей, историю и принятую замену. Для ветки старше 24/48 часов — актуализация/эскалация по GF-03; старше 7 дней — явное решение по GF-08. Не обновлять дату коммитом без полезной работы. Не открывать новый PR вместо старого без обоснования. Никогда не удалять release/hotfix/служебную ветку автоматически. Данные external QA хранятся отдельно от product main.

### Безопасность штатного worktree lifecycle

`scripts/git/worktree-lifecycle.py cleanup` больше не использует принудительное удаление веток/worktree, даже с устаревшим параметром `--force-guard`. Хук post-merge не передаёт этот параметр. Проверяются фактическая принадлежность worktree задаче, неотслеживаемые и игнорируемые пользовательские файлы, достижимость коммита из опубликованного origin/main (свежий fetch), а также отсутствие remote ref через ls-remote. При сохранённой удалённой ветке, недоступном origin, уникальном squash tip без доказательства или неизвестном результате сохраняются данные и возвращается BLOCKED. Обычный remote cleanup обеспечивает GitHub auto-delete после принятого merge; оставшиеся refs разбираются аудитом с учётом PR dependencies. Локальный lifecycle не удаляет remote refs без возможности проверить эти зависимости. Полный squash-cleanup остаётся отдельным проверяемым операторским действием, не обходить его force-флагом.
