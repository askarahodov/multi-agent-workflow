"""One synchronization pass: collect -> diff QA responses -> publish -> verify."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

from . import collect, config as C, publish, render, respond, store

SYNC_MODULES = ["config.py", "store.py", "collect.py", "render.py", "respond.py",
                "publish.py", "main.py"]


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
    r = subprocess.run(
        ["git", "-C", str(C.REPO), "show", f"origin/{C.BRANCH}:{C.CONTACT_REL}/requests.md"],
        capture_output=True, text=True, timeout=90)
    return r.stdout if r.returncode == 0 else ""


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

    # Exactly-once ACK, robust to a changed response body: a response is answered
    # if its id already appears as `in_reply_to` in the PUBLISHED remote requests.md
    # (survives rebase/partial publish) OR its id+sha is in the durable ledger.
    answered = set(re.findall(r"in_reply_to:\s*(QA-RSP-[A-Za-z0-9._\-]+)", _read_remote_requests()))
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
    summary["new_responses"] = [e["id"] for e in new_entries]
    summary["generated_requests"] = [r["id"] for r in req_entries]

    # ---- render status + dashboard from the SAME snapshot ----
    prev_pub = store.get_kv(con, "last_publish_remote_sha", "NONE")
    ps = prev_pub[:12] if prev_pub != "NONE" else "NONE"
    body, sub_status = render.render(state, snapshot_id, publish_state=ps)
    dashboard = render.render_dashboard(state, snapshot_id, publish_state=ps)
    sync_files = _sync_code()
    code_hash = hashlib.sha256(
        json.dumps(sorted(sync_files.items()), ensure_ascii=False).encode("utf-8")).hexdigest()
    substance = hashlib.sha256(
        (sub_status + render.normalize(dashboard) + code_hash).encode("utf-8")).hexdigest()
    last_substance = store.get_kv(con, "published_substance")
    need_status = (substance != last_substance)
    need_req = bool(req_entries)
    summary["status_substance"] = substance
    summary["status_changed"] = need_status

    if not need_status and not need_req and not args.force:
        summary["action"] = "skip (no substance change, no new QA responses)"
        _print(summary)
        return 0

    # ---- publish ----
    verify_markers = [(f"{C.CONTACT_REL}/status/current.md", snapshot_id),
                      (f"{C.CONTACT_REL}/QA_DASHBOARD.md", snapshot_id)]
    for r in req_entries:
        verify_markers.append((f"{C.CONTACT_REL}/requests.md", r["id"]))
    commit_msg = f"qa-sync: snapshot {snapshot_id}" + (
        f" + {', '.join(r['id'] for r in req_entries)}" if req_entries else "")

    res = publish.publish(
        status_body=body,
        dashboard_body=dashboard,
        append_requests=[r["text"] for r in req_entries],
        sync_files=sync_files,
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
