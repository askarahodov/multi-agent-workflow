# GitFlow enforcement — implementation evidence (task t_5ba84eb3)

Branch: `wt/t_5ba84eb3` · Repo worktree: `/mnt/data/multi-agent-workflow/.worktrees/t_5ba84eb3`

## Deliverables

| # | Deliverable | Path | Status |
|---|-------------|------|--------|
| 1 | pre-commit hook (commit format, branch pattern, no direct main/develop commits) | `scripts/git/gitflow-hooks/pre-commit` | ✅ |
| 1b | commit-msg hook (belt-and-braces GF-04) | `scripts/git/gitflow-hooks/commit-msg` | ✅ |
| 2 | pre-push hook (protected-branch block, force-push block, squash-merge block, CI-green) | `scripts/git/gitflow-hooks/pre-push` | ✅ |
| 2b | post-merge hook (cleanup trigger GF-06/GF-10) | `scripts/git/gitflow-hooks/post-merge` | ✅ |
| 3 | CI workflow `.github/workflows/gitflow-policy.yml` | policy compliance + required checks + worktree isolation | ✅ |
| 4 | Hermes dispatcher policy injection | `scripts/git/gitflow_context.py`, `scripts/git/dispatcher-policy-hook.sh`, wired into `scripts/git/worktree-lifecycle.py` and `tools/agent-orchestration/scripts/spawn-agent.sh` | ✅ |
| 5 | Worktree manager | `scripts/git/worktree-lifecycle.py` (`create`/`validate`/`cleanup --force-guard`/`reap`) | ✅ |
| 6 | Machine-parseable policy | `AGENT_GITFLOW_RULES.md` YAML front-matter + `gitflow-policy.schema.json` | ✅ |

Also: `scripts/git/gitflow-hooks/gitflow-lib.sh` (shared helpers),
`scripts/git/gitflow-hooks/check_commits.py` (PR-range commit validation),
`scripts/install-gitflow-hooks.sh` (installer), `.gitignore` entries.

## Verification (real execution)

### Hook syntax + Python compile
```
bash -n  (gitflow-lib.sh, pre-commit, pre-push, commit-msg, post-merge,
          install-gitflow-hooks.sh, dispatcher-policy-hook.sh, spawn-agent.sh)  → all ok
python3 -m py_compile  (worktree-lifecycle.py, gitflow_context.py, check_commits.py) → ok
```

### pre-commit / commit-msg (throwaway repo, hooks installed)
```
T1 commit on main                       → exit 1  GF-05 (direct commit on protected)
T2 commit on wt/t_1234abcd valid msg    → exit 0  accepted
T3 commit message "wip"                 → exit 1  GF-04 invalid commit message
T4 commit on branch tmp-branch          → exit 1  GF-02 invalid branch name
```

### pre-push (throwaway repo)
```
T5 push refs/heads/main                 → exit 1  GF-05 refusing direct push to protected
T6 push refs/heads/wt/t_1234abcd        → exit 0  allowed
T7 push refs/heads/tmp-branch           → exit 1  GF-02 invalid branch name
T7b force-push refs/heads/develop       → exit 1  GF-05 refusing force-push to protected
```

### check_commits.py
```
valid range  main..HEAD                 → exit 0
range with "bad message" (non-conf.)    → exit 1  lists offending SHA + expected format
```

### Worktree lifecycle (`worktree-lifecycle.py`)
```
create   --task t_deadbeef              → branch wt/t_deadbeef + worktree + hooks + policy bundle
validate --task t_deadbeef              → {"valid": true, all 6 checks true}
cleanup  (dirty worktree)               → {"status":"blocked","reason":"uncommitted_work_guard"}
cleanup  (clean worktree)               → {"status":"cleaned","verified_clean":true}
cleanup  (branch with unique commits)   → {"status":"blocked","reason":"unmerged_commits_guard"}
cleanup  --force-guard                  → {"status":"cleaned","verified_clean":true}
reap                                    → {"orphans":[],"count":0}; never deletes
```

### Hermes policy injection (`gitflow_context.py`)
```
claim --task-id t_deadbeef --worktree X → writes AGENT_GITFLOW_CONTEXT.json (10 rules, v1.0)
                                          + .agent-gitflow.json {branch_name, policy_path, schema_path}
                                          + .githooks symlink + core.hooksPath=.githooks
                                          + --emit-env prints AGENT_GITFLOW_CONTEXT / _RULES_PATH / _SCHEMA_PATH
```
Verified in `worktree-lifecycle.py create` output: `"policy_injected": true`.

### Policy registry
```
JSON schema parses; jsonschema.validate(object, schema) → OK
AGENT_GITFLOW_RULES.md front-matter: version 1.0, 10 rule ids GF-01..GF-10
fallback parser (no PyYAML) parses 10 rules, version 1.0
version match rules 1.0 ↔ schema 1.0.0  → True
.github/workflows/gitflow-policy.yml    → valid YAML (write_file lint: ok)
```

## Constraints respected
- No push performed; no direct change to `main`/`develop`; no branch-protection ruleset changed.
- All changes on `wt/t_5ba84eb3` (GitFlow feature branch).
