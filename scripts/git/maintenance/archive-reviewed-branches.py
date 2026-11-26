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
BASELINE = "6e47938df1f94e783f266c8210de5c92e8c20058"
TIPS = {
    "ci/pr-run-concurrency": "60261effc5f3f5ed2bdd2e0cdad22e146a41f576",
    "dependabot/uv/services/runtime-hardening/hardening/uv-5b7683a66b": "be795c962f92528d6db0ac449ce31816a11ea614",
    "fix/agent-profile-completion-254": "ea897ca35f43f29418677cae45d6c46550682cb7",
    "fix/provider-create-settings-ux": "9c54ea830904c0ea293d0fc944176f1d9cae418d",
    "fix/provider-create-reliable-254": "d0edf9874dfeedb2e9a469b80af1ed341a585fb2",
    "fix/setup-wizard-partial-failure-ux": "0ed3fb303b0aa566e5625501c80c043d37286533",
    "security/issue-209-stream-ticket-e2e": "94964b7dbcf2f5824df95763ff9aec6ffd74bda3",
    "fix/issue-256-run-launch-consistency": "8b6dfe1f1e0a382d0d9d6ec74b3c7afea971b296",
    "test/issue-11-native-qa-failure-release-block": "d5e8ca0e5d50a6df81b4879f17aa3af491a07b2a",
    "integration/p0-product-user-journey-2026-11-09": "7a7e64d97feb02781ea7dbfbd5819edce541cc21",
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


def validate_context():
    if (os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or
            os.environ.get("GITHUB_REF") != "refs/heads/main" or
            os.environ.get("GITHUB_REPOSITORY", "").lower() != REPO):
        raise RuntimeError("Maintenance is restricted to manual dispatch on this repository's main")
    main = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", main) or run("git", "rev-parse", "HEAD").strip() != main:
        raise RuntimeError("Checkout does not match dispatch SHA")
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


def verify_archive(directory, main):
    bundle = directory / "branches.bundle"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected = expected_refs(main)
    if (manifest.get("repository") != REPO or manifest.get("baseline") != BASELINE or
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


def archive(directory, main):
    directory.mkdir(parents=True, exist_ok=False)
    expected = expected_refs(main)
    specs = [f"refs/heads/{name}:{REF_PREFIX}{name}" for name in {**TIPS, "main": main}]
    run("git", "fetch", "--no-tags", "origin", *specs)
    if refs(run("git", "for-each-ref", "--format=%(objectname) %(refname)", REF_PREFIX)) != expected:
        raise RuntimeError("Fetched archive refs changed")
    bundle = directory / "branches.bundle"
    run("git", "bundle", "create", str(bundle), *expected)
    manifest = {"repository": REPO, "baseline": BASELINE, "main": main,
                "refs": expected, "sha256": digest(bundle),
                "run_id": os.environ["GITHUB_RUN_ID"]}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_archive(directory, main)
    check(main)
    print(f"Archive verified: {len(TIPS)} branches, main {main}; SHA256 {manifest['sha256']}")


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
    parser.add_argument("mode", choices=["archive", "apply"])
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--archive-run", default="")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()
    main_sha = validate_context()
    check(main_sha)
    if args.mode == "archive":
        archive(args.directory, main_sha)
    else:
        apply(args.directory, main_sha, args.archive_run, args.confirmation)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError, OSError, ValueError, KeyError) as exc:
        # No automatic retry after an ambiguous network/write result.
        raise SystemExit(f"BLOCKED: {exc}. Re-read remote refs before retrying.")
