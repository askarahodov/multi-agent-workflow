# github-kanban-sync

Two-way synchronisation between GitHub Issues/PR/CI and the local Hermes Kanban
board (Issue #192). Developer tooling — **not** a runtime dependency of the AI
Multi Agent Workflow product (ref #11).

See the operator runbook: [`docs/developer/github-kanban-sync-runbook.md`](../../docs/developer/github-kanban-sync-runbook.md).

## What it does

* **ID contract** — one `repo + issue_number` ↔ one `board + task_id`, with
  `pr_number`, `branch`, `base/head_sha`, `owner`, `changed_paths`, `status`,
  `source_event_id`. Unique, idempotent, manually bindable, never clones a card.
* **GitHub → Kanban** — ingests Issues (create/edit/close/reopen/comment), PR
  (open/update/merge) and CI, delivering each change to the owning card with a
  recorded delivery receipt. `*_HANDOFF` comments reach owners with confirmation.
  Delivery is idempotent **at the board level**: the ingest marker embeds the full
  `source_event_id`, so a re-observed event (poll↔webhook, or after a ledger
  reset) is never appended twice.
  Normal `sync` and `daemon` cycles poll **all linked Issue comments and
  unique PR/merge Git SHAs for CI**, not just Issues/PR metadata. Pending
  deliveries are retried independently of the GitHub cursor. An Issue linked
  after an earlier observation is backfilled without cloning the card.
* **Kanban → GitHub** — publishes card status/assignee/blocker/branch/PR/evidence
  as a **versioned, deduplicated** comment on the *linked* Issue. Closes an Issue
  only on confirmed merge + **every explicitly configured GitHub required CI
  context on the merge commit** + acceptance evidence — never on `done`
  alone. Default `GKS_REQUIRED_CHECKS` is unset, so automatic closure fails
  closed until the operator inventories the active `main` ruleset. Skipped,
  missing, pending, neutral, malformed and truncated CI evidence is not green.
  On the normal `sync`/daemon cycle, newly bound **existing** Kanban cards
  bootstrap a versioned status comment in their linked Issue even if earlier
  local task events were already consumed. Failed GitHub publish and rate-limit
  responses do not advance the Kanban event cursor, so later cycles retry
  without cloning Issues or duplicating the published marker.
* **Conflicts** — exact-path / sensitive-dir overlap, ownership reservations and
  stale `main`, reported before dispatch and before merge. Observation only: no
  rebase/reset/merge/delete of any worktree.
* **Transport** — ETag/cursor incremental poll by default; a signature-verified
  webhook is an optional accelerator. Both converge on one `source_event_id`.
  Issues, PRs, comments, and check-runs are fetched **across all GitHub pages**
  before a feed cursor advances. A page failure aborts the entire read, keeping
  the previous cursor intact. For a multi-page feed **or an exactly full 100-item first page**, the
  first-page ETag is not cached: unchanged page 1 cannot hide a newly
  appearing second page. Pagination
  links are validated, never followed as credential-bearing URLs. GitHub's
  official numeric `/repositories/{id}` Link aliases are accepted only after
  resolving the configured repository ID. If records shift across pages, a
  duplicate-ID traversal is retried once; persistent instability fails closed.
  Multi-page Issues use a conservative first-page cutoff (with timestamp
  overlap), and multi-page comments replay instead of risking a lost handoff.
  **Upgrade safety:** the first v2 sync for each feed ignores old first-page
  ETags and stale high-water marks, replays the entire feed through idempotent
  delivery and records a v2 marker. A later safe ETag is retained only for
  verified short single-page feeds; old validators are explicitly cleared in
  SQLite (passing None alone does not clear them). An unsafe legacy
  high-water cursor is also explicitly cleared when a multi-page/full replay
  has no trustworthy new boundary, including comments after an upgrade.
* **Autostart** — the `daemon` command runs the poll loop on an interval with an
  exponential backoff, rate-limit-aware sleeping and a single-writer pidfile, so
  GitHub↔Kanban exchanges happen without manual steps. Bounded (`--once`,
  `--max-iterations`) and stoppable (`--stop`, `SIGINT`/`SIGTERM`).
* **Observability** — `status`/`health` (lag, pending, retries, errors, scheduler
  state), per-event delivery trail, correlation ids, `--dry-run`, `reconcile`.

## CLI

```bash
python -m tools.github_kanban_sync.cli status
python -m tools.github_kanban_sync.cli health
python -m tools.github_kanban_sync.cli sync                 # issues, PRs, linked comments/CI, retry, publish
python -m tools.github_kanban_sync.cli daemon               # autostart: run the loop
python -m tools.github_kanban_sync.cli daemon --once        # one cycle, then exit
python -m tools.github_kanban_sync.cli daemon --stop        # stop the running daemon
python -m tools.github_kanban_sync.cli bind --issue 192 --task t_02d18f3e
python -m tools.github_kanban_sync.cli dedupe --task t_02d18f3e   # remove duplicate ingest comments
python -m tools.github_kanban_sync.cli conflict --live-main "$(git rev-parse origin/main)"
python -m tools.github_kanban_sync.cli close --issue 192 # requires GKS_REQUIRED_CHECKS from live ruleset
```

## Tests

```bash
cd tools && python -m pytest tests/test_gks_*.py -q
```

Covers the two-way flow, linked comments/CI in daemon cycles, restart/backfill,
dedup (poll↔webhook), the fail-closed close gate, conflict severity,
webhook signature rejection, rate-limit/backoff handling and token redaction.
Required-CI closure tests reject missing/failed/pending/skipped/malformed contexts.
Pagination regressions cover later-page issues/PRs/comments/handoffs, >100
check-runs, 304/ETag safety, invalid external Link destinations and rollback
when a later GitHub page fails.
