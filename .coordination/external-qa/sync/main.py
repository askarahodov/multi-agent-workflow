"""One synchronization pass: collect -> diff QA responses -> publish -> verify."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

from . import collect, config as C, inbox, publish, render, respond, retention, store

SYNC_MODULES = ["config.py", "store.py", "collect.py", "render.py", "respond.py",
                "publish.py", "retention.py", "inbox.py", "main.py"]


def _utc_snapshot_id():
    return "UTC-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fetch_contact():
    r = subprocess.run(["git", "-C", str(C.REPO), "fetch", "origin", C.BRANCH],
                       capture_output=True, text=True, timeout=180)
    return r.returncode == 0, r.stderr.strip()[:200]


def _read_remote_responses():
    r = subprocess.run(
        ["git", "-C", str(C.REPO), "show", f"origin/{C.BRANCH}:{C.CONTACT_REL}/responses.md"],
        capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        return None, r.stderr.strip()[:200]
    return r.stdout, None


def _read_remote_requests():
    return _read_remote_file(f"{C.CONTACT_REL}/requests.md")


def _read_remote_file(rel):
    r = subprocess.run(
        ["git", "-C", str(C.REPO), "show", f"origin/{C.BRANCH}:{rel}"],
        capture_output=True, text=True, timeout=90)
    return r.stdout if r.returncode == 0 else ""


def _archive_index():
    import json as _json
    raw = _read_remote_file(f"{C.CONTACT_REL}/archive/requests-index.json")
    try:
        return _json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def _outbox_entries():
    """Coordinator-authored entries (e.g. REVIEW_REQUEST with diff/SHA/tests) dropped
    as .md files in the local outbox. Appended once; publish dedups by heading and
    in_reply_to, so a leftover file never duplicates."""
    d = C.SERVICE_DIR / "outbox"
    if not d.exists():
        return []
    return [p.read_text(encoding="utf-8").strip() for p in sorted(d.glob("*.md"))]


def _is_new_entry(entry, base):
    """True when this coordinator entry is not already on the remote requests.md.

    Dedup by ID **and kind** (per the retention protocol): the heading always
    dedupes, but the broader `in_reply_to` rule applies ONLY to a technical ACK —
    a later REVIEW_REQUEST for the same response is a different, legitimate entry.
    """
    lines = entry.splitlines()
    head = lines[0].strip() if lines else ""
    if head and head in base:
        return False
    kind = (re.search(r"^\s*-\s*kind\s*:\s*(\S+)", entry, re.M) or [None, ""])[1] \
        if re.search(r"^\s*-\s*kind\s*:\s*(\S+)", entry, re.M) else ""
    if kind.upper() == "ACK":
        m = re.search(r"^\s*-\s*in_reply_to\s*:\s*(\S+)", entry, re.M)
        if m and f"in_reply_to: {m.group(1)}" in base:
            return False
    return True


def _sync_code():
    out = {}
    for name in SYNC_MODULES:
        p = C.SERVICE_DIR / "qasync" / name
        if p.exists():
            out[f"{C.CONTACT_REL}/sync/{name}"] = p.read_text(encoding="utf-8")
    entry = C.SERVICE_DIR / "qa_sync.py"
    if entry.exists():
        out[f"{C.CONTACT_REL}/sync/qa_sync.py"] = entry.read_text(encoding="utf-8")
    readme = C.SERVICE_DIR / "README.md"
    if readme.exists():
        out[f"{C.CONTACT_REL}/sync/README.md"] = readme.read_text(encoding="utf-8")
    tests = C.SERVICE_DIR / "tests" / "test_acceptance.py"
    if tests.exists():
        out[f"{C.CONTACT_REL}/sync/tests_test_acceptance.py"] = tests.read_text(encoding="utf-8")
    return out


def run_once(args):
    con = store.connect()
    summary = {"collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    fetched, ferr = _fetch_contact()
    summary["fetch_ok"] = fetched
    if not fetched:
        summary["fetch_error"] = ferr

    state = collect.collect_all(con)

    # ---- QA responses ----
    if args.responses_file:
        resp_text = open(args.responses_file, encoding="utf-8").read()
        resp_err = None
    else:
        resp_text, resp_err = _read_remote_responses()
    if resp_err:
        summary["responses_read_error"] = resp_err

    entries = respond.parse_responses(resp_text or "")
    summary["responses_on_remote"] = [e["id"] for e in entries]

    # Exactly-once ACK, robust to a changed response body AND to a lost local ledger:
    # a response is answered if its id already appears as `in_reply_to` in the PUBLISHED
    # remote requests.md OR in the immutable archive index.
    requests_text = _read_remote_requests()
    archive_index = _archive_index()
    answered = retention.delivered_response_ids(requests_text, archive_index)
    # A coordinator-authored outbox entry (e.g. REVIEW_REQUEST) already replies to its
    # target response, so no automated ACK may be generated for the same response.
    outbox = _outbox_entries()
    answered |= set(re.findall(r"in_reply_to:\s*(QA-RSP-[A-Za-z0-9._\-]+)", "\n".join(outbox)))
    new_entries = []
    for e in entries:
        if e["id"] in answered:
            continue  # already answered on the remote; history is preserved, never re-sent
        if re.search(r"request:\s*NONE", e["body"], re.I):
            store.mark_response(con, e["id"], e["sha"], "SEEDED")  # informational bootstrap
            continue
        st = store.response_state(con, e["id"])
        if st and st[0] == e["sha"]:
            continue  # already processed with identical content
        new_entries.append(e)
    store.set_kv(con, "resp_seeded", "1")
    summary["answered_response_ids"] = sorted(answered)

    snapshot_id = _utc_snapshot_id()
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    req_entries = []
    for e in new_entries[: C.MAX_REQ_PER_PASS]:
        seq = store.next_seq(con, date_str)
        req_id = f"QA-REQ-{date_str}-{seq:03d}"
        text = respond.build_request(e, state, req_id, state["git"].get("repo_main_sha", "UNKNOWN"),
                                     snapshot_id=snapshot_id)
        req_entries.append({"id": req_id, "text": text, "response_id": e["id"], "sha": e["sha"]})
    # Only entries NOT already on the remote count as new work — a leftover outbox
    # file (or a re-run) must not force a commit on every pass.
    append_new = [e for e in ([r["text"] for r in req_entries] + outbox)
                  if _is_new_entry(e, requests_text)]
    summary["new_responses"] = [e["id"] for e in new_entries]
    summary["generated_requests"] = [r["id"] for r in req_entries]
    summary["outbox_entries"] = [b.splitlines()[0].strip() for b in outbox if b.splitlines()]
    summary["new_entries_to_publish"] = [e.splitlines()[0].strip() for e in append_new if e.splitlines()]

    # ---- retention: compact index + immutable archive COPIES (active files untouched) ----
    verdicts = [(e["id"], respond._field(e["body"], "verdict")) for e in entries]
    index_md, open_cases, _new_reqs = retention.build_index(
        state, snapshot_id, requests_text=requests_text, responses_text=resp_text or "",
        requests_index=archive_index, contact_sha=state["git"].get("contact_branch_sha", "UNKNOWN"))
    archive_files, _new_archive_index, arch_stats = retention.build_archive(
        requests_text, resp_text or "", date_str, archive_index, read_remote_file=_read_remote_file)
    summary["retention"] = {"archive_new": arch_stats["new"], "archive_kept": arch_stats["already"],
                            "open_cases": len(open_cases), "not_delivered": arch_stats["skipped"]}

    # ---- render status + dashboard from the SAME snapshot ----
    prev_pub = store.get_kv(con, "last_publish_remote_sha", "NONE")
    ps = prev_pub[:12] if prev_pub != "NONE" else "NONE"
    body, sub_status = render.render(state, snapshot_id, publish_state=ps)
    dashboard = render.render_dashboard(state, snapshot_id, publish_state=ps,
                                        qa_verdicts=verdicts, open_cases=open_cases)
    extra_files = {
        f"{C.CONTACT_REL}/QA_DASHBOARD.md": dashboard,
        f"{C.CONTACT_REL}/index/current.md": index_md,
    }
    for rel, content in archive_files.items():
        extra_files[f"{C.CONTACT_REL}/{rel}"] = content
    sync_files = _sync_code()
    extra_files.update(sync_files)
    # Hash ONLY the stable inputs: the code and the immutable archive shards. The
    # dashboard/index are volatile (their own timestamps) and are normalized above;
    # folding their raw bytes into the hash made every pass look like a change.
    code_hash = hashlib.sha256(
        json.dumps(sorted(sync_files.items()), ensure_ascii=False).encode("utf-8")).hexdigest()
    archive_hash = hashlib.sha256(
        render.normalize(json.dumps(sorted(archive_files.items()), ensure_ascii=False))
        .encode("utf-8")).hexdigest()
    substance = hashlib.sha256(
        (sub_status + render.normalize(dashboard) + render.normalize(index_md)
         + archive_hash + code_hash).encode("utf-8")).hexdigest()
    last_substance = store.get_kv(con, "published_substance")
    need_status = (substance != last_substance)
    need_req = bool(append_new)
    summary["status_substance"] = substance
    summary["status_changed"] = need_status

    if not need_status and not need_req and not args.force:
        summary["action"] = "skip (no substance change, no new QA responses)"
        inbox.record(summary, state)
        _print(summary)
        return 0

    # ---- publish ----
    verify_markers = [(f"{C.CONTACT_REL}/status/current.md", snapshot_id),
                      (f"{C.CONTACT_REL}/QA_DASHBOARD.md", snapshot_id),
                      (f"{C.CONTACT_REL}/index/current.md", snapshot_id)]
    for r in req_entries:
        verify_markers.append((f"{C.CONTACT_REL}/requests.md", r["id"]))
    commit_msg = f"qa-sync: snapshot {snapshot_id}" + (
        f" + {', '.join(r['id'] for r in req_entries)}" if req_entries else "")

    res = publish.publish(
        status_body=body,
        append_requests=append_new,
        sync_files=extra_files,
        snapshot_id=snapshot_id,
        verify_markers=verify_markers,
        commit_msg=commit_msg,
        dry_run=args.dry_run,
        attempts=C.PUSH_RETRIES,
    )
    summary["publish"] = res

    if res["state"] == "PUBLISHED" or args.dry_run:
        store.set_kv(con, "published_substance", substance)
        store.set_kv(con, "last_snapshot_id", snapshot_id)
        if res.get("remote_sha"):
            store.set_kv(con, "last_publish_remote_sha", res["remote_sha"])
        store.set_kv(con, "total_rate_limited", state["runs"]["rate_limited"])
        store.set_kv(con, "total_spawn_failed", state["runs"]["spawn_failed"])
        store.set_kv(con, "task_status_map", json.dumps(state["cur_taskmap"]))
        if new_entries:
            store.set_kv(con, "last_qa_response", new_entries[-1]["id"])
        for r in req_entries:
            store.mark_response(con, r["response_id"], r["sha"], r["id"])

    summary["action"] = res["state"]
    inbox.record(summary, state)
    _print(summary)
    return 0 if res["state"] in ("PUBLISHED", "NOCHANGE", "DRY_RUN") else 1


def _print(summary):
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(description="Local Kanban <-> external QA synchronizer")
    p.add_argument("--once", action="store_true", help="run a single pass (default)")
    p.add_argument("--dry-run", action="store_true", help="collect + build but do not commit/push")
    p.add_argument("--responses-file", default=None, help="use a local responses.md instead of the remote")
    p.add_argument("--force", action="store_true", help="publish even if the substance is unchanged")
    args = p.parse_args(argv)
    return run_once(args)


if __name__ == "__main__":
    sys.exit(main())
