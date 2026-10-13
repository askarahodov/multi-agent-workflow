# QA synchronizer (local Kanban ↔ external QA ChatGPT)

Implements `.coordination/external-qa/AUTOMATION_PROTOCOL.md` (v1). Runs on the
coordinator host, publishes **only** coordinator-owned files to
`origin/coord/external-qa`, and never touches ChatGPT-owned `responses.md`.

## What it does (every 15 min, no LLM)

1. Collects current state deterministically: local Kanban boards, git/worktrees,
   gateway log counters, running workers, `gh` CI, provider profile names.
2. Renders `.coordination/external-qa/status/current.md` (YAML head + 7 sections).
3. Reads the **remote** `responses.md`, extracts `QA-RSP-*` sections, and dedups by
   id **and** content SHA against a durable store. New, unanswered responses get
   exactly one coordinator entry (`QA-REQ-*` with `in_reply_to`) appended to `requests.md`.
4. Publishes via a lock-guarded, freshly-fetched temporary worktree; push is never
   forced; success is asserted against the **remote** (ls-remote + `git show`).
5. Skips commit/push when the snapshot substance and requests are unchanged.

## Layout

```
~/.hermes/qa-sync/
├── qasync/            config, store, collect, render, respond, publish, main
├── qa_sync.py         entry point
├── bin/qa-sync.sh     cron wrapper
├── tests/             acceptance tests (5 owner scenarios + invariants)
├── state.db           durable: processed_responses, kv, req_seq
└── logs/cron.log
publish-wt/            ephemeral publish worktree (recreated per pass, removed after)
```

## Run

```
python3 ~/.hermes/qa-sync/qa_sync.py            # one live pass
python3 ~/.hermes/qa-sync/qa_sync.py --dry-run  # collect + build, no commit/push
python3 ~/.hermes/qa-sync/qa_sync.py --responses-file FILE  # test a local responses.md
QASYNC_BRANCH=some-branch ...                   # target another branch (tests)
```

Cron (installed): `*/15 * * * * ~/.hermes/qa-sync/bin/qa-sync.sh >> ~/.hermes/qa-sync/logs/cron.log 2>&1`

## Invariants

- 0 force-push; 0 edits to `responses.md`; 0 secrets (sanitized); 0 GitHub Issues;
  0 interference with active `wt/t_*` worktrees (dedicated worktree only).
- Single writer: lock file with stale (dead-pid / TTL) recovery.
- Non-fast-forward: bounded refetch + replay of coordinator-owned files only.

## Deliberate limits

- `ci_latest` in the snapshot reports the latest run on `main` (no run id/url) so the
  synchronizer's own pushes cannot create a self-referential commit loop.
- The cron never calls an LLM. The coordinator (owner) is engaged only on a new
  substantive QA response, out of band of this job.
