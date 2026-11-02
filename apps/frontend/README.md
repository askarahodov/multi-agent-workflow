# Workflow Editor (frontend)

Visual workflow editor plus the **MVP v1 platform UI** for the AI Multi-Agent
Workflow platform: project management, kanban board, conveyor & roles, workflow
runs & results, the task card and a live agent log.

## Stack

- TypeScript 5 + React 18 + Vite 5
- Canvas: React Flow (`@xyflow/react` v12)
- State: Zustand 4
- Validation: ajv 8 (JSON Schema Draft 2020-12) + a pure graph validator
- Unit tests: Vitest + Testing Library + jsdom
- e2e: Playwright (downstream task T6)
- Lint/format: ESLint 9 + Prettier

## Design system (ADR-110)

The platform UI is built on a single token-driven design system so every section
shares one visual language (no per-section one-off styling).

- **Tokens** — `src/styles/tokens.css` (colour, spacing, radius, typography,
  elevation, motion, z-index, breakpoints) + `src/styles/global.css` (reset,
  visible focus ring, skip link, screen-reader utility). Loaded once in
  `src/main.tsx`.
- **Components** — `src/components/` (CSS Modules + tokens): `Button`,
  `IconButton`, `Field`/`Input`/`Textarea`/`Select`, `Card`, `Badge`/
  `StatusBadge`, `Table`, `Tabs`, `Breadcrumbs`, `Dialog`, `Tooltip`,
  `Skeleton`/`Spinner`, `EmptyState`, `ErrorState`, `ToastProvider`/`useToast`,
  `Stack`/`Grid`. Import from the barrel: `import { Button } from '../components'`.
- **Patterns** — `src/patterns/`: `AppShell` (responsive shell, skip link,
  labelled nav, polite live region, mobile drawer), `PageHeader`, `AsyncBoundary`
  (loading/error/empty/content states).
- **i18n** — `src/i18n/` typed catalog (`ru` default, `en` fallback) with a
  `dir`/`lang` switch on `<html>`; layouts use logical CSS properties so RTL is a
  configuration switch.
- **Core layouts** — `src/pages/`: `ProjectDashboard`, `TaskBoard`,
  `AgentMonitor` (live agent log) and `SettingsPage`. The matching
  `src/mvp/sections/*` files are thin re-exports so existing import paths and
  tests keep working.

Accessibility baseline (WCAG 2.1 AA): every interactive element is
keyboard-operable with a visible focus ring; icon-only buttons require an
`aria-label`; the agent log is an `aria-live="polite"` region; status is conveyed
by text + tone, never colour alone. Behaviour is covered by Vitest component
tests and a Playwright smoke suite (`e2e/design-system.spec.ts`).

## MVP v1 sections

The app shell (`src/App.tsx`) navigates between the existing canvas editor and
the MVP v1 platform sections under `src/mvp/sections/`:

| Section | File | Backend endpoints |
|---------|------|-------------------|
| 1. Проект (Project) | `ProjectSection.tsx` | `GET/POST /projects`, `GET/POST /workspaces` |
| 2. Kanban-доска (Board) | `BoardSection.tsx` | `GET /workflows/runs`, `GET /workflows/runs/{id}/tasks` |
| 3. Конвейер и роли (Conveyor & roles) | `ConveyorSection.tsx` | `GET /agents`, `POST /agents/register`, run tasks |
| 4. Запуски и результаты (Runs) | `RunsSection.tsx` | `POST /workflows/runs`, `GET /workflows/runs...` |
| 5. Карточка задачи (Task card) | `TaskSection.tsx` | `GET /tasks/{id}`, attempts, claim/submit/fail/block |
| 6. Живой журнал (Agent log) | `AgentLogSection.tsx` | polling `getRunSnapshot` (see below) |

All sections consume the single typed `ApiAdapter` (`src/api/`) which defaults
to the real HTTP backend (integration path). Tests and offline development use
`{ mock: true }` → `MockAdapter`, a fully offline in-memory implementation that
mirrors the orchestration-server behaviour.

### Live agent log — polling decision

There is **no dedicated SSE log/stream endpoint** in the backend contract yet.
Per ADR-101 §8 (migration period), the MVP live log uses **short-interval
polling**: `AgentLogSection` polls the existing `getRunSnapshot`
(`GET /workflows/runs/{id}` + `GET /workflows/runs/{id}/tasks`) every
`POLL_MS = 2000 ms` and diffs consecutive snapshots into `RunLogEvent`s via the
pure `diffToEvents` helper. This keeps the section operational against the real
backend and the mock without expanding scope to a backend stream endpoint.
A future SSE endpoint can replace the poller without changing the section UI.

## Layout

```
frontend/
  Makefile                     # make check gate
  scripts/validateSchema.mjs   # AT3 schema gate (Draft 2020-12 meta-schema + const "1.0")
  src/
    workflow/
      types.ts                 # canonical Workflow Definition types
      workflow.schema.json     # JSON Schema (Draft 2020-12), schema_version "1.0"
      validateGraph.ts         # pure graph validator (single start, >=1 end, no cycles,
                               #   reachability, unique ids, dangling endpoints, agent refs)
      validateGraph.test.ts
      workflowSchema.test.ts
    editor/                    # canvas editor, palette, store, panels (T2/T3)
    api/                       # typed persistence API client (T4)
    styles/                    # design tokens + global baseline (ADR-110)
    components/                # token-driven component library + tests
    patterns/                  # AppShell, PageHeader, AsyncBoundary
    i18n/                      # ru/en catalog + provider (ADR-110 §3.5)
    pages/                     # core layouts: ProjectDashboard, TaskBoard,
                               #   AgentMonitor, SettingsPage
    App.tsx
    main.tsx
```

## Workflow Definition

A workflow document has `schema_version: "1.0"` and looks like:

```json
{
  "schema_version": "1.0",
  "metadata": { "name": "...", "version": 1, "created_at": "..." },
  "nodes": [{ "id": "...", "type": "start", "label": "...", "position": { "x": 0, "y": 0 }, "config": {} }],
  "edges": [{ "id": "...", "source_node_id": "...", "target_node_id": "...", "output_mapping": {}, "on_error": "fail", "max_retries": 0 }]
}
```

Node types: `start`, `agent`, `condition`, `gate`, `parallel`, `join`,
`human_approval`, `tool`, `memory`, `delay`, `end`. Graph invariants
(single start, at least one end, no cycles, reachability, unique ids,
dangling endpoints, required agent references) are enforced by
`validateGraph` and covered by unit tests.

## Commands

```sh
npm ci          # install (lockfile-scoped)
npm run dev     # start dev server
npm run typecheck
npm run lint
npm run test -- --run          # run unit tests once
npm run schema:validate        # AT3 schema gate
npm run build
make check      # the full gate
```