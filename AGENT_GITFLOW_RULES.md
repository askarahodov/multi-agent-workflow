---
# Machine-readable policy. This YAML front-matter is the programmatic source of
# truth consumed by the GitFlow hooks (scripts/git/gitflow-hooks/), the
# dispatcher injection (scripts/git/gitflow_context.py) and the CI job
# .github/workflows/gitflow-policy.yml. It MUST stay in sync with
# gitflow-policy.schema.json (exact semver, including the patch component) — the
# CI job fails on drift.
version: "1.2.0"
status: MANDATORY
schema: gitflow-policy.schema.json
rules:
  - id: GF-01
    description: "One Kanban task = one branch = one objective."
    enforcement: review
  - id: GF-02
    description: "Branch names must carry the task ID (wt/t_XXXXXX)."
    enforcement: hook
  - id: GF-03
    description: "An agent task branch lives at most 48 hours; rebase on main past 24 hours."
    enforcement: review
  - id: GF-04
    description: "Every commit follows <type>(<scope>): <summary>."
    enforcement: hook
  - id: GF-05
    description: "Never push directly to main or develop."
    enforcement: branch-protection
  - id: GF-06
    description: "Verify and remove merged task refs and clean worktrees in the same completion; unresolved safety or access blockers prevent closure."
    enforcement: hook
  - id: GF-07
    description: "Never discard unique work; squash or superseded tips require exact evidence, verified archival and a recorded decision before deletion."
    enforcement: review
  - id: GF-08
    description: "An abandoned branch must be triaged within 7 days."
    enforcement: manual
  - id: GF-09
    description: "The merge gate is required CI on the current candidate plus independent review; an authenticated automated review evidence pilot is limited to approved non-normative documentation; equivalent CI may substitute for local checks between integration checkpoints."
    enforcement: ci
  - id: GF-10
    description: "Verify remote deletion after accepted merge; audit all refs and retain protected, service, dependent or unproven work."
    enforcement: hook
branch_taxonomy:
  agent_pattern: "^wt/t_[a-f0-9]{8}$"
  human_prefixes:
    - feat/
    - fix/
    - docs/
    - chore/
    - refactor/
    - perf/
    - test/
    - security/
    - release/v
    - hotfix/v
  forbidden_patterns:
    - "^(tmp|work|new|backup|dev2)$"
    - "^(master|main|develop)(-.*|2|old)?$"
    - "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
commit_format:
  pattern: '^(feat|fix|docs|chore|refactor|perf|test|security|build|ci|revert)(\([^)]+\)): [a-z].{1,71}$'
  types: [feat, fix, docs, chore, refactor, perf, test, security, build, ci, revert]
  max_subject_length: 72
merge_policy:
  agent_branches: squash
  release_branches: merge-commit
  protected_branches: [main, master, develop, "release/*", "hotfix/*"]
lifecycle:
  review_rebase_hours: 24
  hard_max_hours: 48
  abandonment_days: 7
  cleanup_immediate: true
---

# AGENT GITFLOW RULES

**Version:** 1.2.0
**Status:** MANDATORY — binding for every AI agent profile and every human contributor
**Applies to:** all agents (`orchestrator`, `sdlc-architect`, `sdlc-planner`, `sdlc-developer`,
`sdlc-tester`, `sdlc-reviewer`, `sdlc-security`, `sdlc-fixer`, `sdlc-release`) and humans working in
`/mnt/data/multi-agent-workflow/` (remote: `github.com/askarahodov/multi-agent-workflow`).

This file is the **operational rulebook**. `gitflow-strategy.md` (root) explains *why* the model looks
the way it does; `ADR-010` (§7 worktree isolation, §8 coordination) is the architectural source. When
the three disagree, this file wins for day-to-day behaviour — and you must open a card to reconcile the
discrepancy instead of picking silently.

Read this document during onboarding. Re-read it before your first merge.

---

## 0. The Ten Rules (read this even if you read nothing else)

