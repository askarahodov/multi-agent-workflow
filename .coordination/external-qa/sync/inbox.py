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
ACK = INBOX_DIR / "ack.jsonl"


def _ensure_dir():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)


def _read_acks():
    if not ACK.exists():
        return []
    out = []
    for line in ACK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


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
    verdicts = rec.get("new_response_verdicts") or {}
    if new_resp:
        vs = sorted({(verdicts.get(i) or "").split()[0] for i in new_resp if verdicts.get(i)})
        tag = f" ({'/'.join(vs)})" if vs else ""
        bits.append(f"{len(new_resp)} QA-RSP{tag}")
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
        "new_response_verdicts": summary.get("new_response_verdicts") or {},
        "generated_requests": summary.get("generated_requests") or [],
        "new_entries_to_publish": summary.get("new_entries_to_publish") or [],
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

    Only events that concern the EXTERNAL QA channel qualify. A routine publish
    driven by internal Kanban churn (status_changed=true) is deliberately NOT
    actionable: on an active board that fires every pass and causes alert
    fatigue. We wake on:
      - a fetch failure (the channel is unreachable),
      - a new QA response (QA-RSP) or a generated QA-REQ,
      - new coordinator entries actually appended to requests.md.
    """
    if not rec:
        return False
    if rec.get("fetch_ok") is False:
        return True
    if rec.get("new_responses") or rec.get("generated_requests"):
        return True
    if rec.get("new_entries_to_publish"):
        return True
    return False


def unread():
    """Records the coordinator has not acknowledged yet."""
    cur = _cursor_seq()
    return [r for r in _read_journal() if r.get("seq", 0) > cur]


def mark_read(seq=None, source="cli"):
    """Advance the cursor and append an ACK receipt.

    The receipt (inbox/ack.jsonl) is the audit trail: it records WHEN the
    coordinator consumed which records and via which source, so the data ->
    consume chain is provable and its latency is measurable.
    """
    _ensure_dir()
    recs = _read_journal()
    prev = _cursor_seq()
    if seq is None:
        seq = recs[-1].get("seq", 0) if recs else 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    CURSOR.write_text(json.dumps({"seq": int(seq), "ts": now},
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        with open(ACK, "a", encoding="utf-8") as f:
            f.write(json.dumps({"acked_at": now, "from_seq": prev, "to_seq": int(seq),
                                "records": max(0, int(seq) - prev), "source": source},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
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
            vs = r.get("new_response_verdicts") or {}
            items = [f"`{i}` → {vs.get(i) or '—'}" for i in r["new_responses"]]
            lines.append(f"- new_responses: {'; '.join(items)}")
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


def read(consume=False, source="cli"):
    """Return unread records as (records, text). consume=True advances the cursor."""
    recs = unread()
    text = _render_md(recs)
    if consume and recs:
        mark_read(recs[-1].get("seq"), source=source)
    return recs, text


def receipt(limit=12):
    """Timeline proving the data -> consume chain with per-record latency.

    For each of the last `limit` journal records, find the first ACK that covered
    it and compute the lag (record produced -> acknowledged). This is how you
    verify the coordinator actually RECEIVED the data and WHEN.
    """
    recs = _read_journal()
    acks = _read_acks()
    cursor_seq_now = _cursor_seq()
    lines = ["# QA-sync receipt — data → consume chain", ""]
    lines.append(f"records={len(recs)} acks={len(acks)} cursor_seq={cursor_seq_now} "
                 f"unread={len([r for r in recs if r.get('seq',0) > cursor_seq_now])}")
    lines.append("")
    lines.append("| seq | produced_at (UTC) | acked_at (UTC) | lag_s | source | headline |")
    lines.append("|---|---|---|---|---|---|")
    for r in recs[-limit:]:
        seq = r.get("seq")
        ts = r.get("ts")
        t_rec = _parse_ts(ts)
        ack = next((a for a in acks if a.get("to_seq", 0) >= seq and a.get("from_seq", 0) < seq), None)
        if ack:
            acked_at = ack.get("acked_at")
            t_ack = _parse_ts(acked_at)
            lag = int((t_ack - t_rec).total_seconds()) if (t_ack and t_rec) else "?"
            src = ack.get("source", "?")
        else:
            acked_at, lag, src = "(unread)", "-", "-"
        lines.append(f"| {seq} | {ts} | {acked_at} | {lag} | {src} | {_headline(r)} |")
    if acks:
        lines.append("")
        lines.append(f"last ack: {acks[-1].get('acked_at')} source={acks[-1].get('source')} "
                     f"cover={acks[-1].get('from_seq')}..{acks[-1].get('to_seq')}")
    return "\n".join(lines)


def main(argv=None):
    """CLI: `python3 -m qasync.inbox` prints changes.

    Flags:
      --peek      print unread WITHOUT advancing the cursor (default)
      --read      print unread AND advance the cursor (records an ACK receipt)
      --status    print cursor + journal size only
      --receipt   print the data->consume audit trail with per-record lag
      --source X  label to record on the ACK (default: cli)
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--receipt" in argv:
        print(receipt())
        return 0
    if "--status" in argv:
        recs = _read_journal()
        cur = _cursor_seq()
        print(json.dumps({
            "journal_records": len(recs),
            "cursor_seq": cur,
            "unread": len([r for r in recs if r.get("seq", 0) > cur]),
            "newest": _headline(recs[-1]) if recs else None,
            "last_ack": (_read_acks()[-1] if _read_acks() else None),
        }, ensure_ascii=False, indent=2))
        return 0
    source = "cli"
    if "--source" in argv:
        i = argv.index("--source")
        if i + 1 < len(argv):
            source = argv[i + 1]
    consume = "--read" in argv
    recs, text = read(consume=consume, source=source)
    print(text)
    if recs and not consume:
        print(f"\n(peek: {len(recs)} unread, cursor NOT advanced — use --read to ack)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
