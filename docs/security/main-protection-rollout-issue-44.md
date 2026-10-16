# Защита `main`: инвентаризация и безопасный rollout (Issue #44)

> Состояние проверено 16.10.2026 на `main` (`ea6cdfabc571a4b2a7e58fae5529594b692639ea`). Это **план перехода**, а не утверждение о включённой защите. Изменение GitHub settings выполняет владелец после проверок.

## 1. Подтверждённые факты

- `GET /repos/askarahodov/multi-agent-workflow/branches/main`: `protected=false`.
- `GET /repos/askarahodov/multi-agent-workflow/rulesets`: `[]`.
- GitHub App не имеет гарантированного доступа к изменению branch protection. Не считать `403` свидетельством конкретного значения настройки.
- В `AGENT_GITFLOW_RULES.md` правила GF-05/GF-09 требуют PR + review + quality gate, но **пока не обеспечиваются серверной защитой**. Текст правила — policy, не enforcement.
- Имеются активные PR #1, #79, #87, #88. Их нельзя закрывать, переписывать или обходить ради rollout.
- Существуют `feat/issue-*`, `fix/issue-*`, `wt/t_*`, `coord/external-qa` и другие долгоживущие ветки; наличие ветки само по себе не доказывает, что её агент пушит в `main`.
- `.github/workflows/quality-gate.yml`: aggregate job `quality gate`, `pull_request` для всех веток.
- `.github/workflows/ci.yml`: PR в `main`/`develop`, без aggregate job.
- `.github/workflows/native-agent-e2e.yml`: check `Native LLM-tool-Contract Gate (offline)` для PR в `main`.
- `.github/workflows/coordination-isolation.yml`: check `Reject external QA channel files in product main` для PR в `main`.
- Все required checks следует выбирать **по именам реальных check runs, найденным на свежем PR**, а не просто по имени workflow в YAML.

## 2. Карта producers и допустимых путей

| Producer / канал | Наблюдаемый branch pattern | Целевой путь в main | Проверка до включения защиты |
| --- | --- | --- | --- |
| Ручные product изменения | `feat/*`, `fix/*`, `docs/*`, `security/*` | branch → PR → CI → независимый review → merge | PR открывается, все checks публикуются |
| Локальные Kanban/worktree агенты | `wt/t_*` | own worktree → own branch → PR → CI → review → merge | Проверить **реального** автора push/merge, runner и credentials; не предполагать готовность |
| Native product workers | `feat/issue-*`, `fix/issue-*` (наблюдаемые ветки; ownership не доказан) | isolated workspace → scoped branch → PR, без прямого push в main | Проверить конкретный dispatch/merge механизм на тестовом PR |
| Dependabot | `dependabot/*` | PR → CI → review → merge | Проверить PR #1, отсутствие bypass |
| External QA | `coord/external-qa` | **Никогда не merge в product main**; только отдельный evidence channel | Isolation check и отсутствие `.coordination/external-qa/**` в product PR |
| Emergency human admin | отдельный документированный hotfix | PR предпочтителен; исключительный recovery — только с audit trail | Проверить доступ владельца и восстановление настроек |

**Не подтверждено:** полный список host-side processes, их персональные credentials, фактические direct pushes и auto-merge routes. Для этих сведений требуется безопасная инвентаризация на хостах. Не заявлять, что миграция завершена, пока каждый действующий producer не прошёл PR smoke.

## 3. Инвентаризация на Linux и Windows CMD

Следующие команды только читают данные (требуют `gh auth login`, выполненный владельцем заранее; не выводить токены).

```bash
gh api repos/askarahodov/multi-agent-workflow/branches/main --jq '{name,protected}'
gh api repos/askarahodov/multi-agent-workflow/rulesets
gh pr list --state open --json number,headRefName,baseRefName,author,url
gh run list --limit 20
gh api "repos/askarahodov/multi-agent-workflow/commits?per_page=30" --jq '.[] | [.sha[0:12],.commit.message,.author.login] | @tsv'
```

CMD поддерживает эти же `gh` команды; **не требуется PowerShell/ps1**. Для диагностики каждого хостового producer дополнительно изучить его конфигурацию dispatch/merge, не копируя secrets и не останавливая сервис. Зафиксировать: process/service, identity, branch, push target, PR creation, merge actor, CI evidence, tested PR number, blocker.

## 4. Preflight — обязательно до изменения GitHub settings

