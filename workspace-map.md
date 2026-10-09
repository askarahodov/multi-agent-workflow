# Workspace Structure Map: /mnt/data/multi-agent-workflow

**Обновлено:** 2026-10-09 (задача `t_7f363f69`, профиль `orchestrator`)
**Статус:** канонический каталог проекта — заполнен и консолидирован.

> Первоначальная версия этого файла (автор sdlc-researcher, задача `t_d5e2665c`)
> описывала каталог как пустой. С тех пор подсистемы импортированы, а правило
> «все наработки — только здесь» закреплено в `docs/PROJECT_DIRECTORY.md`.

## Верхнеуровневое содержимое

| Путь | Назначение |
|------|-----------|
| `orchestration-server/` | Сервер оркестрации: durable execution, lifecycle, REST API |
| `agent-management/` | CRUD агентов, LLM-провайдеры, tool-policy |
| `runtime-hardening/` | Hardened-рантайм: cgroups v2, container runtime, circuit breaker, health/metrics |
| `quality-gates/` | Гейты качества: tester/reviewer/security/release-prep, pipeline, evidence |
| `frontend/` | Редактор workflow (React Flow + Vite + Playwright e2e) |
| `tools/agent-orchestration/` | spawn-agent.sh, worktree-менеджер, detect-hotspots.py |
| `docs/` | ADR, research, plans, reviews, audit, runtime-hardening, PROJECT_DIRECTORY.md |
| `README.md`, `SYSTEM_INFO_RU.md`, `workspace-map.md` | Навигация и системная информация для агентов |
| `.git/` | Репозиторий (remote: github.com/askarahodov/multi-agent-workflow) |

## Проверка (evidence)

```bash
$ ls /mnt/data/multi-agent-workflow/
agent-management  docs   frontend  orchestration-server  quality-gates
README.md  SYSTEM_INFO_RU.md  runtime-hardening  tools  workspace-map.md
```

## Правила для агентов

См. `docs/PROJECT_DIRECTORY.md`. Кратко: любые наработки создавать только
внутри `/mnt/data/multi-agent-workflow/`; scratch-воркспейсы временны и
подлежат переносу сюда до завершения задачи.
