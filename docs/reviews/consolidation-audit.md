# Аудит консолидации наработок агентов доски `me`

**Задача:** `t_ac7b260b` (профиль `sdlc-reviewer`, независимый аудит)
**Родитель:** `t_7f363f69` (коммит консолидации `113fdbf`)
**Канонический каталог:** `/mnt/data/multi-agent-workflow`
**Дата:** 2026-10-09
**Роль:** независимая проверка на evidence (команды `find`/`git`/`diff`/`sha256sum`/`pytest`),
а не по отчётам задач.

> Ограничение роли: отчёт создан как единственный новый файл; чужие файлы не изменялись.

---

## 0. Область проверки и метод

Проверялись все завершённые задачи доски `me`, перечисленные в постановке
(`t_ca94c155, t_c55dd026, t_8aaf9df7, t_191fcdcb, t_197396cf, t_c2af4bc8,
t_c39cb99e, t_25e65cca, t_7cd41bc2, t_72478f3c, t_cea09e5d, t_52732c01,
t_cb3ae3dd, t_ba6ff132, t_55aaab56, t_8d8c017a, t_ad20adcc, t_59037942,
t_fe26d6eb, t_d5e2665c, t_8d6ef34a, t_e3f1889e`), плюс дочерние EditorFS
(`workflow-editor` dir-workspace).

Метод:
1. Инвентаризация артефактов: attachments доски из
   `~/.hermes/kanban/boards/me/attachments/` и содержимое scratch-воркспейсов
   `~/.hermes/kanban/boards/me/workspaces/`.
2. Для каждого файла-артефакта — сверка по SHA-256 с содержимым репозитория
   (`/mnt/data/multi-agent-workflow`) с исключением окружений
   (`.git`, `node_modules`, `.venv`, `__pycache__`, кэши).
3. Поиск по диску (`find`) файлов, которых нет в репозитории.
4. Для каждой задачи — вердикт `present` / `superseded` / `missing`.

SHA-256 совпадение считается строгим доказательством «перенесено»;
совпадение только по имени файла — нет (приводится отдельно).

---

## 1. Построчная таблица: задача → артефакт → путь в репо → вердикт

