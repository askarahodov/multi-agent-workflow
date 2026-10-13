"""Parse remote responses.md and build coordinator QA-REQ entries (no LLM)."""
import hashlib
import re

_RSP_RE = re.compile(r"^##\s+(QA-RSP-[A-Za-z0-9._\-]+)\s*$", re.M)
_TASK_RE = re.compile(r"\bt_[0-9a-f]{6,}\b")


def parse_responses(text):
    """Return [{'id','body','sha'}] for each ## QA-RSP-... section."""
    entries = []
    matches = list(_RSP_RE.finditer(text or ""))
    for i, m in enumerate(matches):
        rid = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        entries.append({"id": rid, "body": body, "sha": sha})
    return entries


def _field(body, name):
    m = re.search(rf"^{re.escape(name)}\s*:\s*\**\s*(.+)$", body, re.M | re.I)
    return m.group(1).strip().strip("*`").strip() if m else ""


def classify(entry):
    verdict = _field(entry["body"], "verdict").upper()
    if "APPROV" in verdict or "PASS" in verdict:
        disposition = "ACCEPTED"
    elif "CHANGES_REQUESTED" in verdict or "CHANGES" in verdict:
        disposition = "ACTION_REQUIRED"
    elif "BLOCK" in verdict:
        disposition = "BLOCKED_BY_EVIDENCE"
    elif "NEEDS_APPROVAL" in verdict:
        disposition = "NEEDS_APPROVAL"
    else:
        disposition = "INFORMATIONAL"
    related = sorted(set(_TASK_RE.findall(entry["body"])))
    return disposition, related


def _probe_nonce(body):
    m = re.search(r"probe_nonce\s*:\s*\**\s*`?([A-Za-z0-9\-_.]+)`?", body, re.I)
    return m.group(1) if m else None


def build_request(entry, state, req_id, snapshot_sha, snapshot_id="UNKNOWN"):
    """Deterministic coordinator reply entry appended to requests.md.

    A technical ACK is explicitly separated from recommendation execution: an ACK
    proves READ, never that a recommendation was carried out.
    """
    disposition, related = classify(entry)
    kind = {"ACCEPTED": "ACK", "INFORMATIONAL": "ACK", "BLOCKED_BY_EVIDENCE": "EVIDENCE",
            "ACTION_REQUIRED": "REVIEW_REQUEST", "NEEDS_APPROVAL": "QUESTION"}.get(disposition, "ACK")
    g = state["git"]
    blockers = [t for t in state["tasks"] if t["status"] == "blocked"]
    blocker_ids = ", ".join(f"`{t['id']}`" for t in blockers[:8]) or "NONE"
    gwi = "ESTOP engaged (kanban dispatch paused)" if state["gateway"].get("paused") else "dispatch active"
    nonce = _probe_nonce(entry["body"])
    if nonce:
        kind = "ACK"
        action = "read-only handshake verification; NO Kanban mutations"
    else:
        action = f"read-only ingestion of {entry['id']}; disposition={disposition}; recommendation NOT executed (ACK only)"
    lines = [
        f"## {req_id}",
        f"- in_reply_to: {entry['id']}",
        f"- kind: {kind}",
    ]
    if nonce:
        lines.append(f"- probe_nonce: {nonce}")
    lines += [
        f"- source_snapshot: status/current.md @ {snapshot_id}",
        f"- local_tasks: {', '.join('`'+t+'`' for t in related) or 'NONE'}",
        f"- action_taken: {action}",
        f"- evidence: contact_branch={g.get('contact_branch_sha','UNKNOWN')}; repo_main={g.get('repo_main_sha','UNKNOWN')}; "
        f"snapshot={snapshot_id}; command=bin/qa-sync.sh exit=0; gateway={gwi}",
        "- recommendation_status: ACK_ONLY (no execution claimed)",
        f"- remaining_blockers: {blocker_ids}",
        "- next_checkpoint: next 15-min sync pass (event, not a success promise)",
    ]
    return "\n".join(lines)
