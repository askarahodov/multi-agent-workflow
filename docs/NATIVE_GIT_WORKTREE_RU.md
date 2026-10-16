# Native Git Worktree — доверенная граница для #11

## Назначение

`TrustedGitWorktreeStore` — новый опциональный компонент control plane (`agent-management/agent_management/trusted_git_worktree.py`), **не** модельный инструмент `git` и **не** оболочка для исполнения произвольных команд. Это проверенный локальный этап на пути к автономному SDLC; сам по себе он не закрывает P0 #11.

Доверенный оператор предоставляет абсолютный путь к предварительно проверенному **локальному** Git-репозиторию с реальным каталогом `.git`, отдельную приватную директорию `0700` для рабочих копий и абсолютный путь к доверенному исполняемому файлу `git`. Каталоги и Git metadata не монтируются в процесс недоверенной модели. Поддерживается POSIX в Linux-контейнере; Windows CMD может запускать только этот Linux-контейнер через Docker, **не** native Windows Git для security boundary.

Вызов `provision(task_id, attempt_id)` создаёт **новый detached worktree на каждую попытку** из исходного HEAD, с отдельным каталогом `out/`. Идентификаторы приходят исключительно от control plane после успешного claim. Повторная попытка создать этот же путь или создать его через traversal запрещена.

Модель может использовать только `read_file` / `write_file` с `ScopedFilesystemExecutor` в разрешённом `out/**`. Модель **не выбирает** Git-аргументы, ветку, commit message, hooks, executable, сеть, ключи или Git config. Стадия `commit(task_id, attempt_id, fence=..., ledger=...)` вызывается **только доверенным координатором** с серверной `TrustedSqliteAttemptFence` и существующим `SqliteToolLedger` (не по пользовательскому tool-call). Она проверяет файлы `out/**`, отклоняет symlink, hardlink, специальные/приватные имена, изменения вне output, превышение 64 файлов или 4 MiB. Доступен только локальный commit; **push, fetch, submodule, shell, hooks и внешние AI CLI не вызываются**.

Перед Git I/O ledger фиксирует отдельную операцию `git-commit-v1` в `CLAIMED`. Если Git успешно создаёт commit, control plane сохраняет результат как неизменяемую ссылку `refs/maw/attempts/<task_id>-<attempt_id>` в доверенном исходном репозитории и переводит ledger в `SUCCEEDED`. При сбое после CLAIMED повтор запрещён: ручной reconciliation обязателен. Исходный HEAD не перемещается, никакой релиз/merge автоматически не публикуется.

## Сквозное offline-доказательство

`tests/native_agent_e2e/test_git_worktree_commit.py` использует **настоящий Git**, настоящий file-backed SQLite, серверную attempt fence и Native Agent Loop. Скрипт провайдера создаёт разрешённый файл, доверенная операция коммитит его в worktree, затем OrchestrationEngine отдельно пропускает JSON-результат через Contract Gate. Проверяются исходный HEAD, сохранённый Git ref, отсутствие повторного commit, отказ после recovery, symlink denial, отсутствие запуска hooks, отсутствие Hermes.

```sh
python -m pytest tests/native_agent_e2e/test_git_worktree_commit.py -q
python -m pytest tests/native_agent_e2e -q
```

## Незакрытые ограничения

- **Текущий production-style HTTPS gateway не вызывает этот модуль автоматически.** Требуется отдельная интеграция opt-in фабрики per-attempt worktree с модельным `ScopedFilesystemExecutor`, контрактно проверенное продвижение Git evidence в серверный state и защита от несанкционированного Git commit в многопроцессном развёртывании.
- Исходный репозиторий должен быть **предварительно проверен оператором**. Это не полноценная изоляция против локального злоумышленника, способного писать `.git` или запускать процессы под UID control plane. Недоверенный Git config, атрибуты, hooks и file filters требуют более строгой проверки для произвольных пользовательских репозиториев.
- Ни `git commit`, ни `summary` от модели не доказывают самостоятельное прохождение tests/review/security. Нужны независимые QA-gates и human approval до release.
- Настоящий OpenRouter smoke без разрешённого API-ключа и лимита расходов не выполняется. #11 и зависящая #8 остаются открытыми.

См. [ADR-111](adr/ADR-111-native-sdlc-dependencies.md) и [Native Worker acceptance](NATIVE_WORKER_ACCEPTANCE_RU.md).