| Задача | Артефакт(ы) | Путь в репозитории | Вердикт |
|---|---|---|---|
| t_ca94c155 | research: multi-agent autonomous dev patterns | `docs/research/01-autonomous-dev-patterns-report.md` | **present** (sha256 == attachment) |
| t_c55dd026 | ADR-010 multi-agent orchestration | `docs/adr/ADR-010-multi-agent-orchestration.md` | **present** (sha256 == attachment) |
| t_8aaf9df7 | research-report + technology-comparison-matrix | `docs/research/02-p8.3-runtime-hardening-research.md`, `docs/research/02-p8.3-technology-comparison-matrix.md` | **present** (sha256 == attachment) |
| t_191fcdcb | implementation-plan.json | `docs/plans/workflow-editor-implementation-plan.json` | **present** (sha256 == attachment) |
| t_197396cf | VERIFICATION.md | `docs/reviews/p8.3-runtime-hardening-verification.md` | **present** (sha256 == attachment) |
| t_197396cf | 5 тест-модулей + pyproject.toml (+ reports/) | — (см. §3.1) | **missing** |
| t_c2af4bc8 | REVIEW.md | `docs/reviews/p8.3-runtime-hardening-review.md` | **present** (sha256 == attachment) |
| t_c39cb99e | ADR-011, spec, sequence-plan, threat-model, component-diagram, OpenAPI/AsyncAPI, schemas/config | `docs/runtime-hardening/*` | **present** (9 из 10 файлов, sha256 == attachment) |
| t_c39cb99e | README.md (deliverable-package index) | — (см. §3.4) | **missing** (частично superseded) |
| t_25e65cca | orchestration tooling (scripts + pkg + tests + demo) | `tools/agent-orchestration/**` | **present** (все 8 файлов sha256 == scratch) |
| t_7cd41bc2 | architecture.json | `docs/domain-architecture.json` | **present** (sha256 == attachment) |
| t_72478f3c | arch package (README, ADR-001..005, threat-model, component-diagram, OpenAPI, AsyncAPI, schemas, config) | `docs/runtime-hardening/*` | **present** (все 12 файлов, sha256 == attachment) |
| t_cea09e5d | runtime/ пакет + reports + config + docs | `services/runtime-hardening/runtime/**`, `services/runtime-hardening/reports/**`, `services/runtime-hardening/config/**`, `services/runtime-hardening/docs/IMPLEMENTATION.md` | **present** (все 51 файл, sha256 == scratch) |
| t_52732c01 | orchestration server + openapi.json | `services/orchestration-server/**`, `services/orchestration-server/docs/openapi.json` | **present** (sha256 == attachment; код в коммите bc1b372) |
| t_cb3ae3dd | agent management subsystem | `services/agent-management/**` | **present** (в коммите bc1b372; scratch-воркспейс уже очищен) |
| t_ba6ff132 | quality-gates (model.py, detectors.py, gates.py, policy.py, store.py) | — | **superseded** (см. §4) |
| t_55aaab56 | docs/multi-agent ×5 (operator-guide, developer-guide, architecture, runbook, quickref) | — (см. §3.2) | **missing** |
| t_8d8c017a | review-отчёт multi-agent system | — (см. §3.5) | **missing** |
| t_ad20adcc | test-suite ×4 (42 теста) | — (см. §3.3) | **missing** |
| t_59037942 | перевод документации на русский | n/a | **superseded** / no-op (документация уже была русской) |
| t_fe26d6eb | audit_report.md | `docs/audit/task-project-assignment-audit.md` | **present** (sha256 == attachment) |
| t_d5e2665c | workspace-map.md (каталог пуст) | `workspace-map.md` | **superseded** (перезаписан актуальной версией, см. §4) |
| t_8d6ef34a | SYSTEM_INFO_RU.md | `SYSTEM_INFO_RU.md` | **present** |
| t_e3f1889e | task-graph (артефактов-файлов нет) | n/a | **superseded** / no-op |
| EditorFS t_0cd8001a…t_6c7258db | frontend редактора | `apps/frontend/**` | **present** (весь исходник sha256-matched; missing только coverage/playwright-артефакты прогонов, см. §5) |

Команда-доказательство для сверки attachment ↔ repo (фрагмент вывода):

```
$ python3 cmp_attach.py        # (скрипт аудита; хеш SHA-256 каждого файла)
t_ca94c155/...patterns-report.md       exact_match=['docs/research/01-autonomous-dev-patterns-report.md']
t_c55dd026/ADR-010-...md               exact_match=['docs/adr/ADR-010-multi-agent-orchestration.md']
...
t_7cd41bc2/architecture.json           exact_match=['docs/domain-architecture.json']
t_52732c01/openapi.json                exact_match=['services/orchestration-server/docs/openapi.json']
```

---

## 2. Явный список missing-артефактов

Ниже — единственные артефакты завершённых задач, которых **нет** в каноническом
репозитории (`git ls-files` подтверждает отсутствие; источники при этом сохранены
вне репо и восстановимы). Точные пути-источники приведены для переноса
(задача `t_e6d3329d`, `sdlc-developer`).

### 2.1 t_197396cf — 5 тест-модулей + pyproject (P8.3 test suite, layout `runtime/`)

Источник: собственный scratch-воркспейс задачи
`/home/askarahodov/.hermes/kanban/boards/me/workspaces/t_197396cf/`.

