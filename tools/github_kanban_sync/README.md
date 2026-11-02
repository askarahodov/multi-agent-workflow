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
* **Kanban → GitHub** — publishes card status/assignee/blocker/branch/PR/evidence
  as a **versioned, deduplicated** comment on the *linked* Issue. Closes an Issue
  only on confirmed merge + required CI + acceptance evidence — never on `done`
  alone.
* **Conflicts** — exact-path / sensitive-dir overlap, ownership reservations and
  stale `main`, reported before dispatch and before merge. Observation only: no
  rebase/reset/merge/delete of any worktree.
* **Transport** — ETag/cursor incremental poll by default; a signature-verified
  webhook is an optional accelerator. Both converge on one `source_event_id`.
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
python -m tools.github_kanban_sync.cli sync                 # ingest + publish (one cycle)
python -m tools.github_kanban_sync.cli daemon               # autostart: run the loop
python -m tools.github_kanban_sync.cli daemon --once        # one cycle, then exit
python -m tools.github_kanban_sync.cli daemon --stop        # stop the running daemon
python -m tools.github_kanban_sync.cli bind --issue 192 --task t_02d18f3e
python -m tools.github_kanban_sync.cli dedupe --task t_02d18f3e   # remove duplicate ingest comments
python -m tools.github_kanban_sync.cli conflict --live-main "$(git rev-parse origin/main)"
python -m tools.github_kanban_sync.cli close --issue 192
```

## Tests

```bash
cd tools && python -m pytest tests/test_gks_*.py -q
```

Covers the two-way flow, dedup (poll↔webhook), the close gate, conflict severity,
webhook signature rejection, rate-limit/backoff handling and token redaction.
