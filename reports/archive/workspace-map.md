# Workspace Structure Map: /mnt/data/multi-agent-workflow

**Обновлено:** 2026-10-12 (задача `t_82b08777`, EPIC-INT E9.3).
**Ветка:** `epic-int/e9-release`.
**Статус:** канонический каталог проекта — заполнен и консолидирован.

> Первоначальная версия этого файла (автор sdlc-researcher, задача `t_d5e2665c`)
> описывала каталог как пустой. С тех пор подсистемы импортированы, добавлены
> воспроизводимый локальный запуск и CI quality gate, а правило «все наработки —
> только здесь» закреплено в `docs/PROJECT_DIRECTORY.md`.

## Верхнеуровневое содержимое

| Путь | Назначение |
|------|-----------|
| `orchestration-server/` | Сервер оркестрации: durable execution, lifecycle, REST API (порт 8000) |
| `agent-management/` | CRUD агентов, LLM-провайдеры, tool-policy (порт 8001) |
| `runtime-hardening/` | Hardened-рантайм: cgroups v2, container runtime, circuit breaker, health/metrics (порт 8002) |
| `quality-gates/` | Гейты качества: tester/reviewer/security/release-prep, pipeline, evidence (порт 8003) |
| `frontend/` | Редактор workflow (React Flow + Vite + Playwright e2e, порт 5173) |
| `shared/` | Общий Python-пакет: auth/security middleware для сервисов |
| `tools/` | Инструменты разработки: spawn агентов, worktree-менеджер, детектор hotspots, storage |
| `scripts/` | Служебные скрипты: `security_scan.py` (обёртка quality-gates SecurityGate для `make security`) |
| `docs/` | ADR, research, plans, reviews, audit, integration-audit, runtime-hardening, wiki, PROJECT_DIRECTORY.md |
| `Makefile` | Единая точка входа: `up`/`down`/`logs`/`ps` (E9.1) и `check` (E9.2) |
| `docker-compose.yml` | Локальный стек: postgres + 5 сервисов с healthcheck |
| `.github/workflows/quality-gate.yml` | CI quality gate (job `quality-gate` агрегирует backend/frontend/lint/security) |
| `.dockerignore`, `.gitignore` | Исключения для образов и git |
| `PLAN.md` | План развития платформы |
| `README.md`, `SYSTEM_INFO_RU.md`, `workspace-map.md` | Навигация и системная информация для агентов |
| `.git/` | Репозиторий (remote: github.com/askarahodov/multi-agent-workflow) |

## Проверка (evidence)

```bash
$ git branch --show-current
epic-int/e9-release
$ git log --oneline -1
bd06d89 feat(e9): unified CI quality gate (.github/workflows/quality-gate.yml + make check)
$ ls -1
agent-management  docker-compose.yml  docs  evidence_store  frontend  Makefile
orchestration-server  PLAN.md  quality-gates  README.md  release_artifacts
runtime-hardening  scripts  shared  SYSTEM_INFO_RU.md  tools  workspace-map.md
```

## Запуск и проверка

```bash
make up      # поднять весь стек (docker compose up -d --build)
make ps      # статус сервисов (healthy)
make down    # остановить стек
make check   # полный локальный quality gate (аналог CI)
```

## Правила для агентов

См. `docs/PROJECT_DIRECTORY.md`. Кратко: любые наработки создавать только
внутри `/mnt/data/multi-agent-workflow/`; scratch-воркспейсы временны и
подлежат переносу сюда до завершения задачи.
