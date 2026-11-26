#!/usr/bin/env python3
"""Read-only remote GitHub branch audit; never deletes refs.

Run using a read-only GH_TOKEN or authenticated gh CLI.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone

KEEP_NAMES = {"main", "master", "develop"}
KEEP_PREFIXES = ("release/", "hotfix/", "coord/")


def api(endpoint, paginated=False):
    cmd = ["gh", "api"]
    if paginated:
        cmd += ["--paginate", "--slurp"]
    raw = json.loads(subprocess.run([*cmd, endpoint], check=True, capture_output=True, text=True).stdout)
    return [item for page in raw for item in page] if paginated else raw


def same_repo(ref, repo):
    return (ref.get("repo") or {}).get("full_name", "").lower() == repo.lower()


def classify(branch, pulls, repo, default, ancestor):
    name = branch["name"]
    sha = branch["commit"]["sha"]
    related = [p for p in pulls if
        (same_repo(p["head"], repo) and p["head"]["ref"] == name) or
        (same_repo(p["base"], repo) and p["base"]["ref"] == name)]
    open_prs = [p["number"] for p in related if p["state"] == "open"]
    if branch.get("protected") or name == default or name in KEEP_NAMES or name.startswith(KEEP_PREFIXES):
        return "KEEP_PROTECTED_OR_SERVICE", open_prs
    if open_prs:
        return "KEEP_OPEN_PR_OR_BASE", open_prs
    # Exact head only: a newer commit on a previously merged branch is unique
    # work until proven otherwise. Squash merges require the PR merge receipt.
    for p in related:
        if (p.get("merged_at") and same_repo(p["head"], repo) and
                p["head"]["ref"] == name and p["head"]["sha"] == sha and
                same_repo(p["base"], repo) and p["base"]["ref"] == default and
                p.get("merge_commit_sha") and ancestor(p["merge_commit_sha"])):
            return "MERGED_EXACT_HEAD_REVIEW_DELETE", [p["number"]]
    if ancestor(sha):
        return "REACHABLE_REVIEW_DELETE", []
    return "KEEP_UNPROVEN_REVIEW", [p["number"] for p in related]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    repo = args.repo
    meta = api(f"repos/{repo}")
    default = meta["default_branch"]
    branches = api(f"repos/{repo}/branches?per_page=100", True)
    pulls = api(f"repos/{repo}/pulls?state=all&per_page=100", True)
    main_sha = next(b["commit"]["sha"] for b in branches if b["name"] == default)
    def ancestor(sha):
        try:
            result = api(f"repos/{repo}/compare/{sha}...{main_sha}")
        except subprocess.CalledProcessError:
            # Missing common ancestor, permission or API failure is not proof.
            return False
        return result.get("status") in ("ahead", "identical") and result.get("behind_by") == 0

    rows = []
    for branch in branches:
        disposition, prs = classify(branch, pulls, repo, default, ancestor)
        rows.append({"branch": branch["name"], "sha": branch["commit"]["sha"], "decision": disposition, "prs": prs})
    print(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "main_sha": main_sha,
                      "delete_branch_on_merge": meta.get("delete_branch_on_merge"),
                      "count": len(rows), "branches": rows}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
