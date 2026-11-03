# GitFlow required checks job — fail-closed behavior (#44)

**State as of 2026-11-03:** the live GitHub `main` branch ruleset
`26129824` requires 14 status contexts. That **server-side ruleset remains
the merge authority**. This job (`gitflow required checks`) is an additional
diagnostic and is not itself among those 14 required contexts. Its green state
alone does **not** mean a PR is approved or mergeable.

## Purpose and behavior

The previous `.github/workflows/gitflow-policy.yml` job emitted warnings
rather than failures for missing/in-progress checks, and treated
`skipped`/`neutral` as acceptable. Consequently it could finish green
before all required checks actually completed.

The updated job:

1. Starts after `gitflow policy validation` and `gitflow worktree isolation`,
   reads exact PR `head.sha` and paginates GitHub check-runs.
2. Polls all 14 required names (inline list mirrors
   `tests/gitflow/required-checks.txt`) with a bounded 80 × 15-second loop.
   Missing or still-running checks remain **waiting**, not success.
3. Returns `success` only for `status=completed, conclusion=success`
   on **every** required check. `skipped`, `neutral`, `cancelled`,
   `timed_out`, `failure`, malformed statuses and contradictory duplicate
   runs are **blocked**. Any nonterminal check past the poll bound fails.
4. Uses read-only `checks: read` permission, no production secrets,
   no write to branches and `persist-credentials: false` during checkout.
   The pure Node classifier is covered by a separate offline regression test.
   There are no third-party npm dependencies in the classifier.

## Test and incident commands

```bash
node --test scripts/git/required-checks-gate.test.cjs
bash tests/gitflow/test_required_checks_gate.sh
gh pr checks <PR_NUMBER>
gh api repos/askarahodov/multi-agent-workflow/rulesets/26129824 \
  --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
```

For a changed required context, update **both** the workflow inventory and
`tests/gitflow/required-checks.txt` after checking the real main ruleset
and recent PR check-runs. Do not remove a failing context to make a PR green.

If `gitflow required checks` is red, check the JSON check-run state and
the latest CI job logs. A timed-out wait means **unknown**, not an approval.
Do not bypass server rules. The local `main` policy audit is tracked by
[#44](https://github.com/askarahodov/multi-agent-workflow/issues/44);
independent approval remains a separate governance requirement. Changing
server-side ruleset settings needs a repository admin and an audited rollout.

## Scope

This remediation does not enable stream tickets, run OpenRouter, start a
host Kanban daemon, merge open PRs, or prove the seven-stage SDLC MVP. Green
CI is narrower than signed independent QA/reviewer/security acceptance.
