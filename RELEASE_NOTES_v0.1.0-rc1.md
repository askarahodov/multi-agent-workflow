# Release Notes v0.1.0-rc1

**Release Date:** 2026-10-30
**Release Type:** Release Candidate (pre-release)
**Git Tag:** `v0.1.0-rc1` (annotated, SSH-signed; tag object `4f4fec7`)
**Tagged Commit:** `42b5354` (`42b53548ba121814fff46520ca979efaaadc8bde`)
**Baseline:** `rc-1.0.0` (`8fa2fbd`); merge-base `295a8bc`
**Published:** GitHub pre-release `v0.1.0-rc1`, published `2026-10-30T12:23:37Z`
**Verified Candidate:** `a613a54` (tree-identical to the tagged commit)

---

## Overview

This is the first release candidate of the Multi-Agent Workflow System — a platform for
orchestrating autonomous AI agents that collaborate on software-engineering tasks.

It ships the SDLC pipeline (planner, architect, developer, reviewer, tester, release,
security profiles) coordinated through the Kanban task system, the native agent runtime
loop with leased and fenced tool execution, the quality-gate pipeline, and the
GitHub ↔ Kanban coordination tool.

> **Scope note.** The change list below is generated from the merged pull requests that
> are ancestors of the tagged commit, so it describes exactly what is inside
> `v0.1.0-rc1`. Narrative sections that could not be grounded in the repository were
> removed rather than carried forward.

---

## Changes in this release

This release candidate contains **85 merged pull requests** since the baseline tag `rc-1.0.0` (merge-base `295a8bc87`, `rc-1.0.0` = `8fa2fbd`), up to the tagged commit `42b5354`.

