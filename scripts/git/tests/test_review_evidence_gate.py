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
    required=["quality gate","gitflow required checks"]
    return dict(pr=pr,main=BASE,comparison={"behind_by":0,"ahead_by":1,"merge_base_commit":{"sha":BASE}},
                files=[{"filename":next(iter(gate.PILOT_PATHS)),"status":"added"}],
                comments=comments,reviews=[],threads=[],required=required,
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
    elif change=="policy_change": f["files"][0]["filename"]="AGENT_GITFLOW_RULES.md"
    elif change=="deleted_file": f["files"][0]["status"]="removed"
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
