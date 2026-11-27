"""Regression tests for independent review evidence; no GitHub credentials."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location("review_gate",Path(__file__).parents[1]/"review-evidence-gate.py")
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

HEAD="a"*40
BASE="b"*40

def fixture():
    repo={"full_name":gate.REPO}
    pr={"head":{"sha":HEAD,"repo":repo},"base":{"sha":BASE,"ref":"main","repo":repo},
        "state":"open","draft":False,"mergeable":True,"user":{"id":7},"changed_files":1}
    body=gate.MARKER+"\n<!-- codex-review-state:v1 "+json.dumps({"code_review":{
        "commit_sha":HEAD,"status":"completed","has_any_findings":False,"has_unresolved_findings":False}})+" -->"
    comments=[{"id":8,"body":body,"user":{"id":gate.BOT_ID,"type":"Bot","login":"chatgpt-codex-connector[bot]"},
               "performed_via_github_app":{"id":gate.APP_ID,"slug":"chatgpt-codex-connector","owner":{"id":14957082}}}]
    comments[0].update(node_id="comment-node",updated_at="2026-11-26T10:00:00Z")
    node={"id":"comment-node","body":body,"createdAt":"2026-11-26T09:00:00Z",
          "updatedAt":comments[0]["updated_at"],"lastEditedAt":"2026-11-26T10:00:00Z",
          "author":{"__typename":"Bot","id":gate.BOT_NODE_ID},
          "editor":{"__typename":"Bot","id":gate.BOT_NODE_ID}}
    required=["quality gate","gitflow required checks"]
    return dict(pr=pr,main=BASE,comparison={"behind_by":0,"ahead_by":1,"merge_base_commit":{"sha":BASE},
                            "files":[{"filename":next(iter(gate.PILOT_PATHS)),"status":"added"}]},
                comments=comments,comment_nodes={"comment-node":node},reviews=[],threads=[],required=required,
                checks=[{"name":n,"head_sha":HEAD,"app":{"id":gate.ACTIONS_APP_ID},"status":"completed","conclusion":"success"} for n in required],
                runs=[{"id":i,"path":path,"head_sha":HEAD,"status":"completed","conclusion":"success"} for i,path in enumerate(sorted(gate.REQUIRED_WORKFLOWS),1)])

def test_clean_exact_candidate_is_evidence_only():
    result=gate.assess(**fixture())
    assert result["status"]=="EVIDENCE_READY"
    assert result["merge_authorized"] is False
    assert result["codex_comment_id"]==8

@pytest.mark.parametrize("change",["forged_user","forged_app","stale_sha","unresolved_finding","missing_summary",
    "duplicate_summary","unresolved_thread","changes_requested","stale_base","draft","fork","bot_author",
    "policy_change","deleted_file","truncated_files","missing_check","skipped_check","wrong_check_app",
    "wrong_check_sha","missing_workflow","pending_workflow","failed_workflow"])
def test_fail_closed(change):
    f=fixture()
    if change=="forged_user": f["comments"][0]["user"]["id"]=7
    elif change=="forged_app": f["comments"][0]["performed_via_github_app"]["id"]=0
    elif change=="stale_sha": f["comments"][0]["body"]=f["comments"][0]["body"].replace(HEAD,"c"*40)
    elif change=="unresolved_finding": f["comments"][0]["body"]=f["comments"][0]["body"].replace('"has_unresolved_findings": false','"has_unresolved_findings": true')
    elif change=="missing_summary": f["comments"]=[]
    elif change=="duplicate_summary": f["comments"].append(copy.deepcopy(f["comments"][0]))
    elif change=="unresolved_thread": f["threads"]=[{"isResolved":False}]
    elif change=="changes_requested": f["reviews"]=[{"id":1,"user":{"id":10},"state":"CHANGES_REQUESTED"},{"id":2,"user":{"id":10},"state":"COMMENTED"}]
    elif change=="stale_base": f["comparison"]["behind_by"]=1
    elif change=="draft": f["pr"]["draft"]=True
    elif change=="fork": f["pr"]["head"]={"sha":HEAD,"repo":{"full_name":"other/repo"}}
    elif change=="bot_author": f["pr"]["user"]["id"]=gate.BOT_ID
    elif change=="policy_change": f["comparison"]["files"][0]["filename"]="AGENT_GITFLOW_RULES.md"
    elif change=="deleted_file": f["comparison"]["files"][0]["status"]="removed"
    elif change=="truncated_files": f["pr"]["changed_files"]=2
    elif change=="missing_check": f["checks"].pop()
    elif change=="skipped_check": f["checks"][0]["conclusion"]="skipped"
    elif change=="wrong_check_app": f["checks"][0]["app"]["id"]=0
    elif change=="wrong_check_sha": f["checks"][0]["head_sha"]=BASE
    elif change=="missing_workflow": f["runs"].pop()
    elif change=="pending_workflow": f["runs"][0]["status"]="in_progress"
    elif change=="failed_workflow": f["runs"][0]["conclusion"]="failure"
    report=gate.assess(**f)
    assert report["status"]=="BLOCKED"
    assert report["failures"]
    assert report["merge_authorized"] is False

def test_superseded_cancelled_workflow_does_not_hide_latest_failure():
    f=fixture()
    old=f["runs"][0]
    old["conclusion"]="cancelled"
    f["runs"].append({**old,"id":100,"conclusion":"success"})
    assert gate.assess(**f)["status"]=="EVIDENCE_READY"
    f["runs"][-1]["conclusion"]="failure"
    assert gate.assess(**f)["status"]=="BLOCKED"

def test_later_review_can_clear_previous_request_but_not_open_thread():
    f=fixture()
    f["reviews"]=[{"id":1,"user":{"id":10},"state":"CHANGES_REQUESTED"},
                  {"id":2,"user":{"id":10},"state":"APPROVED"}]
    assert gate.assess(**f)["status"]=="EVIDENCE_READY"
    f["threads"]=[{"isResolved":False}]
    assert gate.assess(**f)["status"]=="BLOCKED"

def test_workflow_trusted_main_read_only_and_no_pr_checkout():
    text=(Path(__file__).parents[3]/".github/workflows/review-evidence-audit.yml").read_text()
    assert "issue_comment:" in text and "workflow_dispatch:" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.event.comment.user.id == 199175422" in text
    assert "github.event.comment.performed_via_github_app.id == 1144995" in text
    assert "ref: refs/heads/main" in text and "persist-credentials: false" in text
    assert "pull_request_target:" not in text
    assert ": write" not in text and "gh pr merge" not in text
    assert "python3 scripts/git/review-evidence-gate.py" in text

@pytest.mark.parametrize("tamper",["human_editor","unknown_editor","missing_editor",
    "wrong_bot","different_body","different_update","different_node","no_provenance"])
def test_comment_editor_and_body_must_be_authenticated(tamper):
    f=fixture()
    node=f["comment_nodes"]["comment-node"]
    if tamper=="human_editor": node["editor"]={"__typename":"User","id":"owner"}
    elif tamper=="unknown_editor": node["editor"]=None
    elif tamper=="missing_editor": del node["editor"]
    elif tamper=="wrong_bot": node["editor"]["id"]="other-bot"
    elif tamper=="different_body": node["body"]+="\nchanged"
    elif tamper=="different_update": node["updatedAt"]="2026-11-26T11:00:00Z"
    elif tamper=="different_node": node["id"]="another-node"
    elif tamper=="no_provenance": f["comment_nodes"]={}
    assert gate.assess(**f)["status"]=="BLOCKED"

def test_unedited_comment_with_explicit_provenance_is_valid():
    f=fixture()
    node=f["comment_nodes"]["comment-node"]
    node["editor"]=None
    node["lastEditedAt"]=None
    node["createdAt"]=node["updatedAt"]
    assert gate.assess(**f)["status"]=="EVIDENCE_READY"

def test_immutable_comparison_prevents_same_count_aba_scope_substitution():
    f=fixture()
    f["comparison"]["files"]=[{"filename":"AGENT_GITFLOW_RULES.md","status":"modified"}]
    # The mutable PR snapshot still says one file. An allowed intermediate
    # PR head cannot replace the immutable comparison's forbidden path.
    assert f["pr"]["changed_files"]==1
    assert gate.assess(**f)["status"]=="BLOCKED"
    del f["comparison"]["files"]
    assert gate.assess(**f)["status"]=="BLOCKED"

def test_comparison_requires_exact_single_allowlisted_path():
    f=fixture()
    f["comparison"]["files"].append(copy.deepcopy(f["comparison"]["files"][0]))
    f["pr"]["changed_files"]=2
    assert gate.assess(**f)["status"]=="BLOCKED"

@pytest.mark.parametrize("kind", ["draft", "closed", "stacked", "fork", "prd", "contract", "ci",
                                  "policy", "deleted", "rename", "multiple"])
def test_automatic_route_non_applicable_never_authorizes(kind):
    f=fixture()
    pr, cmp=f["pr"], f["comparison"]
    if kind=="draft": pr["draft"]=True
    elif kind=="closed": pr["state"]="closed"
    elif kind=="stacked": pr["base"]["ref"]="docs/parent"
    elif kind=="fork": pr["head"]["repo"]={"full_name":"other/repo"}
    elif kind in ("prd","contract","ci","policy"):
        cmp["files"][0]["filename"]={"prd":"docs/product/PRD.md",
            "contract":"docs/architecture/contract-registry.json",
            "ci":".github/workflows/quality-gate.yml","policy":"AGENT_GITFLOW_RULES.md"}[kind]
    elif kind=="deleted": cmp["files"][0]["status"]="removed"
    elif kind=="rename": cmp["files"][0]["previous_filename"]="old.md"
    elif kind=="multiple":
        cmp["files"].append({"filename":"AGENTS.md","status":"modified"})
        pr["changed_files"]=2
    report=gate.route_candidate(pr, BASE, cmp)
    assert report["status"]=="NOT_APPLICABLE"
    assert report["merge_authorized"] is False
    assert report["codex_comment_id"] is None
    assert gate.assess(**f)["status"]=="BLOCKED"


def test_pilot_route_is_not_evidence_ready_even_with_valid_diff():
    f=fixture()
    assert gate.route_candidate(f["pr"], BASE)["status"]=="NEEDS_DIFF"
    report=gate.route_candidate(f["pr"], BASE, f["comparison"])
    assert report["status"]=="ELIGIBLE"
    assert report["merge_authorized"] is False
    assert report["codex_comment_id"] is None


@pytest.mark.parametrize("kind", ["missing_diff", "truncated_diff", "malformed_diff", "unknown_draft"])
def test_automatic_route_missing_information_fails_closed(kind):
    f=fixture()
    if kind=="missing_diff": del f["comparison"]["files"]
    elif kind=="truncated_diff": f["pr"]["changed_files"]=2
    elif kind=="malformed_diff": f["comparison"]["files"]=[{}]
    elif kind=="unknown_draft": del f["pr"]["draft"]
    assert gate.route_candidate(f["pr"],BASE,f["comparison"])["status"]=="BLOCKED"


@pytest.mark.parametrize("route,status,exit_code", [
    (True,"NOT_APPLICABLE",0),(True,"ELIGIBLE",0),(True,"BLOCKED",1),
    (False,"NOT_APPLICABLE",1),(False,"EVIDENCE_READY",0),(False,"BLOCKED",1)])
def test_cli_distinguishes_routing_from_strict_audit(monkeypatch, route, status, exit_code):
    argv=["review-evidence-gate.py","--pr","351","--head",HEAD]
    if route: argv.append("--route")
    monkeypatch.setattr(gate.sys,"argv",argv)
    monkeypatch.setattr(gate,"live_route",lambda *_: {"status":status,"merge_authorized":False})
    monkeypatch.setattr(gate,"live",lambda *_: {"status":status,"merge_authorized":False})
    assert gate.main()==exit_code


def test_live_routing_rejects_snapshot_change(monkeypatch):
    f=fixture()
    start=f["pr"]
    final=copy.deepcopy(start)
    final["draft"]=True
    snapshots=iter([start,final])
    monkeypatch.setattr(gate,"trusted_checkout",lambda _: (None,BASE))
    def fake_api(endpoint):
        if "/pulls/" in endpoint: return next(snapshots)
        if "/compare/" in endpoint: return f["comparison"]
        raise AssertionError(endpoint)
    monkeypatch.setattr(gate,"api",fake_api)
    with pytest.raises(RuntimeError,match="changed during routing"):
        gate.live_route(351,HEAD)


def test_workflow_routes_automatic_only_and_does_not_mask_failures():
    text=(Path(__file__).parents[3]/".github/workflows/review-evidence-audit.yml").read_text()
    assert "id: route" in text and "--route --pr" in text
    assert "NOT_APPLICABLE" in text and "applicable=false" in text
    assert "if: steps.route.outputs.applicable == 'true'" in text
    assert "continue-on-error" not in text
    assert "No approval granted" in text
    assert 'if [[ "$EVENT_NAME" == workflow_dispatch ]]' in text
