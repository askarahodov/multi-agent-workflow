# Versioning

This repository ships several independently installable components from one release
line. This page is the authoritative description of how version numbers are assigned so
that no component drifts from the release.

## Single source of truth

The repository root holds a plain-text **`VERSION`** file:

```text
0.1.0-rc1
```

It contains the release identifier — the git tag **without** the `v` prefix
(`v0.1.0-rc1` → `0.1.0-rc1`) — and is the value the release is cut from.

## Release-level stamps

| File | Value | Consumed by |
|------|-------|-------------|
| `VERSION` | `0.1.0-rc1` | release tooling, humans |
| `package.json` (`version`) | `0.1.0-rc1` | `release.yml` → *Verify version consistency* (compares it to the pushed tag) |

The release workflow fails the release if `package.json` does not equal the tag minus
`v`, so `package.json` and `VERSION` must be bumped together when a release is cut.

## Component-level stamps

The internal distributions and the frontend carry the **base version of the release
line** — `0.1.0` for the `0.1.0-rc1` release:

| Component | File | Value |
|-----------|------|-------|
| `agent-management` | `agent-management/pyproject.toml` | `0.1.0` |
| `orchestration-server` | `orchestration-server/pyproject.toml` | `0.1.0` |
| `quality-gates` | `quality-gates/pyproject.toml` | `0.1.0` |
| `maw-shared` | `shared/pyproject.toml` | `0.1.0` |
| `multi-agent-workflow-tools` | `tools/pyproject.toml` | `0.1.0` |
| `agent-runtime` | `runtime-hardening/pyproject.toml` | `0.1.0` |
| `agent-runtime-hardening` | `runtime-hardening/hardening/pyproject.toml` | `0.1.0` |
| frontend | `frontend/package.json` | `0.1.0` |

Each component also exposes its version at runtime via `__version__` in its package
`__init__.py`; those values match the component manifest.

### Why the pre-release suffix is not propagated to components

Components are pinned to each other by exact version
(`maw-shared==0.1.0`, `agent-management==0.1.0`). Putting the pre-release suffix on an
internal distribution would require re-pinning every consumer
(`maw-shared==0.1.0rc1`, …) and would make the internal graph churn on every RC. The
suffix therefore lives only on the release-level stamps (`VERSION`, `package.json`,
git tag); components stay on the base version for the whole `0.1.0` line.

## What is *not* a package version

The following `1.0.0` values are contract/schema versions and must not be confused with
(or changed to match) the package version:

- `runtime-hardening/**/resource-quota.schema.json` and the `schemaVersion` field of the
  runtime models — the resource-quota schema version.
- `runtime-hardening/hardening/api/*.yaml` — OpenAPI/AsyncAPI document versions.
- `gitflow-policy.schema.json` and `AGENT_GITFLOW_RULES.md` — the GitFlow policy
  registry version (kept in sync by the GitFlow Policy CI job).

## Cutting a release

1. Set `VERSION` and `package.json` `version` to the release identifier.
2. Set the component manifests and `__version__` stamps to the base version of the line.
3. Update `CHANGELOG.md` and the release notes.
4. Commit, merge to `main`, then create the signed tag `v<VERSION>`.
