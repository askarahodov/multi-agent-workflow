# Аудит готовности MVP: первый запуск и блокирующие разрывы (09.11.2026)

**Статус: NO-GO для пользовательской приёмки и production release.** Это технический аудит кода и GitHub, а не диагностика локальной машины оператора. Скриншоты пользователя показывают `Request failed (HTTP 500)` на первом шаге «Настройка проекта» и «Не удалось загрузить настройки. Проверьте agent-management» в интерфейсе провайдера. Снимки **не содержат** HTTP response body, container logs, версию поднятого образа или SQL trace. Установить точный источник серверного HTTP 500 по скриншотам невозможно; не объявлять его устранённым без runtime evidence.

## Структурный review и факты

| Severity | Область | Проверяемый факт / код | Последствие | Приёмка |
| --- | --- | --- | --- | --- |
| **P0** | First-run wizard | До PR #305 `ProjectSetupWizard.refresh` объединял `listProjects`, `listAgentDefinitions`, `listModelProfiles`, `listToolPolicies` одним `Promise.all` | HTTP 500 одного сервиса скрывал проекты другого | PR #305: независимая обработка failures; tests + Compose browser create project/workspace |
| **P0** | Provider Settings | До PR #304 успешный `POST /providers` мог сопровождаться отказом `await load()` при ошибке unrelated GET; UI сообщал «не сохранено» после фактического сохранения | Риск дублирующих ключей/провайдеров, невозможность пройти onboarding | PR #304: POST=201 является persistence boundary, повторная загрузка не отменяет успех; браузер + real HTTP |
| **P0 — непроверено в runtime** | Backend 500 | `agent-management` и `orchestration-server` стартуют через `create_all`, а orchestration `migrations.py` добавляет таблицы, **не** сверяет/меняет существующие колонки | Старый SQLite schema при обновлении может вызывать SQL exception даже при зелёном `/health` | Сопоставить фактические schema и версии с SQLAlchemy metadata в копии DB; тест старой БД, backup, additive migration и rollback до любых prod изменений |
| **P0** | End-to-end runtime | #11/#8 остаются открытыми: нет принятого оператором evidence на реальный семистадийный SDLC, paid provider call, Git evidence, independent QA, human release | Нельзя утверждать «готовый автономный продукт» по unit/CI | Полный утверждённый `docs/qa/PILOT-READINESS.md`, без Hermes и без подмены live на mock |
| **P0/P1** | Agent profiles/runtime | #254 + PR #301: backend ревизии/бюджеты и native offline snapshot уже разработаны, но live revocation, global native enforcement, scopes/role eligibility и полный UI не приняты | Опубликованная конфигурация не обязательно соблюдается всем runtime | Независимый end-to-end dispatcher policy + profile edit/revoke/restart с отказом устаревшим task attempts |
| **P1** | Workflow editor | #253: граф должен сохраняться как immutable revision и исполняться точно по нему; unsupported nodes fail closed | Пользователь видит конфигуратор без гарантии работы графа | Browser → save → publish → reload → run, graph/contract checks |
| **P1** | Run UX | #256: режимы worker, evidence, retry/recovery и release approval не должны отображать ложную готовность | Сложно диагностировать blocked state | Run-centric история, blocked reasons, ticket reconnect, restart |
| **P1 security** | Live streaming | #209: SSE/WS ephemeral tickets существуют как opt-in; legacy URL api_key path требует отдельного approved rollout | Возможная утечка credentials через URL/logging | Security + Browser reconnect review, ticket expiration/replay/rotation |
| **P1 governance** | GitHub merge gate | Ruleset main активен, required CI проверяются, но `required_approving_review_count=0` (проверено через GitHub API) | Зеленые CI без независимого APPROVED могут быть merged | Владелец включает и отрицательно тестирует >=1 независимый approval (#44) |
| **P1 security** | Local runtime | `dev/docker-compose.yml` отключает AUTH и использует `privileged` + `/var/run/docker.sock` для hardening сервиса | Недопустима публичная экспозиция dev Compose | Только доверенная loopback разработка; security-reviewed isolated runtime до public deploy |
| **P1 dependencies** | Root docs | PR #302 устраняет найденные CI root npm audit HIGH advisories в отдельной ветке; не влияет на работу настроек | Security/CI параллелен пользовательскому блокеру | Exact-head docs build/audit/independent review; не смешивать с #305 |

## Почему прежние зелёные тесты недостаточны

`.github/workflows/quality-gate.yml` выполнял реальный Compose/Chromium только при определённых changed paths; изменения `ProjectSetupWizard.tsx` / `SettingsPage.tsx` могли не запустить этот дорогой сценарий, хотя React unit tests были зелёными. PR #305 добавляет эти paths к real Compose acceptance. Существующий `apps/frontend/e2e/compose-acceptance.spec.ts` проверяет создание проекта и провайдера на disposable backend, но пользовательский мастер первого запуска ранее не имел отдельного сквозного сценария.

Проверять нужно **оба** окружения: (1) чистый одноразовый Compose с корректным encryption key; (2) неразрушительную копию существующей БД с данными прошлой версии. Fresh DB SUCCESS не подтверждает схему на обновлённой БД. Ни `GET /health == 200`, ни `npm run build`, ни отсутствие ошибок Vitest не подтверждают пользовательский сценарий в старой локальной установке.

## Read-only проверка существующей схемы agent-management

После резервного копирования пользовательской БД, **без удаления и без миграций**,
можно проверить недостающие таблицы/столбцы командой внутри запущенного
dev Compose (команда ничего не меняет):

```bash
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml exec -T agent-management python -m agent_management.schema_audit
```

Завершение с кодом `0` означает наличие всех ожидаемых ORM-таблиц и
столбцов; код `1` сообщает только имена отсутствующих таблиц/столбцов;
код `2` — недоступность/неисправность подключения. Содержимое строк,
секреты и DATABASE_URL не выводятся. Эта проверка **не валидирует**
типы столбцов, индексы, внешние ключи, data migration и шифрование;
`PASS` не равен подтверждению корректности всех пользовательских данных.
На старой копии БД перед восстановлением сервиса нужен отдельный план
миграции и rollback. Не применять `drop_all`, удаление SQLite или
автоматическую перегенерацию ключа как «исправление».

## Минимальная блокирующая матрица приёмки: без платного API

1. Снять версии/commit SHA развёрнутых сервисов; проверить `docker compose ps` и только безопасные строки логов `orchestration-server` и `agent-management` вокруг 500. **Не** публиковать ключи, Authorization headers, query credentials, переменные окружения или dump БД.
2. Через адрес браузера `http://127.0.0.1:5173` и Vite proxy запросить `GET /api/v1/projects`, `GET /api/v1/providers`, `GET /api/v1/model-profiles`, `GET /api/v1/agents/definitions`, `GET /api/v1/tool-policies`: все должны возвращать 200 и валидный JSON. При 500 сохранить method/path/status, correlation/request id, redacted traceback и SQL exception (без чувствительных данных).
3. Создать **один** тестовый Project и Workspace через первый-run wizard, reload, снова выбрать сохранённый Project без дубля.
4. Создать synthetic OpenRouter connection с **только фиктивным** ключом; проверить 201, повторный GET с записью и без auth_config, исправный статус UI; создать ModelProfile и независимо проверить server persistence. Не вызывать completions или «проверку подключения» с платным provider.
5. Смоделировать отказ GET model/agent reference и убедиться: успешный POST провайдера не объявляется неудачей; отказ каталога не закрывает Project.
6. Выполнить проектный real-HTTP/browser test на CI exact HEAD и после Compose restart. Для существующей установки использовать проверенную копию БД и dry-run schema audit.
7. При успешном базовом gate только тогда переходить к созданию/публикации графа, запуску, native worker, QA, Contract Gate и human approval.

## Stop/Go

**NO-GO**, если любой базовый GET/POST возвращает 500, браузер показывает неверный результат сохранения, persist теряется после restart, или есть неподтверждённые конфликты миграции. При подтверждённом P0 сначала исправить причину (backend schema/config/DB или API), добавить regression test на копии старого состояния, а не маскировать ошибку в UI. Сохранять секреты/ключи только в защищённом окружении. Зелёный PR и даже Compose acceptance на disposable instance не означают, что пользовательская локальная инсталляция исправлена.

Источники: `apps/frontend/src/mvp/sections/{ProjectSetupWizard,SettingsPage}.tsx`, `services/{orchestration-server,agent-management}/.../{api,db}.py`, `orchestration_server/migrations.py`, `deploy/compose/dev/docker-compose.yml`, `.github/workflows/quality-gate.yml`, `apps/frontend/e2e/compose-acceptance.spec.ts`, GitHub Issues #8, #11, #44, #209, #253, #254, #256.
