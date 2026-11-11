# Первый запуск Multi-Agent Workflow (локально)

Эта инструкция описывает **фактический dev Compose** проекта, а не защищённый production deployment и не готовый платный агентный конвейер. Запуск контейнеров позволяет проверить UI, REST API, сохранение проекта, опубликованного workflow и задач. Native worker с OpenRouter/доверенным Git gateway подключается **отдельно и только по явному решению оператора**.

## Требования

- Git и Docker Engine / Docker Desktop с Compose plugin.
- Свободные порты по умолчанию: `5173` (UI), `18000` (orchestration), `8001` (agent-management), `8002`, `8003`, `5432`. Их можно переопределить в `.env`.
- Для запуска контейнеров **не требуются** локальные Node.js, Python, OpenRouter key или Hermes. Для тестов за пределами контейнеров нужны соответствующие локальные инструменты.

## 1. Скачать проект и подготовить конфигурацию

```sh
git clone https://github.com/askarahodov/multi-agent-workflow.git
cd multi-agent-workflow
```

Скопируйте `.env.example` в `.env` только если нужны переопределение портов или постоянное хранение провайдерских credentials. Файл `.env` исключён из Git. Перед вводом **реальных** API-ключей обязательно задайте стабильный `AUTH_ENCRYPTION_KEY` — base64 от 32 криптографически случайных байт:

