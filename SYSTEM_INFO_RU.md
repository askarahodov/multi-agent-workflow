# Системная информация для агентов (на русском языке)

## 1. Путь и структура рабочей директории

- **Канонический путь проекта:** `/mnt/data/multi-agent-workflow/`
  (workspace_kind=`dir`; см. `docs/PROJECT_DIRECTORY.md`).
- **Ветка разработки релиза EPIC-INT:** `epic-int/e9-release`.
- Директория содержит рабочий git-репозиторий
  (remote: `github.com/askarahodov/multi-agent-workflow`) с подсистемами:

  ```
  orchestration-server/   сервер оркестрации (durable execution, REST API)
  agent-management/       управление агентами и LLM-провайдерами
  runtime-hardening/      hardened-рантайм (cgroups v2, circuit breaker)
  quality-gates/          гейты качества (tester/reviewer/security/release)
  frontend/               визуальный редактор workflow (React Flow + Vite)
  shared/                 общий пакет (auth/security middleware)
  tools/                  инструменты разработки (spawn, worktree, hotspots)
  scripts/                служебные скрипты (security_scan.py)
  docs/                   документация (ADR, research, plans, reviews, audit)
  ```

- Корневые точки входа: `Makefile`, `docker-compose.yml`,
  `.github/workflows/quality-gate.yml`, `README.md`, `workspace-map.md`.

## 2. Протокол обмена

Все межагентные сообщения и журналы должны быть на русском языке.

## 3. Ключевые соглашения

- Пути к файлам: используйте абсолютные пути или пути относительно рабочей директории.
- Именование файлов: строчные буквы, дефис как разделитель слов
  (например, `system-info-ru.md`).
- Формат журнала: plain text с меткой времени в ISO 8601
  (например, `2026-10-12T12:00:00Z`).

## 4. Команды запуска и проверки

Запуск стека и прогон гейта качества — из корня репозитория
(фактические цели из `Makefile`, задачи E9.1/E9.2):

```bash
make up      # поднять весь стек (docker compose up -d --build)
make ps      # статус сервисов
make logs    # живые логи
make down    # остановить стек
make check   # полный локальный quality gate (аналог CI)
```

CI-гейт: `.github/workflows/quality-gate.yml` (job `quality-gate`).

## 5. Как находить общие ресурсы и записывать выводы

- **Общие ресурсы:** общий Python-пакет — `shared/`; документация — `docs/`;
  инструменты разработки — `tools/`.
- **Запись выводов:** сохраняйте файлы вывода внутри
  `/mnt/data/multi-agent-workflow/` (или в поддиректориях) и коммитьте в git.
  Не записывайте за пределы рабочей директории без явной необходимости.
- **Scratch-воркспейсы Hermes временны** — всё, что должно пережить задачу,
  переносится в этот каталог до её завершения.

## Примечание

Ранняя версия этого файла (задача `t_d5e2665c`) описывала каталог как пустой
scratch-воркспейс. Это устарело: подсистемы импортированы, репозиторий
инициализирован, действует правило «все наработки — только здесь»
(`docs/PROJECT_DIRECTORY.md`).
