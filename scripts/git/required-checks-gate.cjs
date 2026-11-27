"use strict";

/**
 * Pure, fail-closed check-run classifier for the optional GitFlow PR gate.
 * The authoritative merge enforcement remains GitHub's live branch ruleset.
 * Exported for deterministic node:test regressions (no GitHub credentials).
 */
function assess(required, runs) {
  if (!Array.isArray(required) || required.length === 0
      || required.some(n => typeof n !== "string" || !n.trim())
      || new Set(required).size !== required.length) {
    return { state: "blocked", reasons: ["required check inventory invalid"] };
  }
  if (!Array.isArray(runs)) {
    return { state: "blocked", reasons: ["GitHub check-run response is invalid"] };
  }
  const byName = new Map();
  for (const run of runs) {
    if (!run || typeof run !== "object" || typeof run.name !== "string") {
      return { state: "blocked", reasons: ["malformed check-run"] };
    }
    if (!byName.has(run.name)) byName.set(run.name, []);
    byName.get(run.name).push(run);
  }
  const bad = [], pending = [], missing = [];
  for (const name of required) {
    const matches = byName.get(name) || [];
    if (!matches.length) {
      missing.push(name);
      continue;
    }
    // Duplicate contexts with contradictory results are not trustworthy.
    for (const run of matches) {
      if (run.status !== "completed") {
        if (["queued", "in_progress", "waiting", "pending", "requested"].includes(run.status)) {
          pending.push(name);
        } else {
          bad.push(`${name}: invalid lifecycle status`);
        }
      } else if (run.conclusion !== "success") {
        if (run.conclusion === null || run.conclusion === undefined) {
          bad.push(`${name}: missing conclusion on completed run`);
        } else {
          bad.push(`${name}: ${String(run.conclusion)}`);
        }
      }
    }
  }
  if (bad.length) return { state: "blocked", reasons: bad, missing, pending };
  if (missing.length || pending.length) {
    return { state: "waiting", reasons: [], missing, pending };
  }
  return { state: "success", reasons: [], missing: [], pending: [] };
}


