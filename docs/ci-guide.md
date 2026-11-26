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

Эквивалентный CI между контрольными точками допустим по GF-09 при подтверждённом покрытии всех применимых составляющих. LOCAL_NOT_RUN не равен LOCAL_PASS. Если локальный тест FAIL, сначала расследовать его. Skipped/cancelled/unknown обязательной проверки не являются PASS.

## Ошибки, review и очистка

1. Прочитать фактический failed job/step и лог; исправить причину в той же ветке.
2. Зафиксировать новый SHA и повторно проверить CI. Не переписывать уже рассмотренные коммиты.
3. Указать документы, миграции, риски, rollback и недостающие проверки в PR.
4. Получить независимое review и только затем принять merge. Не отключать required checks ради обхода блокера.
5. Проверить отсутствие принятой удалённой ветки и чистого локального worktree; уникальную работу не удалять. См. [правила required checks](security/gitflow-required-checks-gate.md) и [владение](governance/github-ownership.md).

`coord/external-qa` — отдельная служебная линия, не ветка продукта. История старой редакции руководства доступна в Git; текущие CI команды и workflows проверяются в репозитории, а не по историческим примерам.
