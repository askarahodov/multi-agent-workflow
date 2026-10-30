#!/usr/bin/env bash
# GF-09: the merge gate must be wired, complete and internally consistent.
#
# Verifies, statically and offline:
#   * the CI workflow defines the policy, isolation and required-checks jobs;
#   * the workflow's required-check list covers every context the main-branch
#     ruleset requires (tests/gitflow/required-checks.txt is the mirror of the
#     live ruleset; set GITFLOW_LIVE_RULESET=1 to also diff against GitHub);
#   * the policy registry version matches the JSON schema (full semver);
#   * all ten rules GF-01..GF-10 are present in the registry.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_required_checks_gate

workflow="$REPO_ROOT/.github/workflows/gitflow-policy.yml"
fixture="$TEST_DIR/required-checks.txt"

[ -f "$workflow" ] || fail "CI workflow $workflow is missing"
[ -f "$fixture" ] || fail "required-checks fixture is missing"

for needle in "policy-compliance" "worktree-isolation" "required-checks-gate" \
              "Verify all required checks are green"; do
    assert_contains "$workflow" "$needle" "workflow misses '$needle'" 1
done
pass "CI workflow defines the gitflow policy, isolation and required-checks jobs"

# --- required contexts must all be enforced by the gate -------------------
missing=0
while IFS= read -r ctx; do
    [ -z "$ctx" ] && continue
    if ! grep -qF -- "$ctx" "$workflow"; then
        echo "missing required context: $ctx" | tee -a "$TEST_LOG"
        missing=1
    fi
done <"$fixture"
[ "$missing" -eq 0 ] || fail "the required-checks gate does not enforce every required context"
pass "required-checks gate covers all $(grep -c . "$fixture") contexts"

# --- policy registry integrity ------------------------------------------
python3 - "$REPO_ROOT" <<'PY' || exit 1
import json, re, sys
root = sys.argv[1]
text = open(f"{root}/AGENT_GITFLOW_RULES.md", encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
assert m, "AGENT_GITFLOW_RULES.md has no YAML front-matter"
fm = m.group(1)
version = re.search(r"^\s*version:\s*['\"]?([\w.\-]+)['\"]?\s*$", fm, re.MULTILINE)
assert version, "policy front-matter has no version"
rules = re.findall(r"-\s*id:\s*(GF-\d{2})", fm)
assert sorted(rules) == [f"GF-{i:02d}" for i in range(1, 11)], rules
schema = json.load(open(f"{root}/gitflow-policy.schema.json", encoding="utf-8"))

def semver(value):
    mm = re.match(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?\s*$", str(value))
    return (int(mm.group(1)), int(mm.group(2)), int(mm.group(3) or 0)) if mm else None

assert semver(version.group(1)) == semver(schema.get("version")), (
    f"version drift: rules={version.group(1)} schema={schema.get('version')}")
PY
pass "policy registry version matches the schema; GF-01..GF-10 present"

# --- optional: diff against the live ruleset ----------------------------
if [ "${GITFLOW_LIVE_RULESET:-0}" = "1" ]; then
    command -v gh >/dev/null 2>&1 || fail "GITFLOW_LIVE_RULESET=1 but gh is unavailable"
    live="$(gh api repos/askarahodov/multi-agent-workflow/rulesets/26129824 \
        --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context' \
        2>>"$TEST_LOG" | sort)" || fail "unable to read the live ruleset"
    echo "$live" >"$TEST_LOG.live"
    if ! diff -u <(sort "$fixture") "$TEST_LOG.live" >>"$TEST_LOG"; then
        fail "live ruleset contexts differ from tests/gitflow/required-checks.txt"
    fi
    pass "live ruleset matches the required-checks fixture"
fi