| ID | Rule | Enforcement |
|----|------|-------------|
| GF-01 | **One Kanban task = one branch = one objective.** Never bundle unrelated work into one branch. | review |
| GF-02 | **Branch names must carry the task ID** (`wt/t_XXXXXX`). No anonymous, dated, personal or reused branch names. | hook + CI (pending), review |
| GF-03 | **An agent task branch lives at most 48 hours.** Past 24 hours, rebase on `main` before requesting review. | review |
| GF-04 | **Every commit message follows `<type>(<scope>): <summary>`** and names the task or subsystem. No `wip`, no `fix`, no `update`. | hook + CI (pending), review |
| GF-05 | **Never push directly to `main` or `develop`.** All changes land through a reviewed merge. | branch protection (required), review |
| GF-06 | **Очистка принятой ветки и worktree обязательна в рамках того же завершения задачи.** При блокере безопасности или доступа задача не закрывается; см. §4.1. | lifecycle + review |
| GF-07 | **Не терять уникальную работу.** Для squash/superseded refs требуется доказательство переноса, архив и решение; неизвестный результат блокирует удаление. | review + lifecycle |
| GF-08 | **An abandoned branch is not allowed to just sit there.** Triage it within 7 days: merge, rebase-and-continue, or delete-with-recorded-reason. | review |
| GF-09 | **The merge gate is the CI quality gate** (`.github/workflows/quality-gate.yml`) plus a review approval. Эквивалентный CI на актуальном SHA может заменить полный локальный `make check` между контрольными точками (§4.0). | CI + review |
| GF-10 | **Проверять фактическое отсутствие рабочей ветки в origin после принятого merge.** Активные, зависимые, релизные, служебные и непроверенные refs сохранять. | audit + review |

Enforcement is staged: some rules are machine-enforced today (branch protection, the CI quality gate,
`git branch -d` safety), and the commit-format / branch-name / cleanup hooks and the CI `gitflow` job are
implemented under card **t_5ba84eb3** (§6.2 lists the real paths and commands). GF-01/GF-03/GF-07/GF-08
remain enforced by human and reviewer discipline — which is exactly why they are written down here.

---

## 1. Branch taxonomy and naming

**Managed dependency updates (GF-02, CI-only exception):** PRs whose GitHub-authenticated
author is `dependabot[bot]`, whose head and base repositories are the same,
and whose branch matches `dependabot/(uv|npm_and_yarn)/<package-path>` may
use Dependabot-generated multi-segment names. The exception is checked against
GitHub event metadata, not the branch string alone; a human branch with this
prefix fails GF-02. It affects **branch naming only**: GF-04 commit format,
worktree isolation, tests, security checks, required-checks classification and
review/merge requirements remain enforced. This does not grant Dependabot
permission to push to `main` or bypass branch protection.


### 1.1 Agent task branches — the default for agents

**Pattern:** `wt/<task-id>`
**Examples (real, from this repository):** `wt/t_16d5878b`, `wt/t_fda39b81`, `wt/t_27411115`, `wt/t_0cba57bd`

Rules:

- **DO** create exactly one branch per Kanban card. The branch is created by the dispatcher with the
  worktree (`hermes kanban create --workspace worktree --branch wt/t_XXXXXX`, workspace
  `.worktrees/<task-id>`).
- **DO** keep the task ID in the name. It is the only link between a branch and its card, its review,
  and its worktree.
- **DO NOT** create a human-style branch (`feat/…`, `fix/…`) unless a human explicitly directed it via
  task metadata (`--branch`). The default agent branch is always `wt/<task-id>`.
- **DO NOT** branch from another task branch. Always branch from `main`.
- **DO NOT** commit to `main`, `develop`, or another agent's branch.
- **DO NOT** reuse a branch name after deletion. A `wt/<task-id>` name belongs to one task, forever.

> Reality check: `gitflow-strategy.md` §2.2 describes the pattern as `<project-slug>/<task-id>` with the
> project slug as the namespace. On this host the dispatcher resolves the slug to `wt`, so the branches
> you see are `wt/t_XXXXXX`. Both describe the same rule — *namespace + task ID, deterministically*.
> Use the pattern you actually observe in `git branch -a`.

### 1.2 Human / explicitly-directed branches

| Prefix | Use | Example |
|--------|-----|---------|
| `feat/<scope>` | New user-facing feature | `feat/editor-node-palette` |
| `fix/<scope>` | Bug fix | `fix/orchestration-db-connection-leak` |
| `docs/<scope>` | Documentation only | `docs/adr-017-api-versioning` |
| `chore/<scope>` | Maintenance, tooling, CI | `chore/drop-vendored-fixtures` |
| `refactor/<scope>` | Restructuring, no behaviour change | `refactor/agent-provider-interface` |
| `perf/<scope>` | Performance work | `perf/runtime-container-startup` |
| `test/<scope>` | Test-only changes | `test/quality-gates-integration-suite` |
| `security/<scope>` | Security hardening | `security/tls-cert-validation` |
| `release/v<X>.<Y>.<Z>` | Release stabilization (release gate only) | `release/v1.2.0` |
| `hotfix/v<X>.<Y>.<Z>` | Emergency production fix | `hotfix/v1.2.1` |

