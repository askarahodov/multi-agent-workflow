# Documentation dependency security — Issue #208

## Current dependency graph (2026-11-03 baseline)

The root `package.json` and `package-lock.json` use VitePress' math support
(`docs/.vitepress/config.mts` sets `markdown.math: true`). The root lockfile
contains `katex@0.16.47` and `markdown-it@15.0.3`, but **does not install
`markdown-it-katex`**. The frontend lockfile also contains no copy of that
retired plugin.

`markdown-it-katex@2.0.3` has a high-severity XSS advisory with **no fixed
version**: [GHSA-5ff8-jcf9-fw62](https://github.com/advisories/GHSA-5ff8-jcf9-fw62).
Upgrading this package would not solve the advisory; introducing a replacement
plugin is unnecessary as VitePress already renders math.

The failed [Dependabot workflow run
41404677996](https://github.com/askarahodov/multi-agent-workflow/actions/runs/41404677996)
targeted older commit `916260b`. Its registry timeouts and
`security_update_not_found` error do not prove the retired package is installed
in the current tree. Re-running Dependabot against the newest `main` remains
a **separate, network-dependent confirmation** and has not been performed by
this offline change.

## Regression guard

`scripts/check-docs-deps.js` checks the root manifest and *all installed
package paths and dependency declarations* in the root lockfile. It rejects
direct, nested/transitive, lockfile-only and npm-aliased references to `markdown-it-katex`
and fails closed for missing or invalid files. The documentation dependency
workflow executes this guard **before** its networked lockfile regeneration
and install. Offline regression tests cover forbidden and safe graphs.

From repository root:

```sh
node --test scripts/check-docs-deps.test.js
node scripts/check-docs-deps.js
```

This check does **not** replace an `npm audit`, a fresh Dependabot update
attempt, or the existing VitePress build and link tests. For Issue #208, inspect
the new PR's CI result and a new Dependabot run on its merged `main` before
closing the investigation; do not automatically merge or deploy.