Every entry below links the pull request and records the merge commit SHA on `main`. Grouping follows the [Conventional Commits](https://www.conventionalcommits.org/) type of the merged PR title.

### Features (31)

- `#97` **agent** — durable per-attempt usage and event journal (#21) ([PR #97](https://github.com/askarahodov/multi-agent-workflow/pull/97), merge `404001247`)
- `#98` **worker** — finish leased shutdown, secure Compose and crash-restart acceptance (#33) ([PR #98](https://github.com/askarahodov/multi-agent-workflow/pull/98), merge `488464a55`)
- `#101` **sdlc** — persistent task prerequisite routing and native task context (#11) ([PR #101](https://github.com/askarahodov/multi-agent-workflow/pull/101), merge `61aecca13`)
- `#102` **git** — trusted per-attempt worktree and fenced no-replay commit (#11) ([PR #102](https://github.com/askarahodov/multi-agent-workflow/pull/102), merge `d3cf1af70`)
- `#103` **native** — connect Git worktrees to leased HTTPS gateway and persist task SHA (#11) ([PR #103](https://github.com/askarahodov/multi-agent-workflow/pull/103), merge `f0b82b066`)
- `#106` **native** — verify durable Git ref and committed tree before ledger success (#11) ([PR #106](https://github.com/askarahodov/multi-agent-workflow/pull/106), merge `f3016fbae`)
- `#110` **P0 #11** — cryptographically signed independent QA gates for native SDLC stages ([PR #110](https://github.com/askarahodov/multi-agent-workflow/pull/110), merge `de782c3fe`)
- `#113` **#11** — autonomous independent QA controller for native seven-stage Git SDLC ([PR #113](https://github.com/askarahodov/multi-agent-workflow/pull/113), merge `9450a53a1`)
- `#114` **#11** — authenticated TLS QA Compose profile and trusted signed-handoff wiring ([PR #114](https://github.com/askarahodov/multi-agent-workflow/pull/114), merge `e9f8fdae0`)
- `#120` **#117** — introduce opt-in isolated Docker QA executor ([PR #120](https://github.com/askarahodov/multi-agent-workflow/pull/120), merge `6c7083e17`)
- `#132` **#117** — introduce standalone no-secret QA runner entrypoint ([PR #132](https://github.com/askarahodov/multi-agent-workflow/pull/132), merge `5b3d057e9`)
- `#133` **#117** — version untrusted QA runner result contract ([PR #133](https://github.com/askarahodov/multi-agent-workflow/pull/133), merge `c45f4b843`)
- `#134` **#117** — strict unsigned runner result validation ([PR #134](https://github.com/askarahodov/multi-agent-workflow/pull/134), merge `e54bb7f65`)
- `#135` **#117** — bind unsigned QA result to launcher-observed command and exit code ([PR #135](https://github.com/askarahodov/multi-agent-workflow/pull/135), merge `aa39c2626`)
- `#136` **#117** — fail closed on repeated QA execution IDs in verifier ([PR #136](https://github.com/askarahodov/multi-agent-workflow/pull/136), merge `5c2f3d973`)
- `#137` **#117** — persistent atomic runner replay IDs across verifier restarts ([PR #137](https://github.com/askarahodov/multi-agent-workflow/pull/137), merge `f0021eb35`)
- `#145` **#11** — manage Docker QA via create/start/wait/cleanup lifecycle ([PR #145](https://github.com/askarahodov/multi-agent-workflow/pull/145), merge `dee071d46`)
- `#146` **#11** — durable dependency-aware ready-task discovery for native dispatcher ([PR #146](https://github.com/askarahodov/multi-agent-workflow/pull/146), merge `48c18fdcb`)
- `#147` **#11** — wire native worker to authoritative ready-task scheduler ([PR #147](https://github.com/askarahodov/multi-agent-workflow/pull/147), merge `4cefde61d`)
- `#162` **native** — require Git evidence for leased SDLC completion (issue 11 progress) ([PR #162](https://github.com/askarahodov/multi-agent-workflow/pull/162), merge `ed84c83d2`)
- `#163` **native** — independently verify attempt Git refs before Contract Gate (issue 11) ([PR #163](https://github.com/askarahodov/multi-agent-workflow/pull/163), merge `c5faf88a6`)
- `#165` **native** — require separate operator approval before SDLC run completion (issue 11) ([PR #165](https://github.com/askarahodov/multi-agent-workflow/pull/165), merge `6862a6cfd`)
- `#167` **native** — explicit bounded autonomous task dispatcher (issue 11) ([PR #167](https://github.com/askarahodov/multi-agent-workflow/pull/167), merge `fcd8fe82d`)
- `#168` **native UI** — contract-bound workflow launch for leased SDLC (issue 11) ([PR #168](https://github.com/askarahodov/multi-agent-workflow/pull/168), merge `ca0d01a46`)
- `#172` **native UI** — launch canonical seven-stage Contract Gate SDLC graph (issue 11) ([PR #172](https://github.com/askarahodov/multi-agent-workflow/pull/172), merge `542675ac8`)
- `#175` **native** — bounded opt-in autonomous independent QA dispatch for trusted SDLC (issue 11) ([PR #175](https://github.com/askarahodov/multi-agent-workflow/pull/175), merge `dd7f6a7ed`)
- `#177` **native** — opt-in outbound OpenRouter route for isolated worker (issue 11) ([PR #177](https://github.com/askarahodov/multi-agent-workflow/pull/177), merge `77a61e387`)
- `#178` **native** — enable real leased Git artifacts in protected worker/gateway Compose (issue 11) ([PR #178](https://github.com/askarahodov/multi-agent-workflow/pull/178), merge `a1ab23e74`)
- `#179` **native** — enforce complete protected seven-stage Compose policy before live run (issue 11) ([PR #179](https://github.com/askarahodov/multi-agent-workflow/pull/179), merge `c7b0a00e8`)
- `#186` **architecture** — enumerate static path consumers for #182 ([PR #186](https://github.com/askarahodov/multi-agent-workflow/pull/186), merge `2b0bd543e`)
- `#193` **coordination** — two-way GitHub ↔ Kanban sync tool (#192) ([PR #193](https://github.com/askarahodov/multi-agent-workflow/pull/193), merge `ef9d50fb9`)

### Bug Fixes (22)

- `#99` **agent** — complete OpenRouter streaming and durable usage acceptance (#9) ([PR #99](https://github.com/askarahodov/multi-agent-workflow/pull/99), merge `7147c1fff`)
- `#104` **native** — enforce project scope for SDLC workspace and contracts (#11) ([PR #104](https://github.com/askarahodov/multi-agent-workflow/pull/104), merge `04b27799f`)
- `#105` **native** — disallow Contract Gate bypass for leased SDLC tasks (#11) ([PR #105](https://github.com/askarahodov/multi-agent-workflow/pull/105), merge `f2162b1d9`)
- `#108` **release** — require authenticated admin for approval; reject worker-forged approver (#11) ([PR #108](https://github.com/askarahodov/multi-agent-workflow/pull/108), merge `9b32832c3`)
- `#119` **#117** — stop QA process tree when tests time out ([PR #119](https://github.com/askarahodov/multi-agent-workflow/pull/119), merge `6c258a0c6`)
- `#121` **#117** — remove timed-out isolated QA containers ([PR #121](https://github.com/askarahodov/multi-agent-workflow/pull/121), merge `519a01644`)
- `#122` **#117** — reject newline/CR mount path injection in QA Docker runner ([PR #122](https://github.com/askarahodov/multi-agent-workflow/pull/122), merge `592a689e1`)
- `#127` **#117** — enforce local-only Docker QA images ([PR #127](https://github.com/askarahodov/multi-agent-workflow/pull/127), merge `2f9b56d1a`)
- `#150` **qa** — enforce gate and receipt scope before autonomous QA registration (#148 #149) ([PR #150](https://github.com/askarahodov/multi-agent-workflow/pull/150), merge `6571ae874`)
- `#152` **security** — prevent cross-task Quality Gates run evidence disclosure (#151) ([PR #152](https://github.com/askarahodov/multi-agent-workflow/pull/152), merge `85168297d`)
- `#154` **qa** — persist failed gate runs when execution aborts (#153) ([PR #154](https://github.com/askarahodov/multi-agent-workflow/pull/154), merge `8d429ba48`)
- `#156` **qg** — deterministic fail-closed gate retry ordering (#155) ([PR #156](https://github.com/askarahodov/multi-agent-workflow/pull/156), merge `4afb04e23`)
- `#158` **security** — confine QA evidence file reads and writes to root (#157) ([PR #158](https://github.com/askarahodov/multi-agent-workflow/pull/158), merge `b4ed666f0`)
- `#160` **security** — reject unsafe evidence category paths (#159) ([PR #160](https://github.com/askarahodov/multi-agent-workflow/pull/160), merge `aae94f9f1`)
- `#161` **#11** — fail closed on incomplete trusted native-worker runtime preflight ([PR #161](https://github.com/askarahodov/multi-agent-workflow/pull/161), merge `b381b5cf3`)
- `#164` **native** — enforce Git blob size cap in independent server verifier (issue 11) ([PR #164](https://github.com/askarahodov/multi-agent-workflow/pull/164), merge `522f30538`)
- `#166` **native** — prevent active workflow starvation in bounded worker polls (issue 11) ([PR #166](https://github.com/askarahodov/multi-agent-workflow/pull/166), merge `2a0bebd21`)
- `#169` **native** — preserve fair workflow cursor across automatic dispatch sessions (issue 11) ([PR #169](https://github.com/askarahodov/multi-agent-workflow/pull/169), merge `e1185ee24`)
- `#171` **native** — prevent task starvation after bounded workflow task pages (issue 11) ([PR #171](https://github.com/askarahodov/multi-agent-workflow/pull/171), merge `81a21e88f`)
- `#176` **native QA** — fair workflow and task pagination for autonomous controller (issue 11) ([PR #176](https://github.com/askarahodov/multi-agent-workflow/pull/176), merge `833941b5d`)
- `#180` **native** — fail closed on unusable QA command and missing live credentials (issue 11) ([PR #180](https://github.com/askarahodov/multi-agent-workflow/pull/180), merge `da657e67d`)
- `#185` **frontend** — patch fast-uri to 3.1.9 without Vite 8 upgrade ([PR #185](https://github.com/askarahodov/multi-agent-workflow/pull/185), merge `546502203`)

### Security (10)

- `#109` **qa** — prevent native workers from self-issuing QA and release transition evidence (#11) ([PR #109](https://github.com/askarahodov/multi-agent-workflow/pull/109), merge `2cf51ba7f`)
- `#112` **#11** — verify Git HEAD and evidence bytes before signing native QA receipt ([PR #112](https://github.com/askarahodov/multi-agent-workflow/pull/112), merge `e91ee87d7`)
- `#128` **#117** — fail closed if QA Docker executor inherits signer credentials ([PR #128](https://github.com/askarahodov/multi-agent-workflow/pull/128), merge `92c1686c3`)
- `#130` **#117** — fail closed on credential marker presence ([PR #130](https://github.com/askarahodov/multi-agent-workflow/pull/130), merge `4ebce3d43`)
- `#138` **#117** — require private replay database permissions ([PR #138](https://github.com/askarahodov/multi-agent-workflow/pull/138), merge `775f66936`)
- `#140` **#117** — require clean Git checkout at expected SHA for isolated runner ([PR #140](https://github.com/askarahodov/multi-agent-workflow/pull/140), merge `543d61257`)
- `#141` **#117** — operator-enforced fail-closed in-process tester cutover ([PR #141](https://github.com/askarahodov/multi-agent-workflow/pull/141), merge `69ee6e3f4`)
- `#143` **#117** — explicitly disable Docker IPC for isolated QA ([PR #143](https://github.com/askarahodov/multi-agent-workflow/pull/143), merge `8b0b3f1eb`)
- `#144` **#117** — verify Docker absence after timeout cleanup ([PR #144](https://github.com/askarahodov/multi-agent-workflow/pull/144), merge `41c8343bf`)
- `#181` **native** — reject symlinked credential ancestors for worker and OpenRouter (issue 11) ([PR #181](https://github.com/askarahodov/multi-agent-workflow/pull/181), merge `e9183f3d0`)

### Refactoring (1)

- `#187` **architecture** — archive historical reports for #182 ([PR #187](https://github.com/askarahodov/multi-agent-workflow/pull/187), merge `7fbbc72b6`)

### Documentation (6)

- `#89` **governance** — inventory and safe main protection rollout (#44) ([PR #89](https://github.com/askarahodov/multi-agent-workflow/pull/89), merge `232848ccd`)
- `#126` **#117** — establish independent QA runner trust boundary and acceptance contract ([PR #126](https://github.com/askarahodov/multi-agent-workflow/pull/126), merge `3c728bed0`)
- `#184` **architecture** — coordinate repository restructuring without clobbering local agent work (#182) ([PR #184](https://github.com/askarahodov/multi-agent-workflow/pull/184), merge `4b462412e`)
- `#188` **security** — apply main ruleset control and correct SEC-001 bypass analysis (t_de91cac5) ([PR #188](https://github.com/askarahodov/multi-agent-workflow/pull/188), merge `c94245ffc`)
- `#190` **security** — fix SECURITY_AUDIT.md B1/B2 — release-gate review blockers (t_07eb7c2e) ([PR #190](https://github.com/askarahodov/multi-agent-workflow/pull/190), merge `274ee405d`)
- `#191` **rollout** — land ROLLOUT_PLAN.md v3 (human gate) ([PR #191](https://github.com/askarahodov/multi-agent-workflow/pull/191), merge `b42005336`)

### Tests (14)

- `#100` **qa** — real Compose browser/API acceptance and restart evidence (#8) ([PR #100](https://github.com/askarahodov/multi-agent-workflow/pull/100), merge `564c1afca`)
- `#107` **native** — full seven-stage HTTP/LLM-tool/Git SDLC replay across server restart (#11) ([PR #107](https://github.com/askarahodov/multi-agent-workflow/pull/107), merge `d546ff360`)
- `#115` **#11** — real protected TLS/QA Docker Compose smoke with restart and role isolation ([PR #115](https://github.com/askarahodov/multi-agent-workflow/pull/115), merge `3fb75c765`)
- `#116` **#11** — fail native E2E if Hermes is on execution PATH ([PR #116](https://github.com/askarahodov/multi-agent-workflow/pull/116), merge `690317804`)
- `#123` **#117** — exercise isolated QA runner on actual Docker daemon ([PR #123](https://github.com/askarahodov/multi-agent-workflow/pull/123), merge `db076ef00`)
- `#124` **#117** — verify external QA signing fixture stays invisible in Docker ([PR #124](https://github.com/askarahodov/multi-agent-workflow/pull/124), merge `4f947bcb2`)
- `#125` **#117** — guard signed QA Compose against Docker host privilege regression ([PR #125](https://github.com/askarahodov/multi-agent-workflow/pull/125), merge `3633144f1`)
- `#131` **#117** — enforce Docker QA launcher minimal env and mount contract ([PR #131](https://github.com/askarahodov/multi-agent-workflow/pull/131), merge `757655c62`)
- `#139` **#117** — verify atomic concurrent runner replay rejection ([PR #139](https://github.com/askarahodov/multi-agent-workflow/pull/139), merge `2e565e6c7`)
- `#142` **#117** — fail closed on Docker timeout cleanup failure ([PR #142](https://github.com/askarahodov/multi-agent-workflow/pull/142), merge `68aaa62ef`)
- `#170` **native** — UI-shaped leased SDLC across real REST and SQLite restart (issue 11) ([PR #170](https://github.com/askarahodov/multi-agent-workflow/pull/170), merge `7a9009dee`)
- `#173` **native** — complete seven-stage Git, independent QA and release-approval chain (issue 11) ([PR #173](https://github.com/askarahodov/multi-agent-workflow/pull/173), merge `1a8ea3340`)
- `#174` **browser** — Compose UI seven-stage Contract Gate launch and reload (issue 11) ([PR #174](https://github.com/askarahodov/multi-agent-workflow/pull/174), merge `cb2317eb4`)
- `#189` **gitflow** — hermetic violation suite + required-checks gate alignment ([PR #189](https://github.com/askarahodov/multi-agent-workflow/pull/189), merge `29a0d43fd`)

### Release (1)

- `#197` — v0.1.0-rc1 — RC candidate (fix B1 poll↔webhook convergence + SEC-RC-001 CI injection) ([PR #197](https://github.com/askarahodov/multi-agent-workflow/pull/197), merge `42b53548b`)

---

## Direct commits on `main` (no pull request)

The following commits are on `main` in this range without an associated merged pull request:

- `6f15980` — feat(t_5ba84eb3): implement gitflow hooks, ci checks and policy distribution
- `5bf7cef` — fix(docs): replace Slack credential placeholders with .env guidance

The tagged commit `42b5354` and its parent `f275aa7` are the two commits carried by
release PR [#197](https://github.com/askarahodov/multi-agent-workflow/pull/197)
(branch `release/v0.1.0`); they are not standalone pushes to `main`.

---

## Excluded from this release candidate

- **P1 `frontend/src/api/runStream.ts`** (task `t_ff8817c5`) is **EXCLUDED** from
  `v0.1.0-rc1`. The live-run stream hardening is not part of this release line: the file
  exists only on branch `wt/t_ff8817c5` (head `e72a641`) and is absent from the tagged
  commit `42b5354`. Do not expect run-stream changes in the RC artifacts.

---

## Compatibility notes

- Dispatcher/worker polling is configured with `poll_interval_seconds` (the former
  `poll_interval` name is not read by the current code).
- The GitHub ↔ Kanban webhook receiver requires a shared secret
  (`GKS_WEBHOOK_SECRET`) and verifies the request signature before ingesting an event.
- Kanban worktree tasks carry an explicit `completion_contract`
  (`local-only`, `OWNER/REPO`, or a PR URL).
- SQLite remains the default datastore; PostgreSQL is an optional extra
  (`postgres = ["asyncpg>=0.29"]`) and the `postgres` service in `docker-compose.yml`
  is optional.

---

## Version scheme

- The release identifier lives in the root **`VERSION`** file — single source of truth —
  and matches the git tag without the `v` prefix (`v0.1.0-rc1` → `0.1.0-rc1`).
- The root `package.json` carries the same release identifier; the release workflow's
  `Verify version consistency` step compares it against the tag.
- Internal component distributions carry the base version of the release line
  (`0.1.0`) because they are pinned to each other (`maw-shared==0.1.0`,
  `agent-management==0.1.0`); a pre-release suffix on a pinned internal dependency
  would require re-pinning every consumer.
- See [`docs/developer/versioning.md`](https://github.com/askarahodov/multi-agent-workflow/blob/main/docs/developer/versioning.md)
  for the full scheme.

---

## Artifacts

| Artifact | Digest |
|----------|--------|
| `multi-agent-workflow-0.1.0-rc1.tar.gz` | `sha256:56aa566ee149ce072c4b78c9f6df2f37ec2c63c7a99ca9063e939d8ce54559d4` |

Published container images (`ghcr.io/askarahodov/multi-agent-workflow-<service>:v0.1.0-rc1`):

- `orchestration-server`
- `agent-management`
- `runtime-hardening`
- `frontend`
- `quality-gates`

Source tarball and its `.sha256` companion are attached to the GitHub pre-release.

---

## Upgrade

This is the first tagged release — there is no prior tagged version to migrate from.
For a development deployment:

```bash
git fetch --tags
git checkout v0.1.0-rc1

# 1. Back up the local Kanban database
cp data/kanban.db data/kanban.db.backup

# 2. Rebuild and start the stack
docker compose build
docker compose up -d

# 3. Verify (orchestration-server is published on host port 18000)
curl http://localhost:18000/health
```

---

## Links

- **GitHub Release:** https://github.com/askarahodov/multi-agent-workflow/releases/tag/v0.1.0-rc1
- **Repository:** https://github.com/askarahodov/multi-agent-workflow
- **Issues:** https://github.com/askarahodov/multi-agent-workflow/issues

---

*This release candidate is intended for testing and validation. Report issues via GitHub
Issues. The stable `v0.1.0` release follows after RC validation.*