`<scope>` is lower-case, hyphen-separated, and describes the *subject* (`tls-cert-validation`), never a
person or a date.

### 1.3 Forbidden branch names

Reject any branch that:

- has no task ID and no conventional prefix (`tmp`, `work`, `new`, `backup`, `dev2`);
- is a date or a person (`alex-fix`, `2026-10-13`);
- is a near-duplicate of an existing one (`feat/login-fix-2`, `fix/login-final`);
- shadows a protected name (`main2`, `develop-old`).

If you catch yourself typing any of these, you are about to create an orphan. Stop and use `wt/<task-id>`.

---

## 2. Branch lifetime

| Limit | Value | Action when reached |
|-------|-------|---------------------|
| Review-ready rebase | **24 hours** | `git fetch origin && git rebase origin/main` before `kanban_request_review` |
| Hard maximum lifetime | **48 hours** | Delete or escalate (§5). A 3-day-old agent branch is a defect. |
| Abandonment threshold | **7 days with no commits** | Mandatory triage (§5) |
| Merged branch | **0 minutes** | Delete immediately, local + remote (§4) |

Rules:

- **DO** keep task branches short-lived. A branch that outlives its task is a branch nobody owns.
- **DO** rebase on `main` before review — do not merge `main` into your branch to "catch up".
  Keep task-branch history linear so the squash at the gate stays clean.
- **DO NOT** park long-running work on an agent branch "to come back to it". If the work is not
  finishable inside the window, split the card and land what is done.
- **DO NOT** keep a branch alive after its card is `done`, `blocked`, or `archived` without a comment
  explaining why.

Verification:

```bash
# How old is my branch?
git log -1 --format='%cr  %s' wt/t_XXXXXX

# Am I behind main?
git rev-list --count wt/t_XXXXXX..origin/main
```

---

## 3. Commit message format

**Format:** Conventional Commits, one task per commit subject.

```
<type>(<scope>): <summary>

<body — why, not what>

Refs: t_XXXXXX
```

- `<type>` ∈ `feat | fix | docs | chore | refactor | perf | test | security | build | ci | revert`.
- `<scope>` = the task ID, epic ID, or subsystem (`t_0269195`, `e9.6`, `security`, `frontend`).
- `<summary>` — imperative mood, lower-case, no trailing period, ≤ 72 characters.
- Reference related tickets / ADRs / security findings in parentheses at the end of the subject or in
  the body. Cross-reference the card with `Refs:`/`Closes:`.

Real examples from this repository's history — copy this shape:

```
fix(security): authenticate WebSocket /agents/{id}/events (SEC-001)
feat(frontend): MVP v1 UI sections (project, kanban board, conveyor & roles, runs, task card, live agent log)
chore(e9.6): neutralize tools/agent-orchestration (rename package + parametrize paths)
docs(MVP-ROOT t_cfeb50a9): record MVP-shell (src/mvp) as out-of-scope
feat(t_0269195): shared tooling + unified CI/SDLC pipeline (ADR-012/013/016)
docs(t_ff669a29): consolidate Hermes-independence plan (inventory+ADR-001+PLAN v2.0)
```

Rejected messages (these were really used and they cost reviewers time):

```
wip
fix
update stuff
fixes for the thing
final
Merge branch 'x' into y        # on a task branch — rebase instead
```

Rules:

- **DO** commit early and often, but each commit subject must mean something on its own.
- **DO** put the task ID in the scope when there is one — it makes `git log --grep t_XXXXXX` work.
- **DO NOT** push a `wip`/`tmp`/`fixup` commit to a branch that is under review. Squash it
  (`git rebase -i origin/main`) or amend before requesting review.
- **DO NOT** let merge commits accumulate on a task branch — rebase on `main`, never merge `main` in.

---

## 4. Merge and PR requirements

Every change reaches `main` through exactly this path:

1. **Work on your branch** (`wt/<task-id>` or a directed human branch).
2. **Проверки изменяемых компонентов:** выполнить применимые целевые тесты, контрактные, security и migration checks. Если полный локальный `make check` отложен, записать `NOT_RUN` и основание замещения CI; локальный PASS не заявлять. Draft PR разрешён до окончания CI.
3. **Push your branch** and open a PR (`hermes kanban request-review` for Kanban-driven work; a GitHub PR
   for human work).