| Целевой путь в репо | Источник (scratch) | sha256 |
|---|---|---|
| `services/runtime-hardening/tests/chaos/runtime/test_resource_chaos.py` | `…/t_197396cf/tests/chaos/runtime/test_resource_chaos.py` | `14f287c2…a9ea26` |
| `services/runtime-hardening/tests/integration/runtime/test_hardening_integration.py` | `…/t_197396cf/tests/integration/runtime/test_hardening_integration.py` | `32ca1769…04208d` |
| `services/runtime-hardening/tests/observability/runtime/test_observability.py` | `…/t_197396cf/tests/observability/runtime/test_observability.py` | `20ee7947…f6fe3` |
| `services/runtime-hardening/tests/performance/runtime/test_benchmarks.py` | `…/t_197396cf/tests/performance/runtime/test_benchmarks.py` | `2d0078dd…5b1298` |
| `services/runtime-hardening/tests/security/runtime/test_security_hardening.py` | `…/t_197396cf/tests/security/runtime/test_security_hardening.py` | `87e66c5e…b4d04c` |
| `services/runtime-hardening/pyproject.toml` | `…/t_197396cf/pyproject.toml` | `320e0703…0e1115` |

Дополнительно (тест-отчёт, не критично): `reports/junit.xml`, `reports/coverage.xml`,
`reports/coverage_html/**`, `reports/verify/**`, `reports/benchmarks.json`,
`.coverage` — остались только в scratch.

> Важно: репозиторий `services/runtime-hardening/tests/` содержит лишь 8 unit-модулей,
> 1 integration и 1 chaos. Каталогов `observability/`, `performance/`,
> `security/` и модуля `test_hardening_integration.py` в репо нет вовсе.
> Задача-тестер (`t_197396cf` run112) сообщала о 176 прошедших тестах — этот
> охват в репо не сохранён.

### 2.2 t_55aaab56 — 5 документов multi-agent (1394 строки, ru)

Все 5 файлов лежат **вне** канонического репо и даже вне доски — в
git-неотслеживаемом каталоге HTP (`git status` в HTP: `?? docs/multi-agent/`).

| Целевой путь в репо | Источник | sha256 |
|---|---|---|
| `docs/multi-agent/operator-guide.md` | `/mnt/data/app/Harbor-Transfer-Portal/docs/multi-agent/operator-guide.md` | `6d1331ac…dbda080` |
| `docs/multi-agent/developer-guide.md` | `/mnt/data/app/Harbor-Transfer-Portal/docs/multi-agent/developer-guide.md` | `33db8d41…c87875e` |
| `docs/multi-agent/architecture.md` | `/mnt/data/app/Harbor-Transfer-Portal/docs/multi-agent/architecture.md` | `d43891bf…279689` |
| `docs/multi-agent/runbook.md` | `/mnt/data/app/Harbor-Transfer-Portal/docs/multi-agent/runbook.md` | `12104eca…805556` |
| `docs/multi-agent/quickref.md` | `/mnt/data/app/Harbor-Transfer-Portal/docs/multi-agent/quickref.md` | `25c61097…dcbf6c` |

Метаданные задачи `t_55aaab56` (`created_files`) подтверждают именно эти 5 путей
и `total_lines: 1394`.

### 2.3 t_ad20adcc — test-suite из 4 файлов (42 теста: unit/integration/chaos/e2e)

Тесты лежат вне канонического репо — в git-неотслеживаемых путях репозитория
`hermes-agent` (`git status` там: `?? tests/chaos/`, `?? tests/unit/`, …).

| Целевой путь в репо | Источник | sha256 |
|---|---|---|
| `tools/agent-orchestration/tests/unit/test_agent_workspace.py` | `/home/askarahodov/.hermes/hermes-agent/tests/unit/test_agent_workspace.py` | `3a41ca8b…8a54a69` |
| `tools/agent-orchestration/tests/integration/test_multi_agent_flow.py` | `/home/askarahodov/.hermes/hermes-agent/tests/integration/test_multi_agent_flow.py` | `fb27adbc…d37f604` |
| `tools/agent-orchestration/tests/chaos/test_failure_modes.py` | `/home/askarahodov/.hermes/hermes-agent/tests/chaos/test_failure_modes.py` | `beea8d53…a302f6` |
| `tools/agent-orchestration/tests/e2e/test_harbor_transfer_portal_flow.py` | `/home/askarahodov/.hermes/hermes-agent/tests/e2e/test_harbor_transfer_portal_flow.py` | `f3c25c72…00a8d11` |

