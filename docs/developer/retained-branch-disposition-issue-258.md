# Issue #258 — disposition of retained branches (read-only review)

**Audit date:** 2026-11-06. **Product base:** `main@be52e2a71318684375dd30a90ddbd4496695d7ee`. GitHub `GET /branches?per_page=100` returned exactly **10 remote branches** including protected `main`. The table records the exact observed heads, not a hypothetical working-tree status.

## Complete remote-branch inventory and disposition

The decision for **every** non-main branch in this snapshot is explicitly **KEEP**; none is approved for destructive removal or an unreviewed bulk merge. This is a deliberate preservation decision, not an implication that unique commits are integrated into main.

| Branch | Exact observed HEAD | `main...branch` comparison | Decision and content-level rationale |
| --- | --- | --- | --- |
| `ci/pr-run-concurrency` | `60261effc5f3f5ed2bdd2e0cdad22e146a41f576` | 9 ahead / 62 behind | **KEEP — superseded CI proposal** — Candidate uses a stable github.ref concurrency group whereas current main uses github.run_id for non-PR events. Never port this by blanket cherry-pick: on main, sequential pushes must not have a pending required run displaced by a newer push. All nine workflow changes need a separate owner-approved design change, not a cleanup merge. |
| `coord/external-qa` | `e12ab4bf8c0a768490ed00c46e763d484b6ae4b8` | 374 ahead / 322 behind | **KEEP — active isolated coordination channel** — Independent QA channel with ongoing requests, responses and sync state. MUST NOT merge into product main and MUST NOT delete. |
| `fix/209-bound-stream-ticket-input` | `3da3d211d852c8b33c6656c1683c2ddb195f1a25` | open, exact SHA | **KEEP — open PR #284** — Security PR head; preserve until independent security/QA acceptance, merge/rollback decision and automatic PR branch cleanup. No premature merge/deletion. |
| `qa-sync-test-1792050525` | `1f0803be69379ca9ae0fc45583a8a9dc64c82260` | no common ancestor | **KEEP — unattached synthetic evidence** — Orphan-root QA sync snapshot (GitHub compare returns 404: no common ancestor); no product port; retaining historical identity avoids irreversible deletion until evidence retention is approved. |
| `release/v0.1.0` | `a613a54c146aa244aba959f4f3237d582cc00798` | 2 ahead / 150 behind | **KEEP — release line** — Named v0.1.0 release maintenance branch; its two unique commits touch GitFlow and GitHub/Kanban safety tests. Retain per release policy; never replace current main with old release history. |
| `test-substance-components-1791965479` | `c42b72f109d957f10689ae71a3810859375200ce` | no common ancestor | **KEEP — unattached synthetic evidence** — Synthetic test snapshot without common ancestor; do not treat as merged and do not delete until forensic/evidence retention policy authorizes it. |
| `test-workflows-1791891554` | `3196848c91e6ac567a12e3b79728b3f4ad0ed3c7` | 9 ahead / 322 behind | **KEEP — obsolete CI-test snapshot** — Contains experimental workflow-test files, ad-hoc trigger marker and pre-migration CI repairs. The current main owns the production CI/Quality Gate suite; do not bulk-port ancient workflow versions or trigger files. Retain only as historical test identity. |
| `wt/t_1fd6385e` | `bcda741376023262321b37222e0ee6f84a64e761` | 2 ahead / 154 behind | **KEEP — historical security evidence** — Contains main-protection audit reports, GH013 negative direct-push evidence and old security runbook. Current main has newer main-protection auditor/runbook (#44); retain unique evidence in source branch, do not overwrite modern docs or clean the attached worktree. |
| `wt/t_759fb8e6` | `36fc1350a4d2bda507d34c21e513b88759c93763` | 6 ahead / 322 behind | **KEEP — historical CI test worktree** — Includes merged PR #10 ancestry plus independent experimental workflow-test commits; production CI tests supersede this trial. Retain branch/worktree as historical record; no blind cherry-pick. |

**Default `main`:** `be52e2a71318684375dd30a90ddbd4496695d7ee` (`protected=true` from GitHub branches API); no direct push, force update or protection change was made in this audit.

## Why no code cherry-picks or branch deletes are authorized

1. **No missing production change was established.** The old CI experiments and worktree snapshots differ from `main`, but newer product CI, QA and security controls are in place. A compare's `ahead_by` only proves distinct commits, not missing functionality. Backport of an older CI file would overwrite later production gates.
2. **Keep release and channel boundaries.** `release/v0.1.0` is intentionally separate; `coord/external-qa` is an isolated active synchronization channel, not a product branch. The PR #284 security branch remains live until its own independent review.
3. **Two synthetic QA branches have unrelated Git histories.** GitHub returns `404 No common ancestor` for each. They cannot be classified as merged through ancestry and have been retained as historical snapshots.
4. **Security and QA evidence is historical evidence.** `wt/t_1fd6385e` includes negative GH013 results and ruleset snapshots. No migration is needed merely to make a snapshot executable from `main`; current `docs/security/main-protection-rollout-issue-44.md` and `scripts/git/check_main_ruleset.py` own live governance validation.

## Local worktree and untracked-data boundary

Earlier owner-side inventory on #258 reported **91 worktrees**, around **90 local branches**, dirty/ignored service data and hundreds of untracked evidence files. **This GitHub-only audit cannot independently inspect those local paths or certify that their contents have been backed up.** Therefore no `git worktree remove`, `git clean`, local branch deletion, force reset, archive move, branch deletion or external QA mutation was performed. The decision is **PRESERVE IN PLACE**. Before any separate local cleanup, an authorized host operator must record `git worktree list --porcelain`, per-worktree `git status --porcelain=v1 -uall`, ignored-file inventory, explicit backups/checksums and owners' sign-off. Until then, local state is out of bounds for deletion.

## Exit criteria and ongoing maintenance

The retained-branch **triage** is complete for the enumerated snapshot: every remote branch has an exact SHA and explicit disposition; there are no approved remote deletions and no justified selective product ports. This does **not** claim local worktree cleanup, independent acceptance of #209, completion of #44 governance review, or resolution of #208 Dependabot. Re-audit when remote heads change or a branch owner proposes deletion; for any future non-ancestry-merged deletion, first record the head SHA, content comparison, approval and restoration path.

Reference: [issue #258](https://github.com/askarahodov/multi-agent-workflow/issues/258).
