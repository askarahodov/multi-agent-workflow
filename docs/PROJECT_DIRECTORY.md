# Canonical Project Directory

**Канонический каталог проекта: `/mnt/data/multi-agent-workflow/`**

Это единственное место, где хранится и разрабатывается весь проект
(платформенная оркестрация, управление агентами, редактор workflow,
runtime hardening, quality-gates, документация).

Дата фиксации правила: 2026-10-09 (kanban-задача `t_7f363f69`, профиль `orchestrator`).

## Правило для ВСЕХ агентов

1. **Любые наработки — только в этот каталог.** Никакие артефакты, код,
   документы, отчёты и результаты тестов не должны оставаться вне
   `/mnt/data/multi-agent-workflow/`.
2. **Задачи этой доски (`me`) выполняются в этом каталоге.**
   При создании задачи-потомка указывать
   `workspace_kind=dir`, `workspace_path=/mnt/data/multi-agent-workflow`
   (или git-worktree внутри репозитория), а не `scratch`.
3. **Если работа уже выполнена где-то ещё** (в scratch-воркспейсе задачи,
   в другом каталоге, на другой доске) — её нужно перенести в этот каталог
   и закоммитить в git. Перенос не считается завершённым, пока файлы
   не оказались в репозитории.
4. **Структура каталогов** (неплодотворно создавать новые верхнеуровневые
   папки без необходимости):

   | Каталог | Назначение |
   |---------|-----------|
   | `orchestration-server/` | Сервер оркестрации (durable execution, REST API) |
   | `agent-management/` | Управление агентами и абстракция LLM-провайдеров |
   | `runtime-hardening/` | Hardened-рантайм (cgroups, circuit breaker, health/metrics) |
   | `quality-gates/` | Гейты качества (tester, reviewer, security, release-prep) |
   | `frontend/` | Визуальный редактор workflow (React Flow + Vite) |
   | `tools/` | Инструменты разработки (spawn агентов, worktree, hotspots) |
   | `docs/` | Документация: `adr/`, `research/`, `plans/`, `reviews/`, `audit/`, `runtime-hardening/`, `wiki/` |

5. **Ветки и коммиты.** Разработка ведётся в git-репозитории этого каталога
   (remote: `github.com/askarahodov/multi-agent-workflow`). Пуш/теги/релиз —
   только через отдельно авторизованный релизный процесс.
6. **Scratch-воркспейсы Hermes временны.** Всё, что должно пережить задачу,
   переносится в этот каталог до завершения задачи.

## История консолидации

Первичный импорт подсистем выполнен коммитами:
- `bc1b372` — orchestration server, agent management, runtime hardening,
  workflow editor frontend, доменная архитектура.
- `fa1da65` — синхронизация runtime-hardening с финальной P8.3.
- `c835943` — quality-gates (переписанная версия, автор t_fe85477d).
- Consolidation-коммит `t_7f363f69` — перенос остаточных документов
  (research, ADR-010, планы, обзоры, аудит, инструменты) в `docs/` и `tools/`.

Аудит назначения задач (`docs/audit/task-project-assignment-audit.md`)
подтвердил: 12 задач были ошибочно привязаны к проекту Multi-Agent Workflow Platform,
хотя относятся к этой мультиагентной системе, и подлежат консолидации здесь.