const SHA = /^[0-9a-f]{40}$/;
const PATH = ".github/workflows/make-check-checkpoint.yml";
const CHECKPOINT = "make check (CI checkpoint)";
const CHECKPOINT_STEPS = [
  "Verify checkout provenance", "Execute exact Makefile target",
  "Prepare exact PR checkpoint receipt", "Publish exact PR checkpoint receipt",
  "Record CI checkpoint provenance",
];
function validSHA(value) { return typeof value === "string" && SHA.test(value) && value !== "0".repeat(40); }
function positive(value) { return Number.isSafeInteger(value) && value > 0; }
function samePR(expected, current, checkout) {
  return current?.state === "open" && positive(expected?.number) &&
    current.number === expected.number &&
    validSHA(checkout) && current.merge_commit_sha === checkout &&
    validSHA(expected.head?.sha) && validSHA(expected.base?.sha) &&
    current.head?.sha === expected.head.sha && current.base?.sha === expected.base.sha &&
    positive(expected.head?.repo?.id) && positive(expected.base?.repo?.id) &&
    current.head?.repo?.id === expected.head.repo.id &&
    current.base?.repo?.id === expected.base.repo.id &&
    current.head?.ref === expected.head.ref && current.base?.ref === expected.base.ref;
}
// Do not fall back to a same-head run from a different repository, branch,
// PR or base. GitHub can omit the association array for fork PRs; only that
// specific case may use the run-bound receipt below to identify the merge.
function checkpointCandidates(pr, runs) {
  if (!Array.isArray(runs)) throw new Error("Invalid checkpoint run list");
  return runs.filter(run => {
    if (!positive(run?.id) || !positive(run.run_attempt) ||
        run.path !== PATH || run.event !== "pull_request" ||
        run.repository?.id !== pr.base.repo.id ||
        run.head_repository?.id !== pr.head.repo.id ||
        run.head_branch !== pr.head.ref || run.head_sha !== pr.head.sha ||
        !Array.isArray(run.pull_requests)) return false;
    if (run.pull_requests.length === 0)
      return pr.head.repo.id !== pr.base.repo.id;
    return run.pull_requests.some(p => p.number === pr.number &&
      p.head?.sha === pr.head.sha && p.base?.sha === pr.base.sha &&
      p.head?.repo?.id === pr.head.repo.id && p.base?.repo?.id === pr.base.repo.id &&
      p.head?.ref === pr.head.ref && p.base?.ref === pr.base.ref);
  }).sort((a,b) => b.id - a.id);
}
function assessCheckpoint(pr, checkout, run, jobs, artifacts) {
  if (!checkpointCandidates(pr, [run]).length || !validSHA(checkout))
    return {state:"blocked", reason:"Unrelated checkpoint run"};
  if (run.status !== "completed")
    return {state:"waiting", reason:"Checkpoint in progress"};
  if (run.conclusion !== "success")
    return {state:"blocked", reason:"Checkpoint failed"};
  const job = Array.isArray(jobs) ? jobs.filter(j => j.name === CHECKPOINT) : [];
  if (job.length !== 1 || job[0].run_id !== run.id ||
      job[0].run_attempt !== run.run_attempt || job[0].head_sha !== pr.head.sha ||
      job[0].status !== "completed" || job[0].conclusion !== "success" ||
      !CHECKPOINT_STEPS.every(name => {
        const steps = job[0].steps?.filter(s => s.name === name);
        return steps?.length === 1 && steps[0].status === "completed" &&
          steps[0].conclusion === "success";
      })) return {state:"blocked",reason:"Checkpoint job or actual command/receipt step not successful"};
  // Artifact metadata comes from THIS workflow run's API, not the PR body.
  // A successful exact upload binds the event PR number, actual merge SHA and
  // attempt. The name is an index, not an independent cryptographic attestation.
  const name = "make-check-pr-" + pr.number + "-" + checkout + "-" + run.run_attempt;
  const receipts = Array.isArray(artifacts) ? artifacts.filter(a => a.name === name) : [];
  if (receipts.length !== 1) return {state:"blocked",reason:"Missing or ambiguous exact PR checkpoint receipt"};
  const receipt = receipts[0];
  if (!positive(receipt.id) || receipt.expired !== false ||
      !positive(receipt.size_in_bytes) || receipt.size_in_bytes > 65536 ||
      !/^sha256:[0-9a-f]{64}$/.test(receipt.digest ?? "") ||
      (receipt.workflow_run && (receipt.workflow_run.id !== run.id ||
        receipt.workflow_run.head_sha !== pr.head.sha)))
    return {state:"blocked",reason:"Invalid checkpoint receipt metadata"};
  return {state:"success",receipt_id:receipt.id};
}

const OWN_CHECKS = ["gitflow policy validation", "gitflow worktree isolation"];

// GitHub listForRef(filter=latest) can expose multiple check suites for the
// same head after rapid PR edits. For our own prerequisite jobs we have a
// stronger source: the exact current workflow run and attempt. Never choose
// an arbitrary successful duplicate, and never discard other required checks.
function bindOwnChecks(required, checks, jobs, identity) {
  if (!Array.isArray(required) || !Array.isArray(checks) || !Array.isArray(jobs) ||
      !positive(identity?.run_id) || !positive(identity?.run_attempt) ||
      !validSHA(identity?.head_sha) || !OWN_CHECKS.every(name => required.includes(name)))
    throw new Error("Invalid current GitFlow job inventory or identity");
  if (checks.some(row => !row || typeof row.name !== "string"))
    throw new Error("Malformed check-run inventory");
  const verified = OWN_CHECKS.map(name => {
    const rows = jobs.filter(row => row?.name === name);
    if (rows.length !== 1) throw new Error("Missing or duplicate current GitFlow job: " + name);
    const row = rows[0];
    if (row.run_id !== identity.run_id || row.run_attempt !== identity.run_attempt ||
        row.head_sha !== identity.head_sha || row.status !== "completed" ||
        row.conclusion !== "success")
      throw new Error("Current GitFlow prerequisite not successful: " + name);
    return row;
  });
  return [...checks.filter(row => !OWN_CHECKS.includes(row.name)), ...verified];
}

module.exports = { assess, samePR, checkpointCandidates, assessCheckpoint, bindOwnChecks };
