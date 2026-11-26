import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("remote_audit", Path(__file__).resolve().parents[1] / "audit-remote-branches.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
REPO = "owner/repo"

def branch(name="feat/one", sha="a", protected=False):
    return {"name": name, "commit": {"sha": sha}, "protected": protected}

def pull(state="closed", head="feat/one", sha="a", base="main", merged=True, head_repo=REPO):
    return {"number": 1, "state": state, "merged_at": "date" if merged else None,
            "merge_commit_sha": "b", "head": {"ref": head, "sha": sha, "repo": {"full_name": head_repo}},
            "base": {"ref": base, "repo": {"full_name": REPO}}}

def decision(b, pulls, ancestor=lambda sha: sha == "b"):
    return audit.classify(b, pulls, REPO, "main", ancestor)[0]

def test_squash_receipt_matches_exact_head_and_published_merge():
    assert decision(branch(), [pull()]) == "MERGED_EXACT_HEAD_REVIEW_DELETE"
    assert decision(branch(sha="new"), [pull()]) == "KEEP_UNPROVEN_REVIEW"
    assert decision(branch(), [pull()], lambda sha: False) == "KEEP_UNPROVEN_REVIEW"

def test_open_source_or_stacked_base_blocks_cleanup():
    assert decision(branch(), [pull(state="open")]) == "KEEP_OPEN_PR_OR_BASE"
    assert decision(branch(), [pull(state="open", head="feat/child", base="feat/one")]) == "KEEP_OPEN_PR_OR_BASE"

def test_closed_unmerged_fork_and_protected_never_imply_deletion():
    assert decision(branch(), [pull(merged=False)]) == "KEEP_UNPROVEN_REVIEW"
    assert decision(branch(), [pull(head_repo="fork/repo")]) == "KEEP_UNPROVEN_REVIEW"
    for name in ("main", "release/v1", "hotfix/v1", "coord/external-qa"):
        assert decision(branch(name), [], lambda sha: True) == "KEEP_PROTECTED_OR_SERVICE"
    assert decision(branch(protected=True), [], lambda sha: True) == "KEEP_PROTECTED_OR_SERVICE"

def test_reachable_and_unknown():
    assert decision(branch(), [], lambda sha: True) == "REACHABLE_REVIEW_DELETE"
    assert decision(branch(), []) == "KEEP_UNPROVEN_REVIEW"
