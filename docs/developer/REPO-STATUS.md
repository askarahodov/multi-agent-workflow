# Состояние разработки Multi-Agent Workflow

> **Срез на 03.11.2026 (UTC), GitHub main `ee06a35ed6ae367dd47bc73ac33d420fa9b5fa5c`.**
> Это журнал подтверждённых фактов на указанную дату, а не живой мониторинг.
> После merge, смены SHA или результатов QA обязательно актуализировать строки
> и проставлять дату и URL фактического CI. Источник истины — GitHub Issues,
> PR, check-runs и отдельно зарегистрированные результаты операторской приёмки.

## Открытая работа и подтверждённые проверки

| Направление | Факт / ссылка | Дальнейший критерий |
| --- | --- | --- |
| #11 — независимый от Hermes автономный SDLC | [Issue #11](https://github.com/askarahodov/multi-agent-workflow/issues/11) открыта. Существуют offline native E2E, UI/browser Compose smoke и Contract Gate | Live OpenRouter tool-call и Git artifact, сквозные семь стадий из UI на чистом Compose, независимый QA, release approval и restart-evidence |
| #8 — локальная приёмка MVP | [Issue #8](https://github.com/askarahodov/multi-agent-workflow/issues/8) открыта; offline Compose/HTTP тесты не заменяют live user acceptance | Подписанный ручной чеклист и реальные logs/screenshots без раскрытия secrets |
| #11/#8 — readiness evidence gate | [PR #228](https://github.com/askarahodov/multi-agent-workflow/pull/228) открыт, head `77d46f42bd1d3f28305a5d419bb8ec102545521c`, **26/26 CI success** | Независимая операторская оценка полного набора evidence; не считать этим PR запуск агента вживую |
| #208 — документационные зависимости | [PR #229](https://github.com/askarahodov/multi-agent-workflow/pull/229) открыт, head `4248e896521e094998189eba8274252323bb700a`, **26/26 CI success** | Повторный Dependabot/network audit после merge и разрешённая приёмка |
| #209 — URL credentials / stream tickets | [PR #230](https://github.com/askarahodov/multi-agent-workflow/pull/230) открыт, head `22725ca871c5219e8261e4c38d2f92c746f3f40f`, **28/28 CI success**. Log-redaction исправлена; ticket mode **default-off** | Security/TESTER/REVIEWER sign-off на точном SHA, проверка внешних прокси/телеметрии, browser reconnect и отдельное rollout-разрешение |
| #192 — GitHub ↔ Kanban | [Объединённый PR #235](https://github.com/askarahodov/multi-agent-workflow/pull/235) интегрирует полную пагинацию, корректное восстановление cursor/ETag, fail-closed CI/close gate, автоматический цикл Issues → PR → linked comments/HANDOFF → CI → retry → publish, восстановление после restart, late binding и защиту от потери публикации при 401/rate-limit. Прежние зелёные [PR #231](https://github.com/askarahodov/multi-agent-workflow/pull/231) и [PR #232](https://github.com/askarahodov/multi-agent-workflow/pull/232) служат аудитируемыми источниками и **заменяются единым PR #235**, а не добавляются к обязательным merge. Есть SQLite+HTTP mock E2E, но не live host acceptance | Требуются зелёные CI **на последнем head #235**, независимый review, реальный операторский GitHub ↔ Kanban прогон и квитанции доставки после restart. До этого Issue #192 OPEN |
| #44 — защита main | Живой [ruleset 26129824](https://github.com/askarahodov/multi-agent-workflow/rules/26129824): active, 14 required contexts, запрет прямых/force pushes, но **0 approving reviews**. [PR #233](https://github.com/askarahodov/multi-agent-workflow/pull/233) — read-only ruleset audit, [PR #234](https://github.com/askarahodov/multi-agent-workflow/pull/234) — fail-closed дополнительный GitFlow checks diagnostic; у каждого **26/26 CI success** на собственном SHA, они ещё не merged | Владелец/admin включает ≥1 независимый approval, dismissal stale reviews, resolution threads только после producer PR smoke; Issue #44 OPEN |
| #3 — Docker host risk | [Issue #3](https://github.com/askarahodov/multi-agent-workflow/issues/3) отложена для trusted local-only | До публичного deployment — отдельный security review и риск-решение |

## Политика обновления документации

1. **Каждый PR вместе с кодом** обновляет затронутый runbook, ограничения и регрессионные команды. Код без соответствующих документов считается незавершённым.
2. Проверка CI указывается **с точным head SHA, числом success/failure/pending и URL PR**. Старый зелёный SHA не подтверждает новый коммит.
3. **Секреты и URL с параметрами авторизации не публикуются.** В evidence допустимы безопасные пути в репозитории или публичные URL без userinfo/query/fragment. Реальные ключи — только в защищённом хранилище.
4. PR может быть технически зелёным, но **MVP accepted**, **production approved**, **independent Security/QA PASS** и **merged** являются разными статусами. Не утверждать их без отдельной проверки.
5. При обновлении статуса сверять [Issues](https://github.com/askarahodov/multi-agent-workflow/issues), [PR](https://github.com/askarahodov/multi-agent-workflow/pulls), [Actions](https://github.com/askarahodov/multi-agent-workflow/actions) и текущий ruleset. После merge заменять устаревшие ссылки и HEAD, не переписывать историю тестов.

## Где инструкции и доказательства

- [Локальная ручная приёмка](../qa/LOCAL-MANUAL-ACCEPTANCE.md) — инструкция для проверок, не сертификат приёмки. Evidence-readiness gate до merge находится в PR #228.
- [Stream-ticket rollout](stream-ticket-rollout.md): default-off, credential rotation, отключение legacy URL keys только после отдельного approval.
- [GitHub ↔ Kanban runbook](github-kanban-sync-runbook.md): связка Issues/PR/CI, процесс работы с required checks и точные условия закрытия Issue.
- [Безопасное включение защиты main](../security/main-protection-rollout-issue-44.md): GitHub rules, отрицательные проверки, переход локальных producer.
