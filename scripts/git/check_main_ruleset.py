#!/usr/bin/env python3
"""Read-only auditor for the LIVE GitHub main ruleset (Issue #44).

No writes, no tokens in output, and no automatic exception/bypass acceptance.
Snapshot mode is for regression/rehearsal only; only --live verifies current
repository configuration. A red result is a governance blocker, not an
instruction to weaken GitHub settings.
"""
from __future__ import annotations

import argparse
import json
import fnmatch
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = "askarahodov/multi-agent-workflow"
MAIN = "refs/heads/main"
REQUIRED_CHECKS_PATH = Path("tests/gitflow/required-checks.txt")


def expected_contexts(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    contexts = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not contexts or len(contexts) != len(set(contexts)):
        raise ValueError("required-checks inventory is empty or contains duplicates")
    return set(contexts)


def audit_ruleset(data: Any, expected: set[str]) -> dict[str, Any]:
    """Return deterministic findings without trusting a stale local snapshot."""
    failures: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return {"ok": False, "failures": ["ruleset response is not an object"],
                "warnings": [], "required_checks": [], "missing_checks": sorted(expected)}

    if data.get("target") != "branch":
        failures.append("ruleset must target branches")
    if data.get("enforcement") != "active":
        failures.append("ruleset must be active")
    conditions = data.get("conditions")
    ref = conditions.get("ref_name") if isinstance(conditions, dict) else None
    includes = ref.get("include") if isinstance(ref, dict) else None
    excludes = ref.get("exclude") if isinstance(ref, dict) else None
    if not isinstance(includes, list) or MAIN not in includes:
        failures.append("main is not explicitly included")
    if not isinstance(excludes, list) or any(
        not isinstance(v, str)
        or v in ("~ALL", "~DEFAULT_BRANCH")
        or fnmatch.fnmatchcase(MAIN, v)
        for v in excludes
    ):
        failures.append("main may be excluded or exclusions are malformed")
    bypass = data.get("bypass_actors")
    if bypass != []:
        failures.append("ruleset has bypass actors or bypass inventory is unreadable")

    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
        failures.append("rules are missing or malformed")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("type"), str):
            by_type.setdefault(rule["type"], []).append(rule)
    for rule_type in ("deletion", "non_fast_forward"):
        if not by_type.get(rule_type):
            failures.append(f"missing {rule_type} protection")

    pulls = by_type.get("pull_request", [])
    if len(pulls) != 1:
        failures.append("exactly one pull_request rule required")
    params = pulls[0].get("parameters") if len(pulls) == 1 else None
    if not isinstance(params, dict):
        params = {}
    approvals = params.get("required_approving_review_count")
    if type(approvals) is not int or approvals < 1:
        failures.append("independent PR approval is not required (count < 1)")
    if params.get("dismiss_stale_reviews_on_push") is not True:
        failures.append("stale PR approvals are not dismissed on push")
    if params.get("required_review_thread_resolution") is not True:
        failures.append("unresolved review threads do not block merge")
    if params.get("require_last_push_approval") is not True:
        warnings.append("last-push approval is not enforced; assess actor separation")

    check_rules = by_type.get("required_status_checks", [])
    if len(check_rules) != 1:
        failures.append("exactly one required_status_checks rule required")
    ck = check_rules[0].get("parameters") if len(check_rules) == 1 else None
    if not isinstance(ck, dict):
        ck = {}
    entries = ck.get("required_status_checks")
    names: list[str] = []
    if not isinstance(entries, list):
        failures.append("required status check inventory missing")
    else:
        for entry in entries:
            name = entry.get("context") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name.strip():
                failures.append("invalid required check entry")
            else:
                names.append(name)
    if len(names) != len(set(names)):
        failures.append("duplicate required status checks")
    missing = sorted(expected - set(names))
    if missing:
        failures.append("required checks absent: " + ", ".join(missing))
    if ck.get("strict_required_status_checks_policy") is not True:
        warnings.append("strict up-to-date branch policy is off; confirm stale-branch behavior")

    return {
        "ok": not failures,
        "ruleset_id": data.get("id"),
        "enforcement": data.get("enforcement"),
        "required_approvals": approvals,
        "required_checks": sorted(set(names)),
        "missing_checks": missing,
        "failures": failures,
        "warnings": warnings,
    }


def load_live(repo: str, ruleset_id: int) -> Any:
    # gh auth handles authentication; never capture or print token values.
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/rulesets/{ruleset_id}"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("GitHub ruleset read failed (gh auth, repo access or network)")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub ruleset returned invalid JSON") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument("--live", action="store_true", help="read current GitHub ruleset using gh api")
    origin.add_argument("--snapshot", type=Path, help="offline rehearsal only")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--ruleset-id", type=int, default=26129824)
    parser.add_argument("--required-checks-file", type=Path, default=REQUIRED_CHECKS_PATH)
    args = parser.parse_args(argv)
    try:
        expected = expected_contexts(args.required_checks_file)
        data = load_live(args.repo, args.ruleset_id) if args.live else json.loads(
            args.snapshot.read_text(encoding="utf-8")
        )
        result = audit_ruleset(data, expected)
        result["mode"] = "live" if args.live else "offline_snapshot_NOT_live_evidence"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = {"ok": False, "mode": "live" if args.live else "offline_snapshot_NOT_live_evidence",
                  "failures": [str(exc)], "warnings": []}
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
