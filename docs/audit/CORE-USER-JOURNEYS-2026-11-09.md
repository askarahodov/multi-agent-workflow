# Аудит основных пользовательских сценариев — 2026-11-09

> **Оценка готовности: NO-GO для автономного живого SDLC с платным провайдером.**
> Этот документ основан на актуальном `main@1aa202dd`, открытых Issues/PR,
> реализации API/UI и доступных CI-свидетельствах. Это **не** полный
> эксплуатационный аудит и не утверждение, что Compose/браузер на машине
> пользователя были запущены в ходе этой проверки.

## 1. Первый блокер: подключение OpenRouter → профиль модели

**Подтверждённый дефект UI.** В `SettingsPage.tsx` сохранение провайдера
сначала выполняло `POST /api/v1/providers`, затем вызывало `load()`,
который через `Promise.all` одновременно обращался к `/providers`,
`/model-profiles`, `/agents/definitions`. Даже после **успешного 201**
сбой любого GET переключал экран в общий catch «сохранить не удалось».
Пользователь не получал достоверного подтверждения, мог повторить создание
и встретить конфликт имени. При начальном открытии сбой одного из трёх
GET также скрывал успешные результаты остальных. **Аналогичная ошибка**
была после `POST /model-profiles`.

**Исправление в PR #304:** результат успешного POST немедленно отражается
в состоянии; соседние списки загружаются независимо; 409/422/401/403/5xx
и network failure показываются отдельно, без вывода ответа с возможными
секретами. Добавлены Vitest-регрессии на 201 + независимые 503, 409 и
создание провайдера/модели. Расширена Compose Playwright-проверка
восстановления провайдера и модели после reload. Это **не доказывает**,
что конкретная ошибка пользовательского экземпляра была ровно этой:
для неё нужен реальный HTTP response и лог контейнера.

**Граница безопасности:** синтетический тестовый API key не должен
инициировать completion, платные запросы требуют отдельного подтверждения;
секреты не должны попадать в логи, browser storage или текст ошибок.

## 2. Путь MVP: обязательные quality gates

| № | Сценарий | Подтверждено | Осталось / stop condition | Tracking |
|---|---|---|---|---|
| A1 | Создать OpenRouter и модель | Существуют backend POST, хранение encrypted auth_config, API persistence tests; PR #304 исправляет ложный UI failure | Chromium + реальный Compose POST/GET/reload на чистой БД и с настоящей конфигурацией шифрования, отрицательные 409/503; **без платных вызовов** | #254 |
| A2 | Создать независимые профили developer/tester/reviewer/security | Backend AgentDefinition + модели + ToolPolicy; активный PR #301 расширяет policy/версионирование | Единый UI для создания/назначения профилей; роль/permissions/budget native worker должны применяться в реальном dispatch, не только в API | #254, PR #301 |
| A3 | Сохранить и опубликовать граф редактора | `EditorWorkspace.tsx` имеет save/publish/preflight/launch; опубликованная версия отделена от черновика | Реальный Chromium для графа Start→Agent→Gate→End и отрицательные 409/invalid graph/disabled refs; успешная публикация не означает выполненный run | #253 |
| A4 | Запустить опубликованный граф | `RunsSection.tsx` вызывает server preflight и published run API | Проверить точное соответствие task graph/версии; availability worker, credentials, бюджет и платность *не* подтверждаются одним preflight | #256, #11 |
| A5 | Реальный native worker + инструменты | Имеются native worker, gateway, offline E2E; PR #301 добавляет операторский pinned snapshot | Живой trusted resolver/revocation, глобальные бюджет/concurrency, независимое QA, Compose с реальным агентом; запрещено выдавать offline mock за живую автономность | #254, #11 |
| A6 | Contract Gate, независимые проверки и release | Серверные QA/Contract Gate и protected release approval представлены в API | Сквозной negative browser+HTTP: агент не может self-approve; rejected/missing Git evidence не становится выполненным; release boundary подтверждает человек | #11, #8, #256 |
| A7 | SSE/WS журнал, reconnect/revocation | В API есть opt-in short-lived stream tickets, UI reconnect/fallback | Security-approved rollout, текущая RBAC/replay/expiry/restart проверка в браузере, прокси URL redaction | #209, #256 |
| A8 | Recovery, restart, durable history | Представлены карантин/reconciliation и server persistence | Реальный Compose restart, incomplete side effects и запрет replay без operator attestation | #8, #256 |
| A9 | Защищённый merge/release | Active main ruleset с required CI checks | `required_approving_review_count=0`: обязательное независимое APPROVED **не enforced**. Нужна owner/admin настройка и проверка PR path | #44 |
| A10 | Уязвимости документации | PR #302: миграция Mermaid/Vite, docs build и root npm audit показали 0 high/critical | Отдельный independent security/UI review, реальная визуальная проверка диаграмм; PR #302 остаётся draft | #208 |

## 3. Условия «сценарий завершён»

Для каждого пути A1–A8 недостаточно React unit test или green backend pytest.
**Done** означает: (1) чистая установка/Compose и health; (2) реальный
Chromium UI → HTTP/API → БД → reload/restart; (3) негативные API/RBAC/QA
проверки; (4) отсутствие утечек ключей; (5) реальные worker/модель
отмечены как недоступные, если не настроены; (6) тесты и требуемые CI
checks на точном SHA; (7) независимое review и зафиксированные evidence.

Изменения `main`, production credentials/бюджеты и live provider testing
не проводятся автоматически при таком аудите. Не следует закрывать #11,
#8, #253, #254 и #256 только по обновлённому UI, зелёному CI или review
комментариям. Настоящий production release требует отдельного Go/No-Go.

## 4. Приоритет выполнения без дробления

1. **P1 setup journey:** довести создание OpenRouter → модель → профиль до
   реального browser/HTTP/restart acceptance, исправлять в одном интегрированном
   изменении и не путать 201 с ошибкой последующего GET.
2. **P0 dispatch correctness:** полноценные профиль, политика, права,
   worker eligibility, бюджет и версия при нативном запуске (#254/#11).
3. **P0 workflow correctness:** опубликованная схема → реальные задачи
   → evidence/Contract Gate/QA → решение о релизе (#253/#256/#11).
4. **P1 operations/security:** stream tickets, reset/restart/recovery,
   независимая review protection (#209/#8/#44).

Приоритет не равен разрешению объединить несвязанные security changes в
один непроверяемый diff. Группа задач считается завершённой только по
сквозному пользовательскому результату и предъявленным evidence.
