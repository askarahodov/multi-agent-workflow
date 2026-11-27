# CI и GitHub: руководство разработчика

Канонические обязательные правила — AGENT_GITFLOW_RULES.md, включая GF-09 и post-merge cleanup. Это руководство не изменяет branch protection, required checks или полномочия reviewer. Используйте фактический checkout и текущую задачу; не предполагайте универсальный путь рабочего каталога.

## Проверка задачи

Из корня репозитория:

```sh
git status --short
git rev-parse HEAD
gh auth status
gh pr view --json number,headRefOid,baseRefName,reviewDecision
gh pr checks
gh run list --limit 20
gh run view <run-id> --log-failed
```

Команды gh требуют установленного и авторизованного CLI. Не выводить токены, конфигурацию credentials или приватные логи. CI workflow следует проверять на фактическом head и связанном merge SHA; не переносить PASS с предыдущей ревизии.

## Состав проверок

`make check` включает lint, typecheck, backend-test, frontend-check и security. Frontend-check включает unit tests, schema validation и build. Помимо CI и Quality Gate применяются GitFlow Policy, native cross-service E2E, coordination isolation, docs dependency/build/link/browser/audit, worker/gateway preflight, release и другие проверки по области изменения. Источник конфигурации — `.github/workflows/`; список required checks определяется фактическими rulesets.

Буквальный `make check` обязателен в CI на каждом PR по GF-09; локальный запуск может быть заменён подтверждённым эквивалентным CI на актуальных head/base. LOCAL_NOT_RUN не равен LOCAL_PASS. Если локальный тест FAIL, сначала расследовать его. Skipped/cancelled/unknown обязательной проверки не являются PASS.

## Ошибки, review и очистка

1. Прочитать фактический failed job/step и лог; исправить причину в той же ветке.
2. Зафиксировать новый SHA и повторно проверить CI. Не переписывать уже рассмотренные коммиты.
3. Указать документы, миграции, риски, rollback и недостающие проверки в PR.
4. Получить независимое review и только затем принять merge. Не отключать required checks ради обхода блокера.
5. Проверить отсутствие принятой удалённой ветки и чистого локального worktree; уникальную работу не удалять. См. [правила required checks](security/gitflow-required-checks-gate.md) и [владение](governance/github-ownership.md).

`coord/external-qa` — отдельная служебная линия, не ветка продукта. История старой редакции руководства доступна в Git; текущие CI команды и workflows проверяются в репозитории, а не по историческим примерам.

## Обязательный CI_MAKE_CHECK (#358)

`Make Check Checkpoint` запускается на каждом PR (включая stacked и draft), protected push и по ручному dispatch. На PR проверяются `GITHUB_SHA` и ровно два родителя merge commit: event base и head. Результат `Execute exact Makefile target` должен быть success; summary содержит checkout, PR head/base, run/attempt. Проверка `gitflow required checks` ожидает actual PR checkpoint на текущих head/base, не manual или stale run. До подтверждённого обновления ruleset 26129824 его 14 контекстов остаются неизменными; checkpoint — дополнительная норма GitFlow. При rollout администратор добавляет `make check (CI checkpoint)` к существующим контекстам без удаления/ослабления остальных. После каждого изменения base/head требуется свежая проверка. Local NOT_RUN сохраняется; live/стендовые/E2E и review отдельны.

При смене base/head/merge во время polling gate возвращает ошибку; требуется свежий PR run. Для fork PR без GitHub pull_requests association применяется привязанный к exact run/attempt receipt с PR number и merge SHA, плюс проверка head repository/ref. Не принимать ручной запуск или receipt из другой попытки. Реальный fork run требует отдельной приёмки.

При нескольких запусках на одном SHA после редактирования PR `gitflow required checks` проверяет свои два prerequisite jobs строго по current run/attempt/head, а остальные обязательные checks — прежним строгим классификатором. Отменённые текущие jobs и сторонние failed checks не считаются PASS.

Ручной checkpoint запускается командой `gh workflow run make-check-checkpoint.yml --ref main`; он не заменяет PR evidence.