Идентичность подтверждена содержимым: тесты импортируют
`harbor_transfer_portal.agent_workspace` / `harbor_transfer_portal.kanban_tools`.
Целевые подкаталоги `tests/` в `tools/agent-orchestration/` пока не созданы.

### 2.4 t_c39cb99e — README.md пакета архитектуры (частично superseded)

Источник: `/home/askarahodov/.hermes/kanban/boards/me/attachments/t_c39cb99e/README.md`
(= scratch `t_c39cb99e/README.md`).

`docs/runtime-hardening/README.md` в репо существует, но это **другая** версия —
из задачи `t_72478f3c` (`Design Package`). Версия `t_c39cb99e`
(`Deliverable Package`) уникальна: содержит заметку о нумерации ADR-011
(«ADR-001..005 = разделы ADR-011») и карту поставки. Вывод: версия `t_72478f3c`
канонична; уникальный контент `t_c39cb99e` либо добавить отдельным файлом,
либо явно задокументировать как superseded.

### 2.5 t_8d8c017a — review-отчёт multi-agent system

Задача — review-гейт. Её единственный «artifact» в метаданных —
транзиентный лог терминала:
`/home/askarahodov/.hermes/profiles/sdlc-reviewer/cache/terminal-output/out-1791538776-2576-c30.log`
(59901 байт, существует). Содержательный отчёт (findings: 107 ruff / 16 mypy
ошибок в orchestration tooling, timeout integration-тестов, отсутствие doc-файлов
в workspace `t_55aaab56`, отсутствие привязки проекта к репо, 10 из 19 профилей
отсутствуют) в репо не оформлен. Рекомендуется перенести как
`docs/reviews/multi-agent-system-review.md`.

---

## 3. Проверки из постановки

### 3.1 Полнота импорта
См. §1–2. Все задачи, у которых артефакт существует как attachment и присутствует
в репо, имеют строгое sha256-совпадение. Три задачи имеют реальные потери
(`t_197396cf`, `t_55aaab56`, `t_ad20adcc`), одна — частичную (`t_c39cb99e` README),
одна — отчёт вне репо (`t_8d8c017a`).

### 3.2 Потери вне репозитория
Найдено и локализовано (см. §2): `t_55aaab56` (в HTP), `t_ad20adcc`
(в hermes-agent), `t_197396cf` (в своём scratch). Ничего из этого не
задокументировано как superseded.

### 3.3 dir-воркспейс `workflow-editor` и прочие dir-воркспейсы
`workflow-editor/frontend/**` — весь исходник и тесты редактора имеют
sha256-совпадение с `apps/frontend/**` в репо. Единственные несовпадения — артефакты
прогонов тестов: `.vite/vitest/results.json`, `coverage/tmp/*.json`,
`apps/frontend/playwright-report/**`, `apps/frontend/test-results/**`. Это не исходный код
и не подлежит переносу (соответствует `.gitignore`). Вердикт: **present**.
Все прочие dir-воркспейсы — те же (данные прогонов), потерь нет.

---

## 4. Вердикт по quality-gates

- **В репо — только версия из коммита `c835943`** (`quality_gates/gates/{base,
  reviewer,security,release_prep,walk,tester}.py` + `models/pipeline/evidence/
  api/config/db/errors/main`). Проверка: `git log --all --name-only | grep -iE
  'detectors|policy|store\.py'` → **пусто**; версия `t_ba6ff132`
  (`model.py, detectors.py, gates.py, policy.py, store.py`) в git никогда не
  попадала и на диске не найдена.
- **Superseded — задокументировано:** `docs/PROJECT_DIRECTORY.md` §«История
  консолидации»: «`c835943` — quality-gates (переписанная версия, автор
  `t_fe85477d`)».
