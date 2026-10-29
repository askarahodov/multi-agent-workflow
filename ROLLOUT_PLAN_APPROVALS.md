# ROLLOUT_PLAN.md — Approval Ledger and Gate Status

**Document under review:** `ROLLOUT_PLAN.md` (repository root, this worktree)
**Frozen artifact:** `sha256 119eafb93a299c368580fe57d0280599de09a3e6f3a8d7b7166a6bef7820f511` (28 590 bytes, 434 lines)
**Produced by:** commit `a2f1e47` on `wt/t_d5a955b6` (card `t_d5a955b6`), copied byte-identically into this card's worktree.
**Ledger date:** 2026-10-29. **Compiled by:** sdlc-release (card `t_9ba6cd7a`).
**Overall gate status: READY_FOR_HUMAN_APPROVAL** — both mandatory independent gates (quality, security) are verified for the exact frozen artifact. This ledger does not approve the plan and does not authorize execution.

> The plan file itself is **frozen**. It is reproduced unmodified so that the hashes the reviewers
> approved remain valid. Approvals, provenance notes and gate status live in this separate file instead of
> being appended to the plan, because editing the plan would invalidate its review identity.

---

## 1. Artifact manifest

| Artifact | Path | sha256 | Produced by |
|---|---|---|---|
| Rollout plan (final candidate) | `ROLLOUT_PLAN.md` | `119eafb93a299c368580fe57d0280599de09a3e6f3a8d7b7166a6bef7820f511` | `t_d5a955b6` @ `a2f1e47` |
| Baseline snapshot (read-only) | `evidence/rollout-baseline-2026-10-29.json` | `f81a93869d1312623a8fb369feb9cda44b7210073f9778101402254c1fd3aa9c` | `t_d5a955b6` |
| Check-run inventory, PR #187 | `evidence/rollout-checkrun-inventory-pr187.json` | `e0e7b7006b643af372660517cf8eea92d01a01bcdf558f4b9c004c8e256f0a8d` | `t_d5a955b6` |
| Executive summary (one page) | `ROLLOUT_EXECUTIVE_SUMMARY.md` | see `git show <commit>:ROLLOUT_EXECUTIVE_SUMMARY.md \| sha256sum` (§5) | `t_9ba6cd7a` |
| This ledger | `ROLLOUT_PLAN_APPROVALS.md` | self-referential — pin by commit (§5); verify with `git show <commit>:ROLLOUT_PLAN_APPROVALS.md \| sha256sum` | `t_9ba6cd7a` |

Copies in other worktrees (`.worktrees/t_e527c2c3/ROLLOUT_PLAN.md`, `.worktrees/t_d5a955b6/ROLLOUT_PLAN.md`)
are snapshots, not authoritative. Only the root-level `ROLLOUT_PLAN.md` on the plan branch is authoritative
(plan header, lines 7–10).

---

## 2. Gate ledger

| # | Gate | Card | Verdict | Artifact actually reviewed | Covers final `119eafb9…`? |
|---|---|---|---|---|---|
| G1 | Quality review (blocking defects) | `t_cf1bc31e` | `changes_requested` — 9 verified blocking defects | draft `sha256 69b69006…` (44-line version) | No — superseded by the rework |
| G2 | Quality re-review (artifact lens) | `t_d5a955b6` | `approved` — all 10 blocking items closed; every check-context string, `file:line` citation and evidence hash re-verified against the repo and live GitHub | `sha256 119eafb9…` @ `a2f1e47` | **Yes** |
| G3 | Security review (first pass) | `t_ccd446d9` | `passed` — 4/4 mandatory areas | **draft** `sha256 69b69006…`, not the reworked file | **No — stale, superseded by G4** |
| G4 | Security re-review of final artifact | `t_a7116377` | **`passed`** — all 5 mandatory areas verified against the final file's own numbering; no secrets; read-only honored | `sha256 119eafb9…` (verified via `git show 707115a:ROLLOUT_PLAN.md`, identical bytes at `a2f1e47`); both evidence hashes re-verified | **Yes** |

**All mandatory gates covering the frozen artifact: PASSED (G2 + G4).**

### Why G3 was replaced (historical record)

The first security handoff (`t_ccd446d9`) described the plan with the **draft's section numbering**:

| Security handoff said | Draft (`69b69006…`) | Final (`119eafb9…`) |
|---|---|---|
| "Section 1 Shadow Mode" | §1 shadow mode | §1 = *Prerequisites P1–P7*; shadow is §3 |
| "Section 4 Emergency Bypass Procedure" | §4 bypass | §4 = *Required-check set (14 contexts)*; bypass/rollback is §6 |
| "Section 5 Metrics Dashboard" | §5 metrics | §5 = *Gradual enforcement, S1–S14*; metrics is §7 |
| "Section 6 Rollback Triggers" | §6 rollback | §6 = *Rollback* (numbering coincides, content differs) |

It therefore assessed the pre-rework draft that G1 rejected, and predated rework commit `a2f1e47`.
Per release policy (all gate results must refer to the same candidate and must not predate subsequent
changes) **G3 was stale and was not counted**. Card `t_a7116377` (sdlc-security, read-only) was created to
re-review the final artifact; it returned `passed` on `sha256 119eafb9…` and supersedes G3.

