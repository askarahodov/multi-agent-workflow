"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { assess } = require("./required-checks-gate.cjs");

const required = ["gitflow policy validation", "quality gate"];
function jobs(a = "success", b = "success") {
  return [
    { name: required[0], status: "completed", conclusion: a },
    { name: required[1], status: "completed", conclusion: b },
  ];
}

test("only complete success for every required check is green", () => {
  assert.equal(assess(required, jobs()).state, "success");
});

for (const conclusion of ["failure", "skipped", "neutral", "cancelled",
                           "timed_out", "action_required", "stale"]) {
  test(`reject completed required check: ${conclusion}`, () => {
    const out = assess(required, jobs("success", conclusion));
    assert.equal(out.state, "blocked");
    assert.match(out.reasons.join(","), new RegExp(conclusion));
  });
}

test("do not signal success before all required checks have appeared", () => {
  const result = assess(required, jobs().slice(0, 1));
  assert.equal(result.state, "waiting");
  assert.deepEqual(result.missing, ["quality gate"]);
});

for (const status of ["queued", "in_progress", "waiting", "requested"]) {
  test(`pending lifecycle status: ${status}`, () => {
    const rows = jobs();
    rows[0] = { name: required[0], status, conclusion: null };
    assert.equal(assess(required, rows).state, "waiting");
  });
}

test("unknown or forged statuses are blocked", () => {
  for (const status of ["success", "nonsense", undefined, ""]) {
    const rows = jobs();
    rows[0].status = status;
    assert.equal(assess(required, rows).state, "blocked", String(status));
  }
});

test("missing completed conclusion blocks instead of waiting forever", () => {
  const rows = jobs();
  rows[0].conclusion = null;
  assert.equal(assess(required, rows).state, "blocked");
});

test("no required inventory and malformed checks fail closed", () => {
  assert.equal(assess([], jobs()).state, "blocked");
  assert.equal(assess(required, null).state, "blocked");
  assert.equal(assess(["duplicate", "duplicate"], jobs()).state, "blocked");
  assert.equal(assess(required, [null]).state, "blocked");
});

test("contradictory duplicate check runs do not authorize success", () => {
  const rows = jobs();
  rows.push({ name: required[1], status: "completed", conclusion: "failure" });
  assert.equal(assess(required, rows).state, "blocked");
});

test("unrelated successful checks cannot substitute for missing required context", () => {
  const rows = [{ name: "other", status: "completed", conclusion: "success" }];
  assert.equal(assess(required, rows).state, "waiting");
  assert.deepEqual(assess(required, rows).missing, required);
});
