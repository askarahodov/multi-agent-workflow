# Evidence — github-kanban-sync E2E + board-level idempotency (Issue #192), 2026-10-30

Environment: real GitHub API (token from `gh auth token`, keyring), real local
Kanban board `~/.hermes/kanban/boards/me/kanban.db`, real card `t_02d18f3e`,
linked to Issue #192. Persistent ledger: `coordination-sync.db`.

Command (from the worktree root):

```
GKS_REPO_ROOT=$PWD GKS_E2E_WRITE=1 python3 tools/github_kanban_sync/e2e_probe.py
```

`GKS_E2E_WRITE=1` enables the real Kanban comment delivery and the single real
GitHub publish; without it the probe is read-only. The ledger used is the
**persistent** default (`~/.hermes/kanban/boards/me/coordination-sync.db`), not a
throwaway scratch, so the idempotency below is demonstrated on the real board.

## 0. Duplicate cleanup (pre-existing pollution)

The previous E2E runs had appended **duplicate** ingest comments to `t_02d18f3e`
(ids 201/203 identical `handoff`, 202/204 identical `comment`) because the old
ingest marker carried only `correlation_id`, not the `source_event_id`, and
`deliver` appended unconditionally.

```
# python3 -m tools.github_kanban_sync.cli dedupe --task t_02d18f3e        (keep one per body)
{"task_id": "t_02d18f3e", "duplicates_removed": 2, "events_pruned": 2, "kept": [201, 202], "removed": [203, 204]}

# python3 -m tools.github_kanban_sync.cli dedupe --task t_02d18f3e --all   (clean re-delivery)
{"task_id": "t_02d18f3e", "duplicates_removed": 2, "events_pruned": 2, "kept": [], "removed": [201, 202]}
```

After cleanup the card had 0 ingest comments; the fixed ingest below re-delivered
the two real comments **once each** with the new `event=<source_event_id>` marker.

## 1. GitHub → Kanban ingest + board-level idempotency (persistent ledger)

```
persistent ledger: /home/askarahodov/.hermes/kanban/boards/me/coordination-sync.db (existed=False)

===== board ingest comments (before) =====
{"count": 0, "ids": [], "markers": []}

===== phase 1 — ingest comments #192 (persistent ledger) =====
{"feed": "comments:192", "new_events": 2, "cursor": "2026-10-30T09:08:47Z"}

===== board ingest comments (after phase 1) =====
{"count": 2, "ids": [214, 215],
 "markers": [
   "<!-- gks:v1 id=issue:192 event=askarahodov/multi-agent-workflow:issue_comment:192:6519063860 channel=ingest -->",
   "<!-- gks:v1 id=issue:192 event=askarahodov/multi-agent-workflow:issue_comment:192:6519142157 channel=ingest -->"]}

===== phase 2 — re-ingest, SAME ledger (expect new_events 0) =====
{"feed": "comments:192", "new_events": 0, "cursor": "2026-10-30T09:08:47Z"}

===== board ingest comments (after phase 2, expect unchanged) =====
{"count": 2, "ids": [214, 215], ...unchanged...}
```

Both real comments on Issue #192 (comment ids `6519063860`, `6519142157`) were
delivered to the owning card `t_02d18f3e` exactly once; re-ingesting with the same
ledger is a no-op.

## 2. Board-level guard survives a journal reset

Phase 3 points a **fresh, empty** ledger (the runbook §9 "полный сброс" /
delete-the-journal case) at the **same real board**. The event is new to the fresh
ledger, so delivery is attempted — but the board marker already carries the same
`source_event_id`, so nothing is appended:

```
===== phase 3 — ingest with FRESH ledger after journal reset =====
{"feed": "comments:192", "new_events": 2, "cursor": "2026-10-30T09:08:47Z"}

===== phase 3 — delivery journal (expect status duplicate) =====
[{"source_event_id": "...:issue_comment:192:6519142157", "channel": "kanban",
  "target": "t_02d18f3e", "status": "duplicate", ...,
  "detail": "issue #192 -> t_02d18f3e (already on board)"},
 {"source_event_id": "...:issue_comment:192:6519063860", ..., "status": "duplicate", ...}]

===== board ingest comments (after phase 3, expect UNCHANGED) =====
{"count": 2, "ids": [214, 215], ...unchanged...}
```

A journal reset no longer re-duplicates the board. A second full probe invocation
with the same persistent ledger is likewise all-zero (`new_events: 0`) and leaves
the board at ids 214/215.

## 3. Kanban → GitHub publish (unchanged, one versioned comment)

```
===== phase 4 — publish card back to linked Issue #192 =====
{"task_id": "t_02d18f3e", "status": "updated", "issue": 192, "rev": 4, "comment_id": 6519184408}

===== issue #192 total comments after publish (expect 3, 1 publish) =====
{"comments": 3}
```

The publish comment is updated **in place** (`comment_id 6519184408`, the same id
as before) — no publish duplicate. `rev` is monotonically continued from the live
marker (3 → 4) instead of restarting at 1 after a ledger reset; a repeat publish
with unchanged content is a no-op (`status: unchanged`).

## 4. Final live state

```
$ python3 -c "..."   # read-only board probe
t_02d18f3e comments total=5 ingest=2
  ingest id=214  marker=<!-- gks:v1 id=issue:192 event=...:6519063860 channel=ingest -->
  ingest id=215  marker=<!-- gks:v1 id=issue:192 event=...:6519142157 channel=ingest -->
duplicate ingest groups on board: []
```

* GitHub Issue #192: **OPEN**, 3 comments total, exactly 1 sync publish comment.
* Card `t_02d18f3e`: 2 ingest comments (one per real GitHub comment), no duplicates.

## 5. Tests

```
$ python3 -m pytest tools/tests -q
140 passed
$ python3 -m pytest tools/tests/test_gks_*.py -q
67 passed
```

New coverage for this rework: marker embeds `source_event_id`; fresh-ledger
re-ingest does not duplicate the board (delivery `duplicate`); `dedupe` removes
duplicate ingest comments (and is idempotent); `has_comment_marker` matches
literally (not as a SQL `LIKE` pattern); publish recovers the revision after a
ledger reset.