4. **CI quality gate green:** все обязательные проверки, агрегатор `quality gate` и дополнительные применимые gates на актуальном candidate SHA (либо проверенном PR merge SHA, однозначно связанном с head и base). CI должен покрывать все составляющие `make check`: lint, typecheck, backend pytest для agent-management, orchestration-server, quality-gates, runtime-hardening, tools и packages/agent-runtime, frontend tests/schema validation/build, security scan. Проверять фактические результаты jobs/steps, а не только имя агрегатора.
5. **Review approval:** at least one reviewer approval (`sdlc-reviewer` or a human). После принятия политики допускается независимое автоматизированное evidence review только в узком пилоте §4.2; обязательные approvals GitHub и human gates сохраняются. Changes requested →
   back to step 2, in the *same* branch and worktree.
6. **Merge:** agent task branches and human branches are **squash-merged** so `main` history stays linear;
   release/hotfix branches use a merge commit and an annotated signed tag. `main` requires linear history,
   signed commits, no force-push, no deletion (see `gitflow-strategy.md` §5.1).
7. **Cleanup:** delete the branch, local and remote, and remove the worktree — before you close the card
   (§4.1). This is part of the merge, not a follow-up task.

Rules:

- **DO NOT** push directly to `main` or `develop`. `main` is protected.
- **DO NOT** force-push `main`, `develop`, `release/*`, or `hotfix/*`. Never.
- **DO** force-push only your own agent branch, and only while it is *before* review. Once a reviewer has
  read a commit, do not rewrite it — add a new commit.
- **DO** resolve merge conflicts by rebasing your branch on the target. If the conflict is semantic
  (two implementations of the same contract, an `add/add`), stop and `kanban_block(kind="capability")`
  — the resolution is an architecture decision, not a merge detail.
- **DO NOT** merge anything without successful required gates on the current candidate and independent review. Не подменять локальный результат данными CI.

### 4.0 Замещение локального make check эквивалентным CI (решение владельца, #358)

В период функциональной разработки полный локальный `make check` можно отложить до интеграционной контрольной точки. Это не исключение из обязательных CI или security gates.

- Для каждого PR определить обязательные проверки по изменённым компонентам, контрактам, документации и рискам. Целевые тесты запускаются локально либо в CI; отсутствие результата отмечается явно.
- Допустимые значения локальной проверки: PASS, FAIL, NOT_RUN. FAIL не заменяется зелёным CI без расследования и устранения причины. При NOT_RUN указать причину, ссылку на CI, точный candidate SHA и подтверждение эквивалентного покрытия. Запрещены фиктивные результаты.
- Эквивалентность: все составляющие make check действительно выполнены и успешны, включая frontend schema validation; дополнительные обязательные security, contract, migration, documentation и integration gates не отменяются. Не считать skipped/cancelled/neutral/unknown обязательный тест успешным. Проверка условного шага допустима как N/A только по документированной области изменений и правилам CI.
- Draft можно публиковать с незавершёнными проверками. Перед передачей на окончательное review/merge проверить актуальные head/base и результаты. Новый commit или изменение base требуют актуального evidence согласно CI и правилам защиты веток. Независимое approval обязательно перед merge; прямой push и обход защиты запрещены.
- На контрольной точке интеграции (после объединения связанных подсистем, перед release candidate или при необходимости по риску) выполнить полный локальный make check и согласованные E2E/Compose/стендовые проверки. Дополнительный workflow `Make Check Checkpoint` выполняет буквальную команду `make check` на изолированном CI-хосте при изменении политики/Makefile и по ручному запуску. Фиксировать его результат отдельно как CI_MAKE_CHECK, не как LOCAL_PASS; он не заменяет стендовые проверки и независимое согласование. Если CI не эквивалентен либо нет доступа к необходимой среде — BLOCKED до проверки, не PASS. Реальные LLM-вызовы, production и миграции требуют отдельных разрешений и проверок.
- В handoff фиксировать локальный статус, CI run/check URLs, candidate SHA, недостающие проверки, основания N/A, независимый reviewer и checkpoint для отложенной полной локальной проверки. Не закрывать задачу до фактического DoD.

### 4.1 Обязательная очистка после merge (GF-06, GF-07, GF-10)