1. Проверить текущий HEAD и отсутствие незавершённых конфликтующих migrations. Снять backup текущих rulesets/settings вручную через UI или `gh api`, если разрешён read.
2. Создать тестовый PR **каждого используемого типа producer** без изменения production и без публикации external QA evidence.
3. Для каждого PR получить `gh pr checks <number>` и `gh api repos/askarahodov/multi-agent-workflow/commits/<sha>/check-runs`; записать имена и результаты check runs. Не использовать только push checks, они могут не совпадать с PR checks.
4. Подтвердить, что `quality gate`, `Native LLM-tool-Contract Gate (offline)`, `Reject external QA channel files in product main` реально появляются на PR. Для отсутствующих имён сначала исправить triggers/путь доставки checks; **не включать блокировку вслепую**.
5. Проверить review независимо от автора PR. Если нет независимой reviewer identity, решить этот governance blocker с владельцем до требования approval.
6. Доказать один нормальный PR → green checks → review → merge для каждого producer (можно использовать отдельные harmless PR). Не трогать PR #1/#79/#87/#88.
7. Убедиться, что external QA branch продолжает обновляться независимо от product main.

## 5. Настройка GitHub владельцем (после preflight)

GitHub → repository → Settings → Rules → Rulesets (или Settings → Branches для branch protection) → создать правило только для `main`:

- Require pull request before merging; require ≥1 approval от независимого reviewer, dismiss stale approvals по возможности; запретить обход через обычные worker identities.
- Require status checks to pass before merging, выбирая **точные** имена, полученные на PR. Начальный кандидат: `quality gate`, `Native LLM-tool-Contract Gate (offline)`, `Reject external QA channel files in product main`. Отдельный `CI` check назначать обязательным только после подтверждения его check name и успешного PR пути.
- Require branch to be up to date, если это совместимо с потоком merge; не включать queue без теста.
- Block force pushes and branch deletion; не включать bypass для worker identities. Отдельно решить политику administrators/emergency recovery.
- Нельзя интерпретировать skipped/neutral/missing required check как успех. Проверить поведение **реальным negative PR**, поскольку условия workflow и GitHub rulesets могут отличаться.

**Важное:** `quality gate` имеет `if: always()` и принудительно проверяет `needs`; это защищает от проваленных/skipped подзадач на уровне aggregate. Проверка `native-agent-e2e` и `isolate-coordination` самостоятельна, поэтому требуется отдельная branch rule.

## 6. Verification matrix (record actual PR and run IDs)

| Сценарий | Ожидаемое поведение |
| --- | --- |
| PR без required check | merge заблокирован |
| PR с failing check | merge заблокирован |
| PR с pending/cancelled/skipped required check | merge заблокирован |
| PR без независимого approval | merge заблокирован |
| Прямая запись worker в `main` | отклонена сервером, без force |
| Force push / удаление `main` | отклонены |
| Green PR + независимый approval | штатный merge возможен |
| PR добавляет `.coordination/external-qa/**` | isolation check красный и merge заблокирован |
| Push в `coord/external-qa` | продолжает работать независимо |

Для доказательства direct push используйте **неразрушительный** dry-run и/или тестовую worker identity без попыток переписать main. Не отправлять `git push --force` в production branch для проверки запрета.

## 7. Rollback и incident recovery

- Если после включения защиты локальный producer перестал создавать/обновлять PR: **не отключать все checks автоматически**. Зафиксировать symptom, PR/run IDs, причины и вернуть producer на branch-only режим до исправления.
- Если заблокированы все штатные merges из-за ошибочно названного required check: admin временно корректирует только соответствующий required check по документированной процедуре, фиксирует время/автора/причину и повторяет negative/positive gate tests.
- Не удалять защиту `main` как стандартный rollback; emergency bypass — решение владельца с audit trail.
- Сохранять запись о прежних settings, о времени активации, точном ruleset ID, исключениях и ответственных.

## 8. Acceptance / checkpoint

- [x] Получен baseline `protected=false`, `rulesets=[]`; инвентаризированы workflows и branch patterns.
- [x] Зафиксированы миграционный путь, check кандидаты, negative matrix, CMD/Linux проверки и безопасный rollback.
- [ ] Названы/проверены **все** пишущие в main host-side producers и actor identities.
- [ ] Все producer types прошли smoke PR.
- [ ] Владелец применил server-side rules после preflight.
- [ ] Реальные PR/run IDs доказывают negative и positive enforcement.

Задачу #44 нельзя закрывать только по этому документу. До реальной активации и проверки rules `main` остаётся незащищённым.