```sh
docker run --rm python:3.12-slim python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

Вставьте выведенное значение в свой `.env`, не публикуя его. Не меняйте ключ без процедуры миграции: иначе уже сохранённые зашифрованные данные могут стать нечитаемыми. **OpenRouter ключ для бесплатного offline smoke не нужен.**

### Если ранее запускали Compose на этом checkout

**Перед обновлением ветки** сохраните
`services/orchestration-server/orchestration.db`: этот файл раньше ошибочно
отслеживался в Git (#311), а сейчас исключён. Если просто переключить ветку,
Git может удалить прежнюю копию. Обязательно выполните
[безопасную миграцию с SQLite backup](../qa/LOCAL-MANUAL-ACCEPTANCE.md#обязательная-резервная-копия-при-переходе-со-старого-git-tracked-sqlite-311)
**до `git pull`/`git switch`**. Сама SQLite после безопасного восстановления
остаётся на bind mount; никаких автоматических удалений данных нет.

## Исходящий прокси для API и моделей

При необходимости скопируйте `.env.example` в локальный `.env` и укажите **только там**:

```dotenv
MAW_OUTBOUND_PROXY_URL=http://USER:URL_ENCODED_PASSWORD@PROXY_HOST:PORT
```

Корневой `.dockerignore` тоже исключает `.env`, SQLite и приватные файлы из контекста сборки; это отдельная защита от случайного `COPY` при создании Docker-образов.

Не добавляйте действующий пароль в Git, скриншоты, issue и вывод `docker compose config`:
**этот вывод содержит раскрытое значение переменной**. В Linux ограничьте доступ
к файлу: `chmod 600 .env`. Для смены прокси отредактируйте одну строку в
`.env`, затем пересоздайте Python-контейнеры:
`docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --force-recreate`.

Используются стандартные переменные в обоих регистрах (`HTTP_PROXY`/`http_proxy`, `HTTPS_PROXY`/`https_proxy`, `ALL_PROXY`/`all_proxy`) внутри
Python-сервисов; `httpx`-адаптеры OpenRouter/HuggingFace их учитывают.
`MAW_OUTBOUND_NO_PROXY` исключает `127.0.0.1`, `localhost` и имена
Docker-сервисов. Внешние модельные запросы идут через прокси, а локальные
healthchecks, Vite proxy и взаимодействие сервисов — напрямую.
Пустой `MAW_OUTBOUND_PROXY_URL` отключает явную прокси-настройку.
Само указание прокси **не** делает платный вызов или диагностику OpenRouter.
Проверить реальную доступность внешнего прокси без сетевого теста нельзя.

В защищённом native-worker overlay эти же переменные передаются worker,
но `trusted-control` остаётся изолированной `internal: true` сетью.
До явной настройки безопасного egress к прокси **не считайте** live OpenRouter
работоспособным — не открывайте неограниченный выход в сеть для обхода gate.

## 2. Запустить стек

Из корня репозитория на Linux/macOS с `make`:

```sh
make up
make ps
```

Универсальная команда Docker Compose, в том числе для **Windows CMD** (PowerShell не нужен):

```text
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up -d --build
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps
```

**Не запускайте** просто `docker compose up -d`: в корне нет `compose.yml` / `docker-compose.yml`. Используйте путь выше или `make up`.

Дождитесь состояния healthy у шести служб: `postgres`, `orchestration-server`, `agent-management`, `runtime-hardening`, `quality-gates`, `frontend`. При первом build понадобится загрузка зависимостей и образов.

## 3. Проверить API и интерфейс

| Назначение | Адрес по умолчанию |
| --- | --- |
| Интерфейс | http://127.0.0.1:5173 |
| Orchestration health | http://127.0.0.1:18000/health |
| Agent Management health | http://127.0.0.1:8001/health |
| Runtime Hardening health | http://127.0.0.1:8002/health |
| Quality Gates health | http://127.0.0.1:8003/health |

Если меняли host ports в `.env`, используйте новые адреса. Сервисные порты внутри Docker менять не нужно.

В интерфейсе пройдите единый сценарий: **Первый запуск / Проект → Настройки провайдера и модели → Профили агентов → Редактор → Проверка графа → Сохранение черновика → Публикация версии → Запуски → Карточка задачи / Журнал**.

- Для offline smoke используйте фиктивного провайдера, не вызывая `/completions` и не нажимая платную проверку подключения.
- Поддерживается линейная публикуемая схема `Start → (Agent → automatic Gate)+ → End`. Неисполняемые типы узлов и ветвления должны блокироваться при publish/run, а не молча пропускаться.
- Сам факт создания `run` **не означает**, что native worker запущен. Появление записей QA или Git evidence не заменяет проверку реального исполнения.
- Завершённый workflow не предоставляет автоматическое разрешение на merge/deploy. Независимая QA и операторское release approval проверяются отдельно.

Подробности настройки: [создание проекта](project-setup.md), [публикация и запуск версии](published-workflow-run.md), [профили агентов](agent-profiles.md).

## 4. Проверить сохранение данных после restart

Из корня репозитория при установленном Python и работающем Compose:

```sh
python3 scripts/local_mvp_api_smoke.py create --state-file smoke.json
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml restart orchestration-server
python3 scripts/local_mvp_api_smoke.py verify --state-file smoke.json
```

В Windows CMD замените `python3` на `python`. Проверку повторяйте только после восстановления health. `smoke.json` содержит тестовые идентификаторы: храните его локально, не добавляйте в коммит. **Не используйте `docker compose down -v`** на стеке с нужными данными — флаг удаляет volumes.

Для автоматической браузерной приёмки на локально поднятом Compose:

```sh
cd apps/frontend
npm ci
npx playwright install chromium
npx playwright test --config compose.playwright.config.ts
```

Playwright здесь обращается к реально работающему Vite/HTTP, а не к подменённому mock API. Дополнительные backend/CI проверки описаны в [локальном сценарии приёмки](../qa/LOCAL-MANUAL-ACCEPTANCE.md).

## 5. Ограничения безопасности и настоящая AI-проверка

**Этот Compose предназначен только для доверенной локальной машины.** В нём выключена API-аутентификация (`AUTH_ENABLED=false`), а `runtime-hardening` имеет `privileged: true` и доступ к Docker socket. Не публикуйте порты наружу и не используйте его как production deployment.

Реальный OpenRouter/native worker **не** стартует автоматически вместе с dev Compose. Для защищённого запуска нужны отдельные TLS, private key files, ограничение расходов у провайдера, рабочий Git gateway, независимые tester/reviewer/security и действие оператора. Действуйте по [native worker runbook](../NATIVE_WORKER_ACCEPTANCE_RU.md) и [live read-only acceptance](../qa/LIVE-NATIVE-SDLC-READ-ONLY-ACCEPTANCE.md). Зелёные контейнеры и offline CI **не доказывают** выполнение платного автономного SDLC.

## Диагностика и остановка

Из корня проекта:

```text
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml logs --tail=100
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml ps
docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml down
```

Если UI пуст, проверьте Vite proxy и `ORCH_UPSTREAM` / `AGENT_MGMT_UPSTREAM`. Если provider credentials не читаются после restart, проверьте **постоянство** `AUTH_ENCRYPTION_KEY`, не выводя его в лог. Если задача остаётся pending, проверьте факт подключения native worker, а не пытайтесь подменить server-owned claim из браузера.

Зафиксированные условия полноценной локальной приёмки: [Issue #8](https://github.com/askarahodov/multi-agent-workflow/issues/8) и [Issue #11](https://github.com/askarahodov/multi-agent-workflow/issues/11).
