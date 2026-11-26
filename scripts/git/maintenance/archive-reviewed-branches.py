#!/usr/bin/env python3
"""Explicit two-run maintenance of the dated, reviewed branch cleanup set.

Archive is read-only. Apply requires a previously downloaded and verified
archive, a quiet repository and operator confirmation of all external worktrees.
Never run apply on a PR, a branch other than main, or via a schedule.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REPO = "askarahodov/multi-agent-workflow"
BASELINE = "780dd2af1c4f9dbeb50f6d2b22f6874788f8eb06"
BATCH = "historical-qa-worktrees-2026-11-26"
# The first ten-ref batch was applied in run 45810201195.
# Only the separately reviewed historical refs below are eligible now.
TIPS = {
    "qa-sync-test-1792050525": "1f0803be69379ca9ae0fc45583a8a9dc64c82260",
    "test-substance-components-1791965479": "c42b72f109d957f10689ae71a3810859375200ce",
    "test-workflows-1791891554": "3196848c91e6ac567a12e3b79728b3f4ad0ed3c7",
    "wt/t_1fd6385e": "bcda741376023262321b37222e0ee6f84a64e761",
    "wt/t_759fb8e6": "36fc1350a4d2bda507d34c21e513b88759c93763",
}
CONFIRM = "ARCHIVE_SAVED_WORKTREES_CHECKED"
REF_PREFIX = "refs/cleanup-archive/"


def run(*cmd):
    # Capture diagnostics rather than emitting Git authentication configuration.
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout


def api(endpoint, pages=False):
    args = ["gh", "api", "--hostname", "github.com"]
    if pages:
        args += ["--paginate", "--slurp"]
    result = json.loads(run(*args, endpoint))
    if pages:
        if not isinstance(result, list) or not all(isinstance(p, list) for p in result):
            raise RuntimeError("Unexpected API pagination")
        return [item for page in result for item in page]
    return result


def refs(text):
    result = {}
    for line in text.splitlines():
        sha, ref = line.split()
        if ref in result or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError("Invalid ref response")
        result[ref] = sha
    return result


def same_repo(ref):
    return (ref.get("repo") or {}).get("full_name", "").lower() == REPO


def validate_snapshot(branches, pulls, remote, main):
    by_name = {b["name"]: b for b in branches}
    if (remote.get("refs/heads/main") != main or
            by_name.get("main", {}).get("commit", {}).get("sha") != main):
        raise RuntimeError("Main changed; repeat the audit and archive")
    used = {p[k]["ref"] for p in pulls if p["state"] == "open"
            for k in ("head", "base") if same_repo(p[k])}
    for name, expected in TIPS.items():
        row = by_name.get(name, {})
        if row.get("protected") is not False:
            raise RuntimeError(f"Protection unknown or enabled: {name}")
        if row.get("commit", {}).get("sha") != expected or remote.get("refs/heads/" + name) != expected:
            raise RuntimeError(f"Ref missing or moved: {name}")
        if name in used:
            raise RuntimeError(f"Open PR head/base: {name}")


def validate_context(rehearsal=False):
    event = os.environ.get("GITHUB_EVENT_NAME")
    ref = os.environ.get("GITHUB_REF", "")
    if os.environ.get("GITHUB_REPOSITORY", "").lower() != REPO:
        raise RuntimeError("Unexpected repository")
    checkout = os.environ.get("GITHUB_SHA", "")
    if rehearsal:
        if event != "pull_request" or not re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", ref):
            raise RuntimeError("Rehearsal requires a same-repository PR merge checkout")
        pr = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))["pull_request"]
        if (not same_repo(pr["head"]) or not same_repo(pr["base"]) or
                pr["base"]["ref"] != "main" or ref != f"refs/pull/{pr['number']}/merge"):
            raise RuntimeError("Rehearsal requires a same-repository PR into main")
        main = pr["base"]["sha"]
    else:
        if event != "workflow_dispatch" or ref != "refs/heads/main":
            raise RuntimeError("Maintenance is restricted to manual dispatch on this repository's main")
        main = checkout
    if (not re.fullmatch(r"[0-9a-f]{40}", checkout) or
            not re.fullmatch(r"[0-9a-f]{40}", main) or
            run("git", "rev-parse", "HEAD").strip() != checkout):
        raise RuntimeError("Checkout does not match event SHA")
    if run("git", "rev-parse", "--is-shallow-repository").strip() != "false":
        raise RuntimeError("Full history required")
    allowed = {f"https://github.com/{REPO}", f"https://github.com/{REPO}.git"}
    for flags in ([], ["--push", "--all"]):
        urls = run("git", "remote", "get-url", *flags, "origin").splitlines()
        if len(urls) != 1 or urls[0] not in allowed:
            raise RuntimeError("Unexpected remote URL")
    meta = api(f"repos/{REPO}")
    if meta.get("full_name", "").lower() != REPO or meta.get("default_branch") != "main":
        raise RuntimeError("Repository identity changed")
    run("git", "merge-base", "--is-ancestor", BASELINE, main)
    run("git", "merge-base", "--is-ancestor", main, checkout)
    return main


def check(main):
    branches = api(f"repos/{REPO}/branches?per_page=100", True)
    pulls = api(f"repos/{REPO}/pulls?state=open&per_page=100", True)
    remote = refs(run("git", "ls-remote", "--heads", "origin"))
    validate_snapshot(branches, pulls, remote, main)


def expected_refs(main):
    return {REF_PREFIX + n: s for n, s in {**TIPS, "main": main}.items()}


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def verify_archive(directory, main, purpose="archive"):
    bundle = directory / "branches.bundle"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected = expected_refs(main)
    if (manifest.get("repository") != REPO or manifest.get("baseline") != BASELINE or
            manifest.get("purpose") != purpose or manifest.get("batch") != BATCH or
            manifest.get("main") != main or manifest.get("refs") != expected or
            manifest.get("sha256") != digest(bundle)):
        raise RuntimeError("Archive manifest, baseline, main, refs or checksum mismatch")
    if refs(run("git", "bundle", "list-heads", str(bundle))) != expected:
        raise RuntimeError("Bundle head mismatch")
    # Restore into an empty bare repository: a thin bundle or a corrupt pack
    # cannot pass merely because the current checkout has its prerequisites.
    with tempfile.TemporaryDirectory(prefix="reviewed-branch-restore-") as tmp:
        run("git", "init", "--bare", tmp)
        run("git", "-C", tmp, "bundle", "verify", str(bundle.resolve()))
        run("git", "-C", tmp, "-c", "fetch.fsckObjects=true", "fetch", "--no-tags",
            str(bundle.resolve()), f"{REF_PREFIX}*:{REF_PREFIX}*")
        restored = refs(run("git", "-C", tmp, "for-each-ref",
                            "--format=%(objectname) %(refname)", REF_PREFIX))
        if restored != expected:
            raise RuntimeError("Restored archive refs mismatch")
    if manifest.get("run_id") is None:
        raise RuntimeError("Missing archive run identity")
    return manifest


def archive(directory, main, purpose="archive"):
    directory.mkdir(parents=True, exist_ok=False)
    expected = expected_refs(main)
    specs = [f"refs/heads/{name}:{REF_PREFIX}{name}" for name in {**TIPS, "main": main}]
    run("git", "fetch", "--no-tags", "origin", *specs)
    if refs(run("git", "for-each-ref", "--format=%(objectname) %(refname)", REF_PREFIX)) != expected:
        raise RuntimeError("Fetched archive refs changed")
    bundle = directory / "branches.bundle"
    run("git", "bundle", "create", str(bundle), *expected)
    manifest = {"repository": REPO, "baseline": BASELINE, "main": main,
                "refs": expected, "sha256": digest(bundle), "purpose": purpose, "batch": BATCH,
                "run_id": os.environ["GITHUB_RUN_ID"]}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_archive(directory, main, purpose=purpose)
    check(main)
    print(f"{purpose} verified: {len(TIPS)} branches, main {main}; SHA256 {manifest['sha256']}")


def delete_command():
    return ["git", "push", "--atomic",
            *[f"--force-with-lease=refs/heads/{name}:{tip}" for name, tip in TIPS.items()],
            "origin", *[f":refs/heads/{name}" for name in TIPS]]


def apply(directory, main, archive_run, confirmation):
    if confirmation != CONFIRM or not re.fullmatch(r"[1-9][0-9]{0,19}", archive_run):
        raise RuntimeError("Explicit operator confirmation and a prior archive run ID required")
    if archive_run == os.environ.get("GITHUB_RUN_ID"):
        raise RuntimeError("Archive must come from a previous successful run")
    info = api(f"repos/{REPO}/actions/runs/{archive_run}")
    if (info.get("event") != "workflow_dispatch" or info.get("head_branch") != "main" or
            info.get("head_sha") != main or info.get("conclusion") != "success" or
            info.get("path") != ".github/workflows/branch-cleanup.yml"):
        raise RuntimeError("Archive run is not a successful matching main dispatch")
    manifest = verify_archive(directory, main)
    if str(manifest["run_id"]) != archive_run:
        raise RuntimeError("Archive run ID mismatch")
    check(main)
    # Atomic deletion with leases; no partial or unleased fallback.
    run(*delete_command())
    after = refs(run("git", "ls-remote", "--heads", "origin"))
    remaining = [name for name in TIPS if "refs/heads/" + name in after]
    if remaining:
        raise RuntimeError("Refs still present: " + ", ".join(remaining))
    print(f"Verified remote absence: {len(TIPS)} branches; local developer worktrees are unchanged")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["archive", "rehearse", "apply"])
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--archive-run", default="")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()
    rehearsal = args.mode == "rehearse"
    main_sha = validate_context(rehearsal=rehearsal)
    check(main_sha)
    if args.mode in ("archive", "rehearse"):
        archive(args.directory, main_sha, purpose="rehearsal" if rehearsal else "archive")
    else:
        apply(args.directory, main_sha, args.archive_run, args.confirmation)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError, OSError, ValueError, KeyError) as exc:
        # No automatic retry after an ambiguous network/write result.
        raise SystemExit(f"BLOCKED: {exc}. Re-read remote refs before retrying.")
