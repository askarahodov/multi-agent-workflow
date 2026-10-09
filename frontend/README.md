# Workflow Editor (frontend)

Visual workflow editor for designing agentic processes. This is the frontend
application for the AI Multi-Agent Workflow platform.

## Stack

- TypeScript 5 + React 18 + Vite 5
- Canvas: React Flow (`@xyflow/react` v12)
- State: Zustand 4
- Validation: ajv 8 (JSON Schema Draft 2020-12) + a pure graph validator
- Unit tests: Vitest + Testing Library + jsdom
- e2e: Playwright (downstream task T6)
- Lint/format: ESLint 9 + Prettier

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