Очистка — часть завершения исходной задачи. Не удалять ветку из-за возраста, закрытого PR, исчезнувшего upstream или успешного локального merge.

1. Зафиксировать номер PR, точный принятый head SHA, merge SHA и целевую ветку. Получить актуальные remote refs, проверить достижимость merge SHA из опубликованной цели. Проверить все открытые PR, включая использование исходной ветки как base для stacked PR; при зависимости сначала безопасно перенести зависимую работу.
2. Проверить статус и зарегистрированные worktree на авторитетном рабочем хосте. Сохранить незапушенные коммиты, изменения, игнорируемые пользовательские файлы и доказательства. Не удалять чужую, защищённую, релизную или служебную ветку автоматически.
3. Проверить GitHub auto-delete head branches и точное отсутствие remote ref. Если ветка осталась, оператор сверяет SHA, PR dependencies и protection непосредственно перед удалением. Разрешено только условное удаление с ожидаемым SHA в согласованное окно без параллельной работы. При неизвестном результате сначала повторно прочитать refs, а не повторять запись вслепую.
4. После подтверждения отсутствия remote ref и сохранности работы безопасно убрать чистый зарегистрированный worktree, **затем** локальную ветку штатным guarded lifecycle: атомарно проверить точный SHA ветки и SHA опубликованной цели в Git ref-транзакции, удалить только доказанно достижимый tip. Ручной `git branch -d` допустим только в том же согласованном окне после проверки точного tip и опубликованной цели. Не применять force-флаг, удаление каталога вручную или удаление незнакомых ignored files. Локальный lifecycle не удаляет remote refs без доказательств по PR.
5. Выполнить `git fetch --prune origin` и проверить отсутствие всех трёх объектов: локального ref, удалённого ref и worktree. Ошибка сети, недоступный хост, неразрешённый squash tip или сохранившийся ref означают BLOCKED, не PASS. Remote-tracking prune сам по себе не удаляет удалённую ветку.

Для обычной ветки, tip которой достижим из опубликованной цели, использовать штатный безопасный lifecycle после его принятия и проверки. Любой локальный apply требует явного `--maintenance-window`, остановки всех агентов и внешних Git-писателей и проверки worktree на авторитетном хосте. Штатные create/cleanup, bulk apply и spawn-agent используют общую неблокирующую flock-блокировку в git-common-dir. При конфликте — BLOCKED. Lock не блокирует сторонний Git и не доказывает остановку агентов; флаг — операторское подтверждение. Post-merge и cron только диагностируют, не удаляют; pending cleanup остаётся блокером завершения задачи. Для squash merge исходный tip может не быть предком main; тогда отказ `git branch -d` ожидаем. Сохранить точную историю в проверяемом долговременном Git bundle (проверка списка refs/SHA и `git bundle verify`), зафиксировать точный PR merge receipt или доказательство переноса изменений и отдельное операторское решение. Только после проверки отсутствия worktree и других зависимостей допускается согласованная условная операция удаления локального ref с ожидаемым SHA. **Никакого автоматического `git branch -D`**, даже если upstream gone. Reflog и ссылка на закрытый PR не считаются архивом.

Проверки из авторитетного клона (пример рабочей ветки; выполнять команды отдельно и проверять exit codes):

```bash
branch=wt/t_1234abcd
git fetch --prune origin
git show-ref --verify --quiet "refs/heads/$branch"
git ls-remote --exit-code --heads origin "refs/heads/$branch"
git worktree list --porcelain
```

Для локального ref ожидается код 1 (нет ref; иные ошибки расследовать), для ls-remote код 2 (нет совпадения; сетевой сбой не является доказательством удаления). В успешном выводе worktree list не должно быть записи `branch refs/heads/$branch` или регистрации соответствующего task worktree. Сам каталог worktree также должен отсутствовать. Проверка `git branch --merged` непригодна для подтверждения удаления: squash-merged или незалитая ветка может не попасть в её вывод.

Указать в Issue/card и handoff: исходный/merge SHA, доказательство принятия/переноса, архив (если нужен), результат local/remote/worktree, время проверки и блокеры. Не закрывать задачу до выполнения применимого DoD.

---

### 4.2 Независимое автоматизированное review (пилот)

