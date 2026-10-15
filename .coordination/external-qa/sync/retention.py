"""P1 retention: compact `index/current.md` + immutable archive COPIES.

First iteration is INDEX-ONLY: archive shards are copies of already-delivered
coordinator blocks; active files are NOT truncated (the cutover is a separate,
reviewed step). `responses.md` is never written here — it belongs to the external QA.

Also exposes the archive-backed delivery lookup so coordinator-side dedup survives
a total loss of the local SQLite ledger.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

REQ_RE = re.compile(r"^##\s+(QA-REQ-[A-Za-z0-9._\-]+)\s*$", re.M)
RSP_RE = re.compile(r"^##\s+(QA-RSP-[A-Za-z0-9._\-]+)\s*$", re.M)
VERSION = 1


def split_blocks(text, pattern):
    """[(id, body)] split on `## <ID>` headings."""
    blocks, matches = [], list(pattern.finditer(text or ""))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((m.group(1), text[m.start():end].strip() + "\n"))
    return blocks


def _field(body, name):
    m = re.search(rf"^\s*-\s*{re.escape(name)}\s*:\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_meta(body):
    return {"kind": _field(body, "kind"), "in_reply_to": _field(body, "in_reply_to")}


def delivered_response_ids(requests_text, requests_index):
    """Response ids already answered — from the ACTIVE remote requests.md AND the
    immutable archive index. This is what keeps dedup correct after truncation or
    after the local SQLite ledger is lost."""
    ids = set(re.findall(r"in_reply_to:\s*(QA-RSP-[A-Za-z0-9._\-]+)", requests_text or ""))
    for rec in (requests_index or {}).values():
        ir = (rec or {}).get("in_reply_to")
        if ir:
            ids.add(ir)
    return ids


def response_field(text, rid, name):
    for bid, body in split_blocks(text, RSP_RE):
        if bid == rid:
            return _field(body, name)
    return ""


def build_archive(requests_text, responses_text, date_str, requests_index, read_remote_file=None):
    """Immutable COPIES of delivered coordinator blocks. Returns (files, index, stats).

    A QA-REQ is archivable when its delivery is proven:
    * kind=ACK            -> its in_reply_to response exists in responses.md
    * kind=REVIEW_REQUEST -> `request: <id>` appears in responses.md (answered)
    
    Write-once guarantee: if the shard path already exists in the index with a
    matching sha256, it is never rewritten. A new shard is only created for
    newly delivered blocks. The shard is append-only - new deliveries are added
    to the existing shard without rewriting history.
    
    Args:
        read_remote_file: Optional callable(rel_path) -> str to read existing shard
                         from the remote repository. If not provided, falls back
                         to local filesystem (for tests).
    """
    index = dict(requests_index or {})
    files, stats = {}, {"new": 0, "already": 0, "skipped": 0}
    rsp_ids = {b for b, _ in split_blocks(responses_text, RSP_RE)}
    answered_reqs = set(re.findall(r"request\s*:\s*(QA-REQ-[A-Za-z0-9._\-]+)", responses_text or ""))
    
    ym = f"{date_str[:4]}-{date_str[4:6]}" if len(date_str) >= 6 else date_str
    shard_path = f"archive/{ym}/requests-{date_str}.md"
    
    # Collect new blocks to archive
    new_shard_blocks = []
    for rid, body in split_blocks(requests_text, REQ_RE):
        kind = _field(body, "kind").upper()
        in_reply = _field(body, "in_reply_to")
        delivered = (kind == "ACK" and in_reply in rsp_ids) or \
                    (kind == "REVIEW_REQUEST" and rid in answered_reqs)
        if not delivered:
            stats["skipped"] += 1
            continue
        digest = _sha(body)
        # Check if already in index with same hash (write-once)
        existing = index.get(rid)
        if existing and existing.get("sha256") == digest:
            stats["already"] += 1
            continue
        # New delivery - add to index and shard
        index[rid] = {"path": shard_path,
                      "sha256": digest, "date": date_str, "kind": kind or "UNKNOWN",
                      "in_reply_to": in_reply or None}
        stats["new"] += 1
        new_shard_blocks.append((rid, body))
    
    # Write shard: append-only - read existing content from remote
    if new_shard_blocks:
        existing_shard_content = ""
        
        # First check if shard already exists in files (from a previous build_archive call in same run)
        if shard_path in files:
            existing_shard_content = files[shard_path]
        # Otherwise try to read from remote repository
        elif read_remote_file:
            try:
                remote_content = read_remote_file(shard_path)
                if remote_content:
                    existing_shard_content = remote_content
            except Exception:
                pass
        # Fallback to local filesystem (for tests without remote)
        else:
            import pathlib
            try:
                for base in [".worktrees/coord-external-qa", ".coordination/external-qa", "."]:
                    p = pathlib.Path(base + "/archive/" + (f"{date_str[:4]}-{date_str[4:6]}" if len(date_str) >= 6 else date_str) + f"/requests-{date_str}.md")
                    if p.exists():
                        with open(p, "r", encoding="utf-8") as f:
                            existing_shard_content = f.read()
                        break
            except Exception:
                pass
        
        if existing_shard_content:
            # Append new blocks to existing content (preserve header if present)
            if existing_shard_content.startswith("# Archive"):
                header_end = existing_shard_content.find("\n\n")
                if header_end > 0:
                    header = existing_shard_content[:header_end + 2]
                    rest = existing_shard_content[header_end + 2:]
                    new_body = "\n\n".join(b for _, b in new_shard_blocks)
                    files[shard_path] = header + rest + ("\n\n" + new_body if rest else new_body)
                else:
                    files[shard_path] = existing_shard_content + "\n\n" + "\n\n".join(b for _, b in new_shard_blocks)
            else:
                files[shard_path] = existing_shard_content + "\n\n" + "\n\n".join(b for _, b in new_shard_blocks)
        else:
            # First time creating this shard
            files[shard_path] = "# Archive — delivered coordinator QA-REQ blocks (immutable, append-only)\n\n" + \
                                "\n\n".join(b for _, b in new_shard_blocks)
    
    files["archive/requests-index.json"] = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return files, index, stats


def build_index(state, snapshot_id, *, requests_text, responses_text, requests_index, contact_sha):
    """Compact queue for the external reviewer: only NEW unanswered requests and
    OPEN cases. No ACK_ONLY, no old PASS, no full history."""
    rsp_verdicts = {}
    for rid, body in split_blocks(responses_text, RSP_RE):
        v = re.sub(r"[\*`]", "", _field(body, "verdict") or "").strip()
        rsp_verdicts[rid] = v.upper()
    answered_reqs = set(re.findall(r"request\s*:\s*(QA-REQ-[A-Za-z0-9._\-]+)", responses_text or ""))
    rsp_ids = set(rsp_verdicts)

    new_reqs = []
    for rid, body in split_blocks(requests_text, REQ_RE):
        kind = _field(body, "kind").upper()
        if kind != "REVIEW_REQUEST" or rid in answered_reqs:
            continue
        new_reqs.append({
            "req_id": rid, "kind": kind,
            "task_id": (_field(body, "local_tasks") or "NONE")[:60],
            "evidence": (_field(body, "evidence") or "-")[:80],
            "in_reply_to": _field(body, "in_reply_to") or "-",
        })

    # OPEN cases: responses with an actionable verdict (their defect stays open until
    # independent verification, even after the ACK).
    open_cases = []
    for rid, verdict in rsp_verdicts.items():
        if not any(k in verdict for k in ("CHANGES_REQUESTED", "ACTION_REQUIRED", "BLOCKED")):
            continue
        tasks = sorted(set(re.findall(r"\bt_[0-9a-f]{6,}\b", next(
            (b for i, b in split_blocks(responses_text, RSP_RE) if i == rid), ""))))
        open_cases.append({
            "case_id": f"QA-CAS-{rid.replace('QA-RSP-', '')[:32]}",
            "owner": "@orchestrator", "task_id": ", ".join(tasks) or "NONE",
            "verdict": (verdict.split()[0] if verdict else "OPEN"),
            "next_action": "publish REVIEW_REQUEST with diff/SHA/tests",
            "evidence_ref": f"responses.md#{rid}",
        })

    lines = [
        "# Активные вопросы QA",
        f"- snapshot_id: {snapshot_id}",
        f"- generated_at_utc: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- status_source: status/current.md @ {snapshot_id}",
        f"- main_sha: {state['git'].get('repo_main_sha', 'UNKNOWN')}",
        f"- inbox_revision: {contact_sha}",
        f"- total_unanswered: {len(new_reqs)}",
        f"- total_open_cases: {len(open_cases)}",
        f"- retention_version: {VERSION}",
        "",
        "## Новые QA-запросы (только без независимого ответа)",
        "| req_id | kind | in_reply_to | task_id | evidence_ref |",
        "|---|---|---|---|---|",
    ]
    for r in new_reqs:
        lines.append(f"| {r['req_id']} | {r['kind']} | {r['in_reply_to']} | {r['task_id']} | {r['evidence']} |")
    if not new_reqs:
        lines.append("| — | — | — | — | — |")
    lines += ["", "## Открытые вопросы/блокеры (не весь transcript)",
              "| case_id | owner | task_id | verdict | next_action | evidence_ref |",
              "|---|---|---|---|---|---|"]
    for c in open_cases:
        lines.append(f"| {c['case_id']} | {c['owner']} | {c['task_id']} | {c['verdict']} | "
                     f"{c['next_action']} | {c['evidence_ref']} |")
    if not open_cases:
        lines.append("| — | — | — | — | — | — |")
    lines += ["", "## Недавно решено",
              "- см. `archive/requests-index.json` (immutable, только для ручного аудита)", ""]
    return "\n".join(lines), open_cases, new_reqs
