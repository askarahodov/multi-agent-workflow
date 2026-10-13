#!/usr/bin/env python3
"""Acceptance tests for the local Kanban <-> external QA synchronizer.

Scenarios mirror AUTOMATION_PROTOCOL.md "Критерии приёмки автоматизации" plus the
owner's five required checks. Destructive/concurrent scenarios run against a
throwaway test branch so the real coord/external-qa (and ChatGPT-owned
responses.md) are never polluted.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SERVICE = Path("/home/askarahodov/.hermes/qa-sync")
PY = sys.executable  # same interpreter the test runs under (avoids the masked tools path)
REPO = "/mnt/data/multi-agent-workflow"
REAL_BRANCH = "coord/external-qa"
TEST_BRANCH = f"qa-sync-test-{int(time.time())}"
CT_GATE_DB = "/home/askarahodov/.hermes/kanban/boards/ct-gate/kanban.db"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def run_sync(branch, extra=()):
    env = dict(os.environ, QASYNC_BRANCH=branch)
    p = subprocess.run([PY, str(SERVICE / "qa_sync.py"), *extra],
                       capture_output=True, text=True, timeout=300, env=env)
    try:
        return json.loads(p.stdout), p
    except ValueError:
        return {"action": "PARSE_ERROR", "stdout": p.stdout, "stderr": p.stderr}, p


def remote_head(branch):
    r = subprocess.run(["git", "-C", REPO, "ls-remote", "origin", f"refs/heads/{branch}"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.split()[0] if r.stdout.strip() else None


def remote_file(branch, rel):
    subprocess.run(["git", "-C", REPO, "fetch", "-q", "origin", branch], timeout=120)
    r = subprocess.run(["git", "-C", REPO, "show", f"origin/{branch}:{rel}"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ""


def _git(args, cwd=REPO, timeout=180):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout)


def setup_test_branch():
    _git(["push", "origin", f"origin/{REAL_BRANCH}:refs/heads/{TEST_BRANCH}"])


def teardown_test_branch():
    _git(["push", "origin", "--delete", TEST_BRANCH])


def set_task_status(db, tid, status):
    con = sqlite3.connect(db, timeout=30)
    with con:
        con.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))
    con.close()


def get_task_status(db, tid):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()
    con.close()
    return row[0] if row else None


# ---------------------------------------------------------------- T1
def test1_stability():
    """3 consecutive no-op passes produce no commits and no LLM calls."""
    # drain any pending work first
    for _ in range(6):
        s, _ = run_sync(REAL_BRANCH)
        if str(s.get("action", "")).startswith("skip"):
            break
    heads = []
    ok = True
    detail = ""
    for i in range(3):
        h_before = remote_head(REAL_BRANCH)
        s, p = run_sync(REAL_BRANCH)
        h_after = remote_head(REAL_BRANCH)
        stable = str(s.get("action", "")).startswith("skip")
        if not stable or h_before != h_after:
            ok = False
            detail = f"pass {i+1}: action={s.get('action')} head {h_before}->{h_after}"
            break
        heads.append(h_after)
    check("T1 3 no-op passes: no commits, no push", ok, detail or f"head stable at {heads[-1][:10]}")
    # no LLM invocation: the module never imports/spawns a model client
    src = (SERVICE / "qasync").glob("*.py")
    txt = "".join(p.read_text() for p in src)
    lowered = txt.lower()
    check("T1 no LLM client used by sync code",
          all(tok not in lowered for tok in ("import openai", "import anthropic", "generativeai",
                                             "requests.post", "chat.completions", "messages.create")))


# ---------------------------------------------------------------- T2
def test2_status_change():
    """A local Kanban status change appears in the REMOTE status/current.md."""
    tid = "t_a906a3c4"  # archived test probe on the ct-gate board
    old = get_task_status(CT_GATE_DB, tid)
    set_task_status(CT_GATE_DB, tid, "todo")
    try:
        s, p = run_sync(REAL_BRANCH)
        doc = remote_file(REAL_BRANCH, ".coordination/external-qa/status/current.md")
        ok = (f"`{tid}`" in doc and "todo" in doc)
        check("T2 status change visible in remote status/current.md", ok,
              f"publish={s.get('publish', {}).get('state')}")
    finally:
        set_task_status(CT_GATE_DB, tid, old or "archived")
        run_sync(REAL_BRANCH)  # publish the restore


# ---------------------------------------------------------------- T3
def test3_single_processing():
    """A new QA-RSP is processed exactly once (one reply, no duplicates)."""
    fixture = SERVICE / "tests" / "fixtures" / "responses_new.md"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    rid = f"QA-RSP-TEST-{int(time.time())}"
    fixture.write_text(
        "# QA responses fixture\n\n"
        f"## {rid}\n- request: QA-REQ-TEST\n- verdict: CHANGES_REQUESTED\n"
        "- findings: test finding referencing t_005a92be and t_759fb8e6\n")
    s1, _ = run_sync(TEST_BRANCH, extra=["--responses-file", str(fixture)])
    req1 = s1.get("generated_requests", [])
    doc = remote_file(TEST_BRANCH, ".coordination/external-qa/requests.md")
    ok1 = len(req1) == 1 and f"in_reply_to: {rid}" in doc
    s2, _ = run_sync(TEST_BRANCH, extra=["--responses-file", str(fixture)])
    req2 = s2.get("generated_requests", [])
    doc2 = remote_file(TEST_BRANCH, ".coordination/external-qa/requests.md")
    ok2 = len(req2) == 0 and doc2.count(f"in_reply_to: {rid}") == 1
    check("T3 new QA-RSP answered exactly once", ok1 and ok2,
          f"first={req1} second={req2} occurrences={doc2.count('in_reply_to: ' + rid)}")


# ---------------------------------------------------------------- T4
def test4_concurrent_responses():
    """A concurrent ChatGPT commit to responses.md is not lost by our publish."""
    # simulate ChatGPT: append a new response directly on the test branch
    wt = SERVICE / "tests" / "tmp-chatgpt"
    subprocess.run(["git", "-C", REPO, "worktree", "remove", "--force", str(wt)],
                   capture_output=True, text=True)
    _git(["fetch", "-q", "origin", TEST_BRANCH])
    subprocess.run(["git", "-C", REPO, "worktree", "add", "--detach", str(wt), f"origin/{TEST_BRANCH}"],
                   capture_output=True, text=True)
    rid = f"QA-RSP-CONCURRENT-{int(time.time())}"
    rp = Path(wt) / ".coordination/external-qa/responses.md"
    rp.write_text(rp.read_text() + f"\n\n## {rid}\n- request: QA-REQ-TEST\n- verdict: INFO\n- findings: concurrent write\n")
    _git(["add", "--", ".coordination/external-qa/responses.md"], wt)
    _git(["-c", "user.name=ChatGPT (sim)", "-c", "user.email=chatgpt@sim", "commit", "-m", "chatgpt: simulated response"], wt)
    _git(["push", "origin", f"HEAD:refs/heads/{TEST_BRANCH}"], wt)
    subprocess.run(["git", "-C", REPO, "worktree", "remove", "--force", str(wt)], capture_output=True, text=True)

    s, _ = run_sync(TEST_BRANCH)
    doc_r = remote_file(TEST_BRANCH, ".coordination/external-qa/responses.md")
    doc_q = remote_file(TEST_BRANCH, ".coordination/external-qa/requests.md")
    kept = rid in doc_r
    replied = f"in_reply_to: {rid}" in doc_q
    check("T4 concurrent ChatGPT responses.md preserved + answered", kept and replied,
          f"kept={kept} replied={replied} publish={s.get('publish', {}).get('state')}")


# ---------------------------------------------------------------- T5
def test5_recovery():
    """Stale lock recovery + non-fast-forward push retry."""
    # 5a: stale lock (dead pid) must be stolen, not fatal
    lock = SERVICE / "sync.lock"
    lock.write_text(json.dumps({"pid": 999999, "ts": time.time() - 999999}))
    s, p = run_sync(TEST_BRANCH, extra=["--force"])
    check("T5a stale lock stolen and pass completes",
          s.get("action") in ("PUBLISHED", "NOCHANGE", "DRY_RUN") and not lock.exists(),
          f"action={s.get('action')}")

    # 5b: first push returns non-fast-forward -> retry loop must refetch and succeed
    sys.path.insert(0, str(SERVICE))
    os.environ["QASYNC_BRANCH"] = TEST_BRANCH
    import importlib
    from qasync import config as C
    importlib.reload(C)
    from qasync import publish as P
    importlib.reload(P)
    real_git = P._git
    state = {"pushes": 0}

    def flaky_git(args, cwd, timeout=180):
        if args and args[0] == "push":
            state["pushes"] += 1
            if state["pushes"] == 1:
                class R:
                    returncode = 1
                    stdout = ""
                    stderr = "! [rejected] non-fast-forward"
                return R()
        return real_git(args, cwd, timeout)

    P._git = flaky_git
    res = P.publish(status_body="# t5b body\n", append_requests=[],
                    sync_files={}, snapshot_id="T5B", verify_markers=[], commit_msg="t5b")
    check("T5b non-fast-forward push retried and published",
          res["state"] == "PUBLISHED" and res["attempts"] >= 2 and state["pushes"] >= 2,
          f"state={res['state']} attempts={res.get('attempts')} pushes={state['pushes']}")


# ---------------------------------------------------------------- T6
def test6_invariants():
    src = "".join(p.read_text() for p in (SERVICE / "qasync").glob("*.py"))
    pub = (SERVICE / "qasync" / "publish.py").read_text()
    check("T6 no force-push in publish path",
          "--force" not in pub and "--force-with-lease" not in pub and "+refs/heads" not in pub)
    check("T6 responses.md is never written by sync code",
          "responses.md" not in (SERVICE / "qasync" / "publish.py").read_text())
    check("T6 no GitHub issue creation", "issue create" not in src and "create_issue" not in src)
    sys.path.insert(0, str(SERVICE))
    from qasync.publish import sanitize
    sample = "key [REDACTED] and Authorization: Bearer [REDACTED]
    red = sanitize(sample)
    check("T6 secret sanitizer redacts tokens", "sk-ABCDEF" not in red and "xyz.secret" not in red, red[:60])


# ---------------------------------------------------------------- T7
def test7_dedup_on_changed_body():
    """Root-cause guard: a response already ACKed on the remote (by in_reply_to)
    must NOT be ACKed again even when its body/SHA changed."""
    # the test branch already carries our ACKs from earlier scenarios; pick an id
    # that is answered there and feed a MODIFIED copy of it.
    req_doc = remote_file(TEST_BRANCH, ".coordination/external-qa/requests.md")
    m = re.search(r"in_reply_to:\s*(QA-RSP-[A-Za-z0-9._\-]+)", req_doc)
    if not m:
        check("T7 changed-body response not re-ACKed", False, "no answered id on test branch")
        return
    rid = m.group(1)
    fixture = SERVICE / "tests" / "fixtures" / "responses_changed.md"
    fixture.write_text(f"# fixture\n\n## {rid}\n- request: QA-REQ-TEST\n- verdict: CHANGES_REQUESTED\n"
                       "- findings: BODY CHANGED after the first ACK (new sha)\n")
    s, _ = run_sync(TEST_BRANCH, extra=["--responses-file", str(fixture)])
    doc = remote_file(TEST_BRANCH, ".coordination/external-qa/requests.md")
    n = doc.count(f"in_reply_to: {rid}")
    check("T7 changed-body response not re-ACKed (no duplicate)", len(s.get("generated_requests", [])) == 0 and n == 1,
          f"generated={s.get('generated_requests')} in_reply_to_count={n}")


def main():
    setup_test_branch()
    try:
        test1_stability()
        test2_status_change()
        test3_single_processing()
        test4_concurrent_responses()
        test5_recovery()
        test6_invariants()
        test7_dedup_on_changed_body()
    finally:
        teardown_test_branch()
    failed = [r for r in results if not r[1]]
    print(f"\n==== {len(results) - len(failed)}/{len(results)} PASSED ====")
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