### G4 scope actually verified (from the `t_a7116377` handoff)

1. **Bypass auditability** — §6.2/§6.4: one-context read-modify-PUT, classic single-context DELETE/POST, no
   whole-ruleset deletion, owner → `sdlc-security` → `sdlc-reviewer` chain, 4 h budget, rows 5/6 attempt IDs.
2. **Rollback + FP precedence** — §6.1 triggers a–e with bands >20% / 5–20% / ≤5%; §6.3 P7 rehearsal on a
   throwaway branch with real PR/run IDs before S1.
3. **Warn-only shadow** — §3.1 (check-runs API + P2 telemetry artifact), §3.2 S-EXIT-1…5, explicit
   `main protected=false` / no required contexts during shadow.
4. **FP metric** — §3.3 before-allowlisting numerator/denominator, explicit never-scanned `SKIP_FILES`
   exclusion (verified `security.py:36`/`:94`), S-EXIT-2 ≤5%.
5. **Gated-step correctness** — §4.1 14 contexts (every name and `workflow:line` re-resolved), §5 aggregate
   `quality gate` enabled last (verified `quality-gate.yml:258 if:always()`, `:260 needs`), §9 G1–G4 + P6.

### TESTER gate

Not applicable and not claimed. The deliverable is a Markdown plan; it changes no code, workflow or
enforcement state. The plan's own execution steps are gated on P1–P7 and shadow exit (§1, §3.2, §9) and are
not executed by this card. `t_d5a955b6` and `t_a7116377` both re-verified that no enforcement/ruleset/CI
state was changed (`main` still `protected=false`, `rulesets []`).

---

## 3. Live re-verification (this card, read-only, 2026-10-29)

Commands and results observed while compiling this ledger:

```bash
gh api repos/askarahodov/multi-agent-workflow/branches/main \
  --jq '{protected:.protected,sha:.commit.sha}'
# {"protected":false,"sha":"e01efa18ae837c61c4f6dcdf3864fcfd926717c8"}

gh api repos/askarahodov/multi-agent-workflow/rulesets
# []

gh api repos/askarahodov/multi-agent-workflow/branches/main/protection
# 404 "Branch not protected"
```

This matches the frozen baseline `evidence/rollout-baseline-2026-10-29.json` byte-for-byte on every field it
records (`protected=false`, `rulesets=[]`, `HEAD=e01efa18…`, classic protection 404). **No enforcement state
was changed by this card**, and the re-verification was repeated after the G4 verdict with the same result.

---

## 4. Open items (none blocking the human gate)

**B1 — independent security review of the final plan: RESOLVED.** Card `t_a7116377` returned `passed` for
`sha256 119eafb9…`, covering exactly the scope previously listed (bypass auditability §6.2/§6.4, rollback
triggers and FP bands §6.1/§6.3, warn-only shadow §3.1/§3.2, metrics §7 + FP definition §3.3, gated-step
correctness §4.1/§5/§9).

**Non-blocking provenance note (open, recorded for audit):** the approved file's §3.4 (lines 149–151)
attributes the SEC-007 identifier to `SECURITY_AUDIT.md` (finding: stale/tampered policy bundles). That file
exists in the main working tree at 20 415 bytes but is **untracked**, so the citation is not durable in Git;
the tracked `docs/reviews/SECURITY-REPORT.md:159` uses SEC-007 for *fixture false positives*. The plan's
conclusion is unaffected (it explicitly removes the SEC-007 → fixture-FP attribution and bases the FP
mitigation on P4 code + tests), but the identifier collision should be fixed when `SECURITY_AUDIT.md` is
committed (card `t_de91cac5`). Accepted as-is by both reviewers; no enforcement impact.

**Pre-existing non-blocking hardening** carried from `EVIDENCE_BRIEF.md` §4 (must precede final enforcement,
not shadow): KEK production guard, WebSocket key transport, release-approval role elevation, TLS/HSTS tests
wired into per-service CI, `src/mvp/**` orphan disposition.

**Optional hardening notes from G4:** pin the rollback audit-ledger location explicitly; consider a dedicated
bypass/real-secret rollback trigger. Neither is required for the human gate.

---

## 5. Version-control record

| Fact | Value |
|---|---|
| Branch | `wt/t_9ba6cd7a` |
| Base commit | `e01efa18ae837c61c4f6dcdf3864fcfd926717c8` |
| Files added by this card | `ROLLOUT_PLAN.md`, `ROLLOUT_PLAN_APPROVALS.md`, `ROLLOUT_EXECUTIVE_SUMMARY.md`, `evidence/rollout-baseline-2026-10-29.json`, `evidence/rollout-checkrun-inventory-pr187.json` |
| First commit (pre-G4) | `707115a92e5ae21b308527671626fe9d914756fc` — frozen plan + evidence + first ledger |
| Final commit (post-G4) | see `t_9ba6cd7a` completion handoff (`commit=`); worktree clean afterwards |
| Pushed / merged | **No.** No push, no PR, no merge to `main`/`develop`. |

**No publication, deployment, tag, ruleset change or required-check enablement was performed. Human
approval is required before any execution step in the plan.**