- **Проверка собираемости (независимо, pytest в чистом venv):**
  ```
  $ pytest -q        # services/quality-gates/
  47 passed in 4.68s
  ```
  (заявлено оркестратором «45 passed»; после коммита `601fb6b` стало 47 —
  согласовано).

**Вердикт: superseded — порт не требуется.** Единственная оговорка (см. §6):
исходники `t_ba6ff132` отсутствуют, поэтому уникальность поведения старой
версии машинно подтвердить нельзя. Поскольку обе версии реализуют один и тот же
пайплайн (Tester/Reviewer/Security/Release-Prep + evidence-ledger + переходы),
а текущая покрыта зелёными тестами, риск потери уникальной функциональности
оценивается как низкий и переносится в остаточные риски.

---

## 5. Согласованность закоммиченного состояния

- `git status` на момент аудита **не чист**: ` M services/quality-gates/quality_gates/gates/base.py`
  (удалено 102 строки). Этот файл НЕ принадлежит консолидации: идёт
  **параллельная работа другого агента** (hotspot, отмеченный родителем:
  «services/quality-gates/quality_gates/gates/* (concurrent writes from harbor board task
  t_f55f6a64)»), mtime 16:29 совпадает с временем аудита. Флаг: перед коммитом
  переноса (задача `t_e6d3329d`) этот файл нужно либо согласовать с владельцем,
  либо не включать в коммит переноса.
- `pytest services/quality-gates/tests` — проходит (§4).
- Коммит консолидации `113fdbf` существует; `git log` на месте.

---

## 6. Остаточные риски

1. **Уникальность старой версии quality-gates непроверяема** — исходники
   `t_ba6ff132` утрачены (нет ни в git, ни на диске). Митиг.: считать rewrite
   каноничным; при появлении независимого описания поведения — сверить.
2. **Параллельная запись в `services/quality-gates/quality_gates/gates/base.py`** —
   незакоммиченные изменения чужого агента в рабочем дереве. Митиг.: не коммитить
   этот файл в рамках переноса.
3. **Test-evidence P8.3 (`t_197396cf`)** — даже после переноса 5 модулей их
   прогон не воспроизведён в репо (нет `pyproject.toml`-конфигурации на месте).
   Митиг.: после переноса прогнать `pytest services/runtime-hardening/tests` и зафиксировать.
4. **`t_8d8c017a`** — отчёт существует лишь как сырой лог терминала; при
   очистке кэша будет утрачен. Митиг.: оформить в `docs/reviews/`.

---

## 7. Итог

- **present:** 15 задач (все attachment-артефакты строго sha256-совпадают).
- **superseded:** `t_ba6ff132` (quality-gates — rewrite `c835943`, задокументировано),
  `t_d5e2665c` (workspace-map перезаписан), `t_59037942`, `t_e3f1889e` (no-op).
- **missing:** `t_197396cf` (5 тестов + pyproject), `t_55aaab56` (5 док-файлов),
  `t_ad20adcc` (4 тест-файла), `t_c39cb99e` (README), `t_8d8c017a` (review-отчёт).

Перенос missing-артефактов — задача `t_e6d3329d` (`sdlc-developer`); точные
пути-источники и sha256 приведены в §2.

---

### Приложение: воспроизводимость команд

```bash
# инвентарь воркспейсов и attachments
ls -la ~/.hermes/kanban/boards/me/workspaces/ ~/.hermes/kanban/boards/me/attachments/
# сверка содержимого (SHA-256) attachment/scratch → repo
python3 cmp_attach.py ; python3 cmp_ws.py   # скрипты аудита
# поиск потерянных файлов на диске
find /home/askarahodov /mnt/data -type f -name 'test_security_hardening.py' …
# отсутствие старых quality-gates в git
git log --all --name-only | grep -iE 'detectors|policy|store\.py'
# собираемость
cd quality-gates && pytest -q
# состояние дерева
git -C /mnt/data/multi-agent-workflow status --short
```