Проверяемый read-only механизм описан в `docs/governance/automated-review-pilot.md`. Только защищённый main может предоставить доверенный gate; PR не может принять себя новым правилом. Подлинный Codex App, exact head, актуальная base, отсутствие findings/threads/changes requested, обязательный CI и строго разрешённая область являются необходимыми условиями. `EVIDENCE_READY` не создаёт формального GitHub APPROVED и не является разрешением merge. Политика, security, runtime, CI, контракты и production сохраняют обычное независимое approval; не изменять ruleset для обхода. Вступление в силу — после независимого согласования и merge bootstrap PR по прежней политике.

---

## 5. Abandoned, orphaned, and unmerged branches

A branch is **abandoned** when any of these holds:

- its card is `done`/`archived` but the branch was never merged and is not deleted;
- no commit for 7 days and no open card referencing it;
- its work has been superseded by work on `main` or another branch;
- it has no card at all (created manually, never registered).

**Handling is mandatory, not optional.** For each abandoned branch, produce a decision — one of exactly
three — and record it:

| Decision | When | Action |
|----------|------|--------|
| **Merge** | The work is still wanted and merges cleanly | Open/keep the card, run the gate, merge, then clean up (§4.1) |
| **Rebase & continue** | The work is wanted but stale | Rebase on `main`, re-run the gate, keep going in the same branch |
| **Delete** | Superseded, duplicated, or rejected | Record exact SHA, proof of transfer or explicit abandonment, verified archive where history differs, and conditional cleanup per §4.1. |

Procedure:

```bash
# Does it still hold unique work?
git fetch --prune origin
git log --oneline origin/main..wt/t_1234abcd
git merge-base --is-ancestor wt/t_1234abcd origin/main && echo REACHABLE || echo REVIEW_REQUIRED
```

- `REVIEW_REQUIRED` → **сохранить**, пока не доказан перенос или не согласовано архивирование/отказ; использовать существующий Issue/card, не дробить задачу.
- `REACHABLE` → кандидат на безопасную очистку по §4.1 с проверкой PR dependencies, protection и локальной работы; ancestry не является единственным условием.
- Superseded by content on `main` → проверить изменения и тесты, сохранить уникальную историю в проверенном архиве и зафиксировать решение с SHA. Reflog не является гарантией восстановления.

Rules:

- **DO NOT** delete an unmerged branch to "clean up". Losing unique commits is the failure mode this
  whole document exists to prevent.
- **DO NOT** leave the decision implicit. "Probably fine to delete" is not a decision.
- **DO** note every orphan branch in `docs/branch-cleanup/` when you perform a sweep, as the
  `t_245d1a99` sweep did (`BRANCH_MAP.md`, `unmerged-review.md`).

### 5.1 Why this rule is written in blood

The `t_245d1a99` cleanup found **9 fully-merged local branches plus 7 stale worktrees** still on disk,
long after their work had landed — pure accumulation, zero benefit. It also found several branches
holding genuinely unique work that could *not* be deleted (`integration/epic-int-final`,
`epic-int/e9-release`, `wt/t_16d5878b`, `origin/dependabot/...`). Every one of those was a *decision*,
not a chore. Both classes of mess come from the same root cause: nobody deleted the branch at the moment
of merge, and nobody triaged the leftovers.

Do not become the next entry in that file.

---

## 6. Enforcement, tooling, and where the gaps are

### 6.1 What enforces these rules today

| Mechanism | Covers | Status |
|-----------|--------|--------|
| GitHub branch protection on `main` (linear history, signed commits, no force-push, required checks) | GF-05, GF-09 | per `gitflow-strategy.md` §5.1 — verify it is applied to the repository, do not assume |
| CI quality gate `.github/workflows/quality-gate.yml` | GF-09 | present in repo, runs on `push` and `pull_request` |
| `make check` | GF-09 (local / equivalent CI between checkpoints) | present |
| Guarded ref transaction, exact target and tip, worktree check | GF-07 | always on |
| Review checklist (§7) | GF-01, GF-04, GF-06, GF-10 | manual |
| This document | all | manual |

### 6.2 Machine enforcement (delivered)

The GitFlow enforcement system is now implemented. Real, runnable entry points:

