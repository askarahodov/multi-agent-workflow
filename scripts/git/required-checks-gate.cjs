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

module.exports = { assess };
