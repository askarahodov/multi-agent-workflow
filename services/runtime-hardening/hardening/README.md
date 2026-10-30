# Agent Runtime — P8.3 Runtime Hardening

Hardened runtime components for the Harbor-Transfer-Portal agent sandbox, per
technical specification `runtime-hardening-spec.md` (ADR-011) from the architect
task `t_c39cb99e`.

## Components (spec §2)

| Component | Module | Spec section |
|---|---|---|
| Isolation layer (tier selector + admission + sandbox wrapper) | `src/runtime/hardening/isolation.py` | §3 (AC-1, AC-2) |
| Resource controller (cgroups v2) | `src/runtime/hardening/resource_manager.py` | §4 (AC-3, AC-4) |
| Resilience framework (CB/bulkhead/timeout/retry/budget) | `src/runtime/hardening/resilience.py` | §5 (AC-5, AC-6) |
| Degradation controller | `src/runtime/hardening/degradation.py` | §5.3 |
| Workspace manager (atomic lifecycle + reaper) | `src/runtime/hardening/workspace_manager.py` | §6 (AC-7, AC-8) |
| Observability (health/logs/metrics/OTel) | `src/runtime/hardening/observability.py` | §7 (AC-9) |
| Control-plane API | `src/runtime/hardening/api.py` | §2.1, §8 |
| Shared data contracts | `src/runtime/hardening/models.py`, `config.py` | §8 |

## Relationship to sibling `runtime/` implementation

This directory (`hardening/`) is the self-contained delivery of the SDLC-chain
implementation (kanban task `t_a0f09cd1`), packaged as `agent-runtime-hardening`
under `src/runtime/hardening/`. It is a *distinct* implementation from the
flat-module `runtime/` P8.3 package already present at
`runtime-hardening/runtime/` (task `t_cea09e5d`, commit `fa1da65`). Both target
ADR-011; this package adds explicit isolation, degradation and observability
modules. Per the operator consolidation rule, the two coexist without
overwriting each other: `config/resource-quota.schema.json` and
`config/resource-quotas.example.yaml` are byte-identical to the sibling's;
`config/settings.example.yaml` differs (this package's RuntimeSettings). See
`docs/IMPLEMENTATION.md` §8 for the full divergence list.

## Interface contracts (spec §8)

- `api/agent-runtime-openapi.yaml` — OpenAPI 3.1 control-plane contract
- `api/lifecycle-events-asyncapi.yaml` — AsyncAPI 2.6 lifecycle event bus
- `config/resource-quota.schema.json` — quota JSON Schema (draft 2020-12)
- `config/resource-quotas.example.yaml` — example classes / parent budget
- `config/settings.example.yaml` — runtime settings example

## Layout

```
src/runtime/hardening/   package source
tests/unit/hardening/    unit tests per component
tests/integration/       integration tests (real container runtime)
tests/chaos/             resilience/degradation tests
config/ api/ docs/       contracts, configs, docs
reports/                 coverage HTML + junit.xml + SUMMARY.txt
```

## Verify

```
uv sync --extra dev
uv run pytest -q --cov=src/runtime --cov-report=term-missing
uv run ruff check src tests
uv run mypy
```

## Known limitations (see docs/IMPLEMENTATION.md)

- Real overlayfs mounts and `tc` network shaping are modelled but not wired to
  a real veth/host (documented deviation, gated by
  `isolation.enable_real_mounts` / `enable_tc_qdisc`).
- gVisor/Kata backends require runsc/kata runtime binaries not present on this
  host; the reference backend is Docker (`runc`), selectors + admission are
  fully unit-tested.
- OTel exporter is a no-op-compatible hook (no `opentelemetry` dependency);
  W3C trace correlation is emitted on structured logs.
- mTLS/bearer auth is declared in the OpenAPI security block but not enforced
  by the reference app (deployment responsibility).