| Mechanism | Path | Covers |
|-----------|------|--------|
| Hook library | `scripts/git/gitflow-hooks/gitflow-lib.sh` | shared helpers |
| pre-commit / commit-msg | `scripts/git/gitflow-hooks/{pre-commit,commit-msg}` | GF-02, GF-04, GF-05 (direct commit) |
| pre-push | `scripts/git/gitflow-hooks/pre-push` | GF-02, GF-05 (push + force-push + squash), CI-green |
| post-merge | `scripts/git/gitflow-hooks/post-merge` | GF-06, GF-10 cleanup trigger |
| Commit checker | `scripts/git/gitflow-hooks/check_commits.py` | GF-04 over a `<base>..<head>` range (invoked by the CI job) |
| Hook installer | `scripts/install-gitflow-hooks.sh` | symlinks `.githooks`, sets `core.hooksPath`, `--check` verifies liveness |
| CI job | `.github/workflows/gitflow-policy.yml` | GF-02, GF-04, worktree isolation, required-checks gate |
| Worktree lifecycle | `scripts/git/worktree-lifecycle.py` | GF-06/GF-07 create/validate/cleanup/reap |
| Dispatcher injection | `scripts/git/gitflow_context.py` + `scripts/git/dispatcher-policy-hook.sh` | L2 policy bundle at task claim; `verify` checks hook liveness |
| Policy registry | `AGENT_GITFLOW_RULES.md` (YAML front-matter) + `gitflow-policy.schema.json` | L1 single source of truth |

Install and verify:

```bash
# install the hooks into the current worktree/repo (idempotent)
bash scripts/install-gitflow-hooks.sh

# verify the hooks are LIVE (fails when core.hooksPath points into the void,
# i.e. `.githooks` is absent and git silently runs no hooks at all)
bash scripts/install-gitflow-hooks.sh --check
python3 scripts/git/gitflow_context.py verify            # repo root
python3 scripts/git/gitflow_context.py verify --worktree .worktrees/t_XXXX

# make(1) shortcuts
make gitflow-hooks   # install/refresh hooks for this repo
make gitflow-reap    # list orphaned task worktrees/branches (report-only)

# inject the policy bundle into an existing task worktree
python3 scripts/git/gitflow_context.py claim --task-id t_XXXX --worktree .worktrees/t_XXXX

# validate a worktree before review
python3 scripts/git/worktree-lifecycle.py validate --task t_XXXX

# post-merge cleanup: only after accepting safe lifecycle and verifying remote absence
# Do not run legacy --force-guard; unresolved safety guards mean BLOCKED.
python3 scripts/git/worktree-lifecycle.py cleanup --task t_1234abcd --merge-sha <sha>
```

Bypassing a hook (`git commit/push --no-verify`) is audited: the CI job
`.github/workflows/gitflow-policy.yml` re-checks branch naming and every commit in
the PR range, so a bypass is still caught before merge.

### 6.3 Tooling reality

`gitflow-strategy.md` §8 lists a `cal` CLI (`cal workspace`, `cal hotspot`, `cal kanban`, `cal scheduler`,
`cal migrate`). **On this host `cal` resolves to `/usr/sbin/cal`, the Unix calendar — those subcommands
do not exist.** Use the real tools instead:

| Task | Real command |
|------|--------------|
| Kanban task CRUD / lifecycle | `hermes kanban <verb>` (see `hermes kanban --help`) |
| Create a worktree-backed task | `hermes kanban create --workspace worktree [--branch wt/t_XXXXXX] <title>` |
| Hook/cleanup config for kanban | `hermes kanban gc --help` (prunes events/logs only — it does **not** delete branches or worktrees) |
| Worktree manager | `tools/agent-orchestration/orchestration_tools/agent_workspace.py` |
| Hotspot / collision detection | `python tools/agent-orchestration/scripts/detect-hotspots.py` |
| Secret + dependency scan | `python scripts/security_scan.py` (also `make security`) |
| Local quality gate | `make check` (или подтверждённый эквивалентный CI по §4.0) |

Reconcile the `cal` discrepancy in a card; do not edit `gitflow-strategy.md` from here.

> **CI reference:** for GitHub Actions authentication, workflow inventory, triggering, reading logs/artifacts,
> secrets, and troubleshooting — including the **verified green run IDs** (main CI run 38404508997, main
> Quality Gate 38404508955, test-workflows Quality Gate 38404788426) — see **`docs/ci-guide.md`**.

---

## 7. Reviewer checklist (paste into the review comment)

Before approving a merge, the reviewer confirms:

