"""Local awareness inbox for the QA sync loop.

The cron loop already runs autonomously and publishes to the remote
`coord/external-qa` branch. What it did NOT do was tell the coordinator (a
separate agent session) what changed — the coordinator only saw changes when it
manually read the remote files.

This module closes that gap *without* any external dependency and without
touching another profile: every pass appends a compact, human-inspectable record
to a local append-only journal, and the coordinator reads "what's new since I
last looked" via a durable cursor.

Layout (all under SERVICE_DIR/inbox):
    changes.jsonl   append-only journal, one JSON object per line
    cursor.json     {"seq": N} — the last record the coordinator acknowledged
    last-changes.json   the newest record, for a one-shot read
    LAST.md         human-readable rendering of the newest record

Nothing here is published to the remote: it is local state, like the SQLite
ledger. The module is still shipped in the remote sync/ dir for transparency.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config as C

INBOX_DIR = C.SERVICE_DIR / "inbox"
JOURNAL = INBOX_DIR / "changes.jsonl"
CURSOR = INBOX_DIR / "cursor.json"
LAST = INBOX_DIR / "last-changes.json"
LAST_MD = INBOX_DIR / "LAST.md"
ALERT = INBOX_DIR / "ALERT.json"


def _ensure_dir():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)


def _read_journal():
    if not JOURNAL.exists():
        return []
    records = []
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # a torn line must never break awareness
    return records


def _cursor_seq():
    if not CURSOR.exists():
        return 0
    try:
        return int(json.loads(CURSOR.read_text(encoding="utf-8")).get("seq", 0))
    except (ValueError, OSError):
        return 0


def _headline(rec):
    """One-line, action-oriented summary of a change record."""
    action = (rec.get("action") or "?").strip()
    bits = []
    new_resp = rec.get("new_responses") or []
    gen_req = rec.get("generated_requests") or []
    if new_resp:
        bits.append(f"{len(new_resp)} QA-RSP")
    if gen_req:
        bits.append(f"{len(gen_req)} QA-REQ")
    ret = rec.get("retention") or {}
    if ret.get("archive_new"):
        bits.append(f"archive+{ret['archive_new']}")
    if ret.get("open_cases"):
        bits.append(f"{ret['open_cases']} open")
    tail = f" [{', '.join(bits)}]" if bits else ""
    return f"{action}{tail}"


def record(summary, state=None):
    """Append one compact change record. Called at the end of every pass.

    Returns the record dict (also the newest entry in the journal).
    """
    _ensure_dir()
    prev = _read_journal()
    seq = (prev[-1].get("seq", 0) + 1) if prev else 1
    rec = {
        "seq": seq,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collected_at": summary.get("collected_at"),
        "action": summary.get("action"),
        "snapshot_id": None,
        "status_substance": summary.get("status_substance"),
        "status_changed": summary.get("status_changed"),
        "remote_sha": (summary.get("publish") or {}).get("remote_sha"),
        "changed": (summary.get("publish") or {}).get("changed"),
        "new_responses": summary.get("new_responses") or [],
        "generated_requests": summary.get("generated_requests") or [],
        "outbox_entries": summary.get("outbox_entries") or [],
        "retention": summary.get("retention"),
        "fetch_ok": summary.get("fetch_ok"),
        "responses_read_error": summary.get("responses_read_error"),
        "legacy_main_sha": None,
        "legacy_contact_sha": None,
    }
    if state:
        g = state.get("git", {})
        rec["main_sha"] = g.get("repo_main_sha")
        rec["contact_sha"] = g.get("contact_branch_sha")
    # append-only: single writer (the cron), one JSON line per pass
    line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    LAST.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LAST_MD.write_text(_render_md([rec]) + "\n", encoding="utf-8")
    # ALERT.json is rewritten ONLY on an actionable event — it is the cheap
    # deterministic gate the scheduler monitors, so quiet skip-passes never
    # wake the coordinator (and never spend an LLM turn).
    if actionable(rec):
        ALERT.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rec


def actionable(rec):
    """A record worth waking the coordinator for.

    Quiet skip-passes are NOT actionable. We wake on: a real publish, a new QA
    response, a generated request, or a fetch failure (something the coordinator
    must know about).
    """
    if not rec:
        return False
    if rec.get("fetch_ok") is False:
        return True
    if rec.get("new_responses") or rec.get("generated_requests"):
        return True
    action = (rec.get("action") or "")
    if action.startswith("PUBLISHED") and rec.get("status_changed"):
        return True
    return False


def unread():
    """Records the coordinator has not acknowledged yet."""
    cur = _cursor_seq()
    return [r for r in _read_journal() if r.get("seq", 0) > cur]


def mark_read(seq=None):
    """Advance the cursor. Defaults to the newest record's seq."""
    _ensure_dir()
    recs = _read_journal()
    if seq is None:
        seq = recs[-1].get("seq", 0) if recs else 0
    CURSOR.write_text(json.dumps({"seq": int(seq),
                                  "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    return int(seq)


def _render_md(records):
    if not records:
        return "# QA-sync inbox\n\n- нет новых изменений\n"
    lines = ["# QA-sync inbox — изменения с прошлого прочтения", ""]
    for r in records:
        lines.append(f"## #{r.get('seq')} — {_headline(r)}")
        lines.append(f"- collected_at: {r.get('collected_at')}")
        lines.append(f"- action: {r.get('action')}")
        lines.append(f"- status_changed: {r.get('status_changed')} "
                     f"(substance {str(r.get('status_substance'))[:12]}…)")
        if r.get("remote_sha"):
            lines.append(f"- remote_sha: {r['remote_sha']}")
        if r.get("changed"):
            lines.append(f"- changed_files: {', '.join(r['changed'])}")
        if r.get("new_responses"):
            lines.append(f"- new_responses: {', '.join(r['new_responses'])}")
        if r.get("generated_requests"):
            lines.append(f"- generated_requests: {', '.join(r['generated_requests'])}")
        if r.get("outbox_entries"):
            lines.append(f"- outbox_pending: {', '.join(r['outbox_entries'])}")
        if r.get("retention"):
            ret = r["retention"]
            lines.append(f"- retention: archive_new={ret.get('archive_new')} "
                         f"kept={ret.get('archive_kept')} open_cases={ret.get('open_cases')} "
                         f"not_delivered={ret.get('not_delivered')}")
        if r.get("fetch_ok") is False:
            lines.append(f"- WARN: fetch failed: {r.get('responses_read_error') or 'unknown'}")
        lines.append("")
    return "\n".join(lines)


def read(consume=False):
    """Return unread records as (records, text). consume=True advances the cursor."""
    recs = unread()
    text = _render_md(recs)
    if consume and recs:
        mark_read(recs[-1].get("seq"))
    return recs, text


def main(argv=None):
    """CLI: `python3 -m qasync.inbox` prints changes.

    Flags:
      --peek    print unread WITHOUT advancing the cursor (default)
      --read    print unread AND advance the cursor to the newest
      --status  print cursor + journal size only
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--status" in argv:
        recs = _read_journal()
        cur = _cursor_seq()
        print(json.dumps({
            "journal_records": len(recs),
            "cursor_seq": cur,
            "unread": len([r for r in recs if r.get("seq", 0) > cur]),
            "newest": _headline(recs[-1]) if recs else None,
        }, ensure_ascii=False, indent=2))
        return 0
    consume = "--read" in argv
    recs, text = read(consume=consume)
    print(text)
    if recs and not consume:
        print(f"\n(peek: {len(recs)} unread, cursor NOT advanced — use --read to ack)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
