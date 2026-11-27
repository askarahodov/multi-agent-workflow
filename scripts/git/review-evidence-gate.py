#!/usr/bin/env python3
"""Read-only GF-09 candidate audit. Run ONLY from an accepted protected main.
Never submits a GitHub review, changes rulesets, merges, or deletes a ref.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = "askarahodov/multi-agent-workflow"
BOT_ID = 199175422
BOT_NODE_ID = "BOT_kgDOC98s_g"
APP_ID = 1144995
ACTIONS_APP_ID = 15368
SHA = re.compile(r"^[0-9a-f]{40}$")
MARKER = "<!-- codex-pull-request-review-summary -->"
STATE = re.compile(r"^<!-- codex-review-state:v1 (\{[^\n]*\}) -->$")
# Initial deliberately narrow pilot. All other paths, including policy, API,
# runtime, CI, security, deployments, contracts and PRD, need human approval.
PILOT_PATHS = frozenset({"docs/architecture/enterprise-gap-audit.md"})
REQUIRED_WORKFLOWS = frozenset({
    ".github/workflows/ci.yml", ".github/workflows/quality-gate.yml",
    ".github/workflows/gitflow-policy.yml", ".github/workflows/coordination-isolation.yml",
    ".github/workflows/native-agent-e2e.yml", ".github/workflows/docs-dependency-check.yml",
})


def trusted_comment(c):
    user = c.get("user") or {}
    app = c.get("performed_via_github_app") or {}
    return (user.get("id") == BOT_ID and user.get("type") == "Bot"
            and user.get("login") == "chatgpt-codex-connector[bot]"
            and app.get("id") == APP_ID and app.get("slug") == "chatgpt-codex-connector"
            and (app.get("owner") or {}).get("id") == 14957082)


def authenticated_body(c, node):
    """Body and editor must come from the SAME trusted GraphQL snapshot."""
    if not trusted_comment(c) or not isinstance(node, dict):
        return False
    author = node.get("author") or {}
    editor = node.get("editor")
    if (not c.get("node_id") or node.get("id") != c["node_id"]
            or node.get("body") != c.get("body")
            or node.get("updatedAt") != c.get("updated_at")
            or author.get("id") != BOT_NODE_ID
            or author.get("__typename") != "Bot"
            or "lastEditedAt" not in node or "editor" not in node):
        return False
    if editor is None:
        return (node["lastEditedAt"] is None
                and node.get("updatedAt") == node.get("createdAt"))
    return (isinstance(editor, dict) and editor.get("__typename") == "Bot"
            and editor.get("id") == BOT_NODE_ID
            and isinstance(node["lastEditedAt"], str))


def assess(pr, main, comparison, comments, comment_nodes, reviews, threads, checks, runs, required):
    """Pure evidence classifier; invalid or missing information never passes."""
    failures = []
    head = (pr.get("head") or {}).get("sha")
    base = pr.get("base") or {}
    author = (pr.get("user") or {}).get("id")
    if (not isinstance(head, str) or not SHA.fullmatch(head) or not isinstance(main, str)
            or not SHA.fullmatch(main) or base.get("sha") != main
            or base.get("ref") != "main" or (base.get("repo") or {}).get("full_name") != REPO
            or ((pr.get("head") or {}).get("repo") or {}).get("full_name") != REPO
            or pr.get("state") != "open" or pr.get("draft") is not False
            or pr.get("mergeable") is not True or not isinstance(author, int) or author == BOT_ID):
        failures.append("candidate is not a ready same-repository PR against current main")
    if (comparison.get("behind_by") != 0
            or (comparison.get("merge_base_commit") or {}).get("sha") != main
            or not isinstance(comparison.get("ahead_by"), int) or comparison["ahead_by"] < 1):
        failures.append("candidate does not contain current main")
    # Immutable comparison, not /pulls/N/files (which is vulnerable to ABA).
    files = comparison.get("files")
    if (not isinstance(files, list) or not files or len(files) != 1
            or len(files) != pr.get("changed_files")
            or any(f.get("filename") not in PILOT_PATHS
                   or f.get("status") not in ("added", "modified")
                   or f.get("previous_filename") is not None for f in files)):
        failures.append("outside narrowly allowlisted documentation pilot; human approval required")
    summaries = [c for c in comments if trusted_comment(c)
                 and (c.get("body") or "").splitlines()[:1] == [MARKER]]
    receipt = None
    if len(summaries) != 1:
        failures.append("missing or ambiguous authenticated Codex summary")
    else:
        c = summaries[0]
        node = comment_nodes.get(c.get("node_id"))
        lines = node["body"].splitlines() if authenticated_body(c, node) else []
        m = STATE.fullmatch(lines[1]) if len(lines) > 1 else None
        try:
            data = json.loads(m.group(1)) if m else {}
            review = data.get("code_review") or {}
            if (review.get("commit_sha") != head or review.get("status") != "completed"
                    or review.get("has_any_findings") is not False
                    or review.get("has_unresolved_findings") is not False
                    or not isinstance(c.get("id"), int)):
                raise ValueError("not clean exact head")
            receipt = c["id"]
        except (ValueError, TypeError, AttributeError):
            failures.append("Codex review stale, incomplete, malformed or has findings")
    # Review threads are retrieved independently from GraphQL; a later clean
    # summary must not conceal an actual unresolved thread.
    if any(t.get("isResolved") is not True for t in threads):
        failures.append("unresolved review thread")
    # A later APPROVED or DISMISSED by the same identity supersedes a prior
    # change request; COMMENTED never cancels an explicit negative review.
    latest = {}
    for rv in sorted(reviews, key=lambda x: x.get("id") or 0):
        uid = (rv.get("user") or {}).get("id")
        if not isinstance(uid, int):
            failures.append("malformed review identity")
        elif rv.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[uid] = rv
    if any(rv.get("state") == "CHANGES_REQUESTED" for rv in latest.values()):
        failures.append("outstanding changes requested")
    if not required or len(set(required)) != len(required):
        failures.append("invalid required check inventory")
    for name in required:
        found = [c for c in checks if c.get("name") == name]
        if not found or any(c.get("head_sha") != head
                            or (c.get("app") or {}).get("id") != ACTIONS_APP_ID
                            or c.get("status") != "completed" or c.get("conclusion") != "success"
                            for c in found):
            failures.append("missing, untrusted or non-success required check: " + name)
    # Newest run for each workflow path on this head only. Do not count an
    # earlier cancelled retry as failure if superseded by a successful run.
    by_path = {}
    for run in runs:
        path = run.get("path")
        if not isinstance(path, str) or not isinstance(run.get("id"), int):
            failures.append("malformed workflow metadata")
            continue
        if run.get("head_sha") != head:
            failures.append("workflow head mismatch")
            continue
        if path not in by_path or run["id"] > by_path[path]["id"]:
            by_path[path] = run
    for path in REQUIRED_WORKFLOWS | set(by_path):
        run = by_path.get(path) or {}
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            failures.append("missing or non-success workflow: " + path)
    return {"status": "EVIDENCE_READY" if not failures else "BLOCKED",
            "head_sha": head, "base_sha": main, "codex_comment_id": receipt,
            "failures": failures, "merge_authorized": False}


def api(endpoint, *, pages=False, fields=()):
    args = ["gh", "api", "--method", "GET", endpoint]
    if pages:
        args += ["--paginate", "--slurp"]
    args += list(fields)
    proc = subprocess.run(args, capture_output=True, text=True, timeout=90, check=False)
    if proc.returncode:
        raise RuntimeError("GitHub API read failed; no approval inferred")
    return json.loads(proc.stdout)


def flatten(data, key=None):
    if not isinstance(data, list):
        raise ValueError("invalid paginated response")
    rows = []
    for page in data:
        part = page.get(key) if key and isinstance(page, dict) else page
        if not isinstance(part, list):
            raise ValueError("invalid page")
        rows.extend(part)
    return rows


def review_threads(number):
    query = """query($owner:String!,$repo:String!,$number:Int!,$endCursor:String){
      repository(owner:$owner,name:$repo){pullRequest(number:$number){
        reviewThreads(first:100,after:$endCursor){
          nodes{isResolved} pageInfo{hasNextPage endCursor}
        }
      }}
    }"""
    owner, name = REPO.split("/")
    proc = subprocess.run(["gh","api","graphql","--paginate","--slurp",
                           "-f","query="+query,"-f","owner="+owner,"-f","repo="+name,
                           "-F","number="+str(number)], capture_output=True, text=True,
                          timeout=90, check=False)
    if proc.returncode:
        raise RuntimeError("review thread read failed")
    pages = json.loads(proc.stdout)
    if not isinstance(pages, list) or not pages:
        raise ValueError("missing review thread pages")
    result = []
    for page in pages:
        if page.get("errors"):
            raise ValueError("review thread query error")
        result.extend(page["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"])
    if pages[-1]["data"]["repository"]["pullRequest"]["reviewThreads"]["pageInfo"]["hasNextPage"] is not False:
        raise ValueError("incomplete review thread pagination")
    return result


def comment_snapshot(node_id):
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("missing comment node ID")
    query = """query($id:ID!){node(id:$id){... on IssueComment{
      id body createdAt updatedAt lastEditedAt
      author { __typename ... on Bot { id } }
      editor { __typename ... on Bot { id } }
    }}}"""
    proc = subprocess.run(["gh","api","graphql","-f","query="+query,
                           "-f","id="+node_id], capture_output=True, text=True,
                          timeout=90, check=False)
    if proc.returncode:
        raise RuntimeError("comment editor read failed")
    data = json.loads(proc.stdout)
    if data.get("errors") or not isinstance(data.get("data",{}).get("node"),dict):
        raise ValueError("comment provenance unavailable")
    return data["data"]["node"]


def route_candidate(pr, main, comparison=None):
    """Classify automatic trigger applicability, never review or merge readiness."""
    head = (pr.get("head") or {}).get("sha")
    base = pr.get("base") or {}
    result = {"head_sha": head, "base_sha": main, "merge_authorized": False,
              "codex_comment_id": None, "failures": []}
    def decision(status, reason):
        return {**result, "status": status, "reason": reason,
                "failures": [reason] if status == "BLOCKED" else []}
    if (not isinstance(head, str) or not SHA.fullmatch(head)
            or not isinstance(main, str) or not SHA.fullmatch(main)
            or pr.get("state") not in ("open", "closed")
            or not isinstance(pr.get("draft"), bool)
            or not isinstance(base.get("ref"), str)
            or not isinstance((base.get("repo") or {}).get("full_name"), str)
            or not isinstance(((pr.get("head") or {}).get("repo") or {}).get("full_name"), str)):
        return decision("BLOCKED", "invalid candidate routing metadata")
    if pr["state"] == "closed":
        return decision("NOT_APPLICABLE", "PR is closed")
    if pr["draft"]:
        return decision("NOT_APPLICABLE", "draft PR; independent approval still required")
    if (base["ref"] != "main" or base["repo"]["full_name"] != REPO
            or pr["head"]["repo"]["full_name"] != REPO):
        return decision("NOT_APPLICABLE", "not a same-repository PR targeting main")
    if comparison is None:
        return decision("NEEDS_DIFF", "immutable candidate diff required")
    files = comparison.get("files")
    if (not isinstance(files, list) or not files
            or len(files) != pr.get("changed_files")
            or any(not isinstance(f, dict) or not isinstance(f.get("filename"), str)
                   or not isinstance(f.get("status"), str) for f in files)):
        return decision("BLOCKED", "missing or incomplete immutable candidate diff")
    if (len(files) != 1 or any(f["filename"] not in PILOT_PATHS
                               or f["status"] not in ("added", "modified")
                               or f.get("previous_filename") is not None for f in files)):
        return decision("NOT_APPLICABLE", "outside pilot scope; ordinary independent approval required")
    return decision("ELIGIBLE", "pilot path only; full audit still required")


def trusted_checkout(expected_head):
    if not SHA.fullmatch(expected_head):
        raise ValueError("exact SHA required")
    root = Path(__file__).resolve().parents[2]
    main = api(f"repos/{REPO}/git/ref/heads/main")["object"]["sha"]
    local = subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],
                           capture_output=True,text=True,timeout=10,check=True).stdout.strip()
    dirty = subprocess.run(["git","-C",str(root),"status","--porcelain"],
                           capture_output=True,text=True,timeout=10,check=True).stdout
    if local != main or dirty:
        raise RuntimeError("run from a clean checkout of exact protected main")
    return root, main


def routing_snapshot(pr):
    head, base = pr["head"], pr["base"]
    return (head["sha"], base["sha"], base["ref"], pr["state"], pr["draft"],
            pr.get("changed_files"), head.get("repo"), base.get("repo"))


def completed_review_event(event, expected_head):
    """Trigger hint only: never use the event as review evidence."""
    comment = event.get("comment") or {}
    sender = event.get("sender") or {}
    user = comment.get("user") or {}
    app = comment.get("performed_via_github_app") or {}
    if (event.get("action") not in ("created", "edited")
            or sender.get("id") != BOT_ID
            or user.get("id") != BOT_ID or app.get("id") != APP_ID
            or not (event.get("issue") or {}).get("pull_request")):
        raise ValueError("untrusted automatic audit event")
    lines = (comment.get("body") or "").splitlines()
    match = STATE.fullmatch(lines[1]) if len(lines) > 1 and lines[0] == MARKER else None
    if not match:
        raise ValueError("malformed review event summary")
    data = json.loads(match.group(1))
    if not isinstance(data, dict) or not isinstance(data.get("code_review"), dict):
        raise ValueError("missing code review event state")
    review = data["code_review"]
    status = review.get("status")
    if status not in ("running", "completed", "pending", "queued"):
        raise ValueError("unknown code review event status")
    sha = review.get("commit_sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("invalid code review event SHA")
    return status == "completed" and sha == expected_head


def live_route(number, expected_head, event=None):
    _, main = trusted_checkout(expected_head)
    prefix = f"repos/{REPO}"
    pr = api(f"{prefix}/pulls/{number}")
    if pr["head"]["sha"] != expected_head:
        raise RuntimeError("PR head changed before routing")
    if event is not None and not completed_review_event(event, expected_head):
        report = {"status": "NOT_APPLICABLE", "head_sha": expected_head,
                  "base_sha": main, "merge_authorized": False, "codex_comment_id": None,
                  "failures": [], "reason": "not a completed code review event for current head"}
    else:
        report = route_candidate(pr, main)
    if report["status"] == "NEEDS_DIFF":
        comparison = api(f"{prefix}/compare/{main}...{expected_head}")
        report = route_candidate(pr, main, comparison)
    final = api(f"{prefix}/pulls/{number}")
    if (routing_snapshot(final) != routing_snapshot(pr)
            or api(f"{prefix}/git/ref/heads/main")["object"]["sha"] != main):
        raise RuntimeError("candidate changed during routing")
    return report


def live(number, expected_head):
    # Never trust the candidate's copy of this script or check inventory.
    root, main = trusted_checkout(expected_head)
    prefix = f"repos/{REPO}"
    pr = api(f"{prefix}/pulls/{number}")
    if pr["head"]["sha"] != expected_head:
        raise RuntimeError("PR head changed")
    comparison = api(f"{prefix}/compare/{main}...{expected_head}")
    comments = flatten(api(f"{prefix}/issues/{number}/comments?per_page=100", pages=True))
    comment_nodes = {c["node_id"]: comment_snapshot(c["node_id"])
                     for c in comments if trusted_comment(c)
                     and (c.get("body") or "").splitlines()[:1] == [MARKER]}
    reviews = flatten(api(f"{prefix}/pulls/{number}/reviews?per_page=100", pages=True))
    threads = review_threads(number)
    checks = flatten(api(f"{prefix}/commits/{expected_head}/check-runs?filter=latest&per_page=100", pages=True), "check_runs")
    runs = flatten(api(f"{prefix}/actions/runs?head_sha={expected_head}&per_page=100", pages=True), "workflow_runs")
    required = [s.strip() for s in (root/"tests/gitflow/required-checks.txt").read_text().splitlines()
                if s.strip() and not s.lstrip().startswith("#")]
    required.append("gitflow required checks")
    report = assess(pr,main,comparison,comments,comment_nodes,reviews,threads,checks,runs,required)
    final = api(f"{prefix}/pulls/{number}")
    if (final["head"]["sha"] != expected_head or final["base"]["sha"] != main
            or final.get("draft") != pr.get("draft") or final.get("state") != pr.get("state")
            or api(f"{prefix}/git/ref/heads/main")["object"]["sha"] != main):
        raise RuntimeError("candidate changed during audit")
    # A changed/deleted comment after the first snapshot invalidates the audit.
    for node_id, snapshot in comment_nodes.items():
        if comment_snapshot(node_id) != snapshot:
            raise RuntimeError("comment changed during audit")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pr",type=int,required=True)
    p.add_argument("--head",required=True)
    p.add_argument("--route", action="store_true", help="automatic trigger applicability only")
    p.add_argument("--event-file", type=Path, help="GitHub automatic event payload; routing only")
    args=p.parse_args()
    try:
        if args.pr < 1:
            raise ValueError("invalid PR number")
        if args.event_file is not None and not args.route:
            raise ValueError("event file only allowed for routing")
        if args.route:
            event = json.loads(args.event_file.read_text()) if args.event_file else None
            if args.event_file and not isinstance(event, dict):
                raise ValueError("invalid event payload")
            report = (live_route(args.pr,args.head,event) if args.event_file
                      else live_route(args.pr,args.head))
        else:
            report=live(args.pr,args.head)
    except (ValueError,RuntimeError,KeyError,TypeError,OSError,subprocess.SubprocessError):
        report={"status":"BLOCKED","merge_authorized":False,"failures":["live audit unavailable or candidate changed"]}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    # Routing success is not audit success. Direct audit remains fail-closed.
    return 0 if report["status"] in (("ELIGIBLE", "NOT_APPLICABLE") if args.route else ("EVIDENCE_READY",)) else 1

if __name__=="__main__":
    sys.exit(main())
