#!/usr/bin/env bash
# SEC-FIX (CWE-78): CI expression injection. `github.head_ref` is
# attacker-controlled and Git permits `$`, `(`, `` ` ``, `;` in ref names, so
# textually interpolating it into a workflow `run:` body executes arbitrary
# shell on the runner. It must be passed through `env:` (data), never inline
# (code). This test guards that regression both statically and dynamically.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_ci_expression_injection

wf="$REPO_ROOT/.github/workflows/gitflow-policy.yml"
[ -f "$wf" ] || fail "gitflow-policy.yml not found at $wf"

# --- static: no expression interpolation inside a run:/script: body --------
python3 - "$wf" <<'PY' || exit 1
import sys
try:
    import yaml
except ImportError:
    sys.exit(0)  # no PyYAML -> skip the static guard, dynamic check still runs
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
bad = [
    f"{s.get('name')!r}[{f}]"
    for job in doc.get("jobs", {}).values()
    for s in job.get("steps", []) or []
    for f in ("run", "script")
    if isinstance(s.get(f), str) and "${{" in s[f]
]
if bad:
    print(f"FAIL: expression interpolation inside shell block(s): {bad}", file=sys.stderr)
    sys.exit(1)
PY
pass "no \${{ }} interpolation inside any run/script body"

# --- static: head_ref reaches the shell via env, not inline ----------------
grep -qF 'HEAD_REF: ${{ github.head_ref }}' "$wf" || fail "head_ref is not passed via env"
grep -qF 'BRANCH="${{ github.head_ref }}"' "$wf" && fail "head_ref is still interpolated inline"
pass "head_ref passed via env (no inline interpolation)"

# --- dynamic: a hostile ref is data, never code ---------------------------
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ci-inject.XXXXXX")"
_TMP_DIRS+=("$tmp")

script="$(python3 - "$wf" <<'PY'
import sys
import yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for job in doc["jobs"].values():
    for s in job.get("steps", []) or []:
        if str(s.get("name", "")).startswith("Resolve branch name"):
            print(s["run"], end="")
            sys.exit(0)
sys.exit(1)
PY
)" || fail "could not extract the 'Resolve branch name' step"

for hostile in 'feat/a$(touch pwned)' 'feat/a`touch pwned`' 'feat/a;touch pwned'; do
    out="$tmp/gh_output"
    : >"$out"
    rm -f "$tmp/pwned"
    (
        cd "$tmp" && \
        EVENT_NAME=pull_request HEAD_REF="$hostile" \
        BASE_SHA=0000000000000000000000000000000000000000 \
        GITHUB_OUTPUT="$out" bash -c "$script"
    ) || fail "resolve step failed for hostile ref: $hostile"
    [ -e "$tmp/pwned" ] && fail "hostile ref was EXECUTED as shell: $hostile"
    grep -qF "branch=$hostile" "$out" || fail "hostile ref not preserved as data: $hostile"
done
pass "hostile branch names are treated as data (no code execution)"