- [ ] GF-01 One card, one branch, one objective — the diff matches the card body.
- [ ] GF-02 Branch name is `wt/<task-id>` (or a directed human prefix) and matches the card.
- [ ] GF-03 Branch is < 48h old, or rebased on `main` and the age is explained.
- [ ] GF-04 Every commit subject is Conventional Commits with a task/subsystem scope; no `wip`/`fix`/`update`; no leftover merge commits on the task branch.
- [ ] GF-05 No commits directly on `main`/`develop`; no force-push of a shared branch.
- [ ] GF-09 CI quality gate green (all required checks + aggregator), exact candidate SHA; local make check PASS or documented NOT_RUN with equivalent coverage per §4.0; no unresolved failures. Independent evidence, not author self-report.
- [ ] No semantic conflict was resolved by "taking the bigger side"; `add/add` decisions are recorded.
- [ ] GF-06/GF-07/GF-10 The **merge-and-delete plan is explicit**: exact SHA/receipt, PR dependencies, archive if required, remote absence, clean worktree then local ref, fresh verification per §4.1.
- [ ] No uncommitted work is left behind in any worktree that the task touched.

An approval that ignores the cleanup rows is not an approval.

---

## 8. Per-task quick reference

```bash
# --- start (dispatcher does this; verify it) ---
git branch --show-current            # expect wt/t_XXXXXX
pwd                                  # expect <repo>/.worktrees/t_XXXXXX

# --- work ---
git add -A && git commit -m "feat(t_XXXXXX): <imperative summary>"
git fetch origin && git rebase origin/main     # if >24h or before review

# --- gate ---
make check                           # full local checkpoint; otherwise documented NOT_RUN + equivalent CI per §4.0

# --- review ---
hermes kanban request-review t_XXXXXX --summary "..."   # CLI form; the tool form is kanban_request_review(task_id=..., summary=...)

# --- after accepted merge: follow §4.1, not a blind deletion command ---
# Verify exact merge receipt, open PR dependencies, archive if needed,
# remote ref absence, and safe worktree removal before local branch deletion.
git fetch --prune origin
branch=wt/t_1234abcd
git show-ref --verify --quiet "refs/heads/$branch"
git ls-remote --exit-code --heads origin "refs/heads/$branch"
git worktree list --porcelain
```

Expected exit codes and worktree checks are defined in §4.1. A silent network failure is not cleanup evidence.

---

## 9. Exceptions and escalation

| Situation | Do this |
|-----------|---------|
| Agent needs a file owned by another active task | `kanban_block(kind="dependency")`; let the orchestrator sequence or decompose. Never edit another worktree. |
| Merge conflict at the gate | Rebase; if semantic, `kanban_block(kind="capability")` and name the conflicting files and the deciding role. |
| A branch must outlive 48h | Record why in a card comment, rebase on `main`, and get the orchestrator to acknowledge. Silence is not an exception. |
| A remote branch cannot be deleted (permissions) | Record the branch name, last SHA, and the blocker in the card; escalate to the orchestrator/release owner. Do not leave it undocumented. |
| `develop` needed for a release train | Human/release-manager decision only. Agents never create `develop`. |
| Hotfix on a tagged release | `hotfix/vX.Y.Z` from the tag, expedited gate, merge commit + signed tag, then delete the branch. |

---

## 10. Definition of done for a gitflow-clean task

A task is not done until **all** of the following hold:

- [ ] Its branch is merged (or explicitly and justifiably not merged, with a decision recorded).
- [ ] The local branch is deleted.
- [ ] The remote branch is deleted.
- [ ] The worktree is removed and pruned.
- [ ] Exact local ref and remote ref absence verified with exit codes per §4.1, not a merged-branch grep.
- [ ] Successful worktree inventory and filesystem verification prove absence of the task worktree.
- [ ] Squash/superseded history preserved and archive/decision recorded where applicable; no unresolved cleanup blockers.
- [ ] No uncommitted changes remain in any worktree the task created.
- [ ] The card's completion metadata names the merge commit SHA and states the cleanup result.

---

## 11. Version history

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-10-13 | `sdlc-planner` (task `t_27411115`) | Initial enforceable rules: naming, lifetime, commit format, merge/PR gate, mandatory post-merge cleanup (local+remote+worktree), abandoned-branch triage, enforcement status, reviewer checklist. |
| 1.1.0 | 2026-11-26 | Governance PR #359 | Эквивалентный CI между контрольными точками; уточнение GF-06/GF-07/GF-10, точная проверка refs, архивирование squash history и безопасная очистка. |
| 1.2.0 | 2026-11-26 | Governance PR #350 | Ограниченный пилот проверяемого независимого автоматизированного review; без bypass, автоматического APPROVED или merge. |
