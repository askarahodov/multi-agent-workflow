"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { assess, samePR, checkpointCandidates, assessCheckpoint, bindOwnChecks } = require("./required-checks-gate.cjs");

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


test("project checkpoint is not replaceable by another passing job", () => {
  const checkpoint = "make check (CI checkpoint)";
  const inventory = [...required, checkpoint];
  assert.equal(assess(inventory, jobs()).state, "waiting");
  for (const conclusion of ["failure", "skipped", "cancelled", "neutral", "stale"]) {
    assert.equal(assess(inventory, [...jobs(), {name:checkpoint,status:"completed",conclusion}]).state, "blocked");
  }
  assert.equal(assess(inventory, [...jobs(), {name:checkpoint,status:"completed",conclusion:"success"}]).state, "success");
});

function checkpointFixture(fork=false) {
  const head="a".repeat(40), base="b".repeat(40), merge="c".repeat(40);
  const pr={number:362,state:"open",merge_commit_sha:merge,
    head:{sha:head,ref:"fix/issue-358-make-check-ci",repo:{id:fork?2:1}},
    base:{sha:base,ref:"main",repo:{id:1}}};
  const run={id:42,run_attempt:2,path:".github/workflows/make-check-checkpoint.yml",
    event:"pull_request",head_sha:head,head_branch:pr.head.ref,
    repository:{id:1},head_repository:{id:pr.head.repo.id},
    pull_requests:fork?[]:[{number:pr.number,head:pr.head,base:pr.base}],
    status:"completed",conclusion:"success"};
  const job={name:"make check (CI checkpoint)",run_id:42,run_attempt:2,head_sha:head,
    status:"completed",conclusion:"success",steps:[
      "Verify checkout provenance","Execute exact Makefile target",
      "Prepare exact PR checkpoint receipt","Publish exact PR checkpoint receipt",
      "Record CI checkpoint provenance",
    ].map(name=>({name,status:"completed",conclusion:"success"}))};
  const receipt={id:123,name:"make-check-pr-362-"+merge+"-2",expired:false,
    size_in_bytes:220,digest:"sha256:"+"d".repeat(64),workflow_run:{id:42,head_sha:head}};
  return {pr,run,job,receipt,merge};
}
test("exact current PR identity and both repository IDs required",()=>{
  const {pr,merge}=checkpointFixture();
  assert.equal(samePR(pr,pr,merge),true);
  for(const mutate of [
    x=>x.head.sha="d".repeat(40),x=>x.base.sha="d".repeat(40),
    x=>x.merge_commit_sha="d".repeat(40),x=>x.state="closed",
    x=>x.head.repo.id=99,x=>x.base.repo.id=99,x=>x.base.ref="other",x=>x.number=363,
  ]) {
    const current=structuredClone(pr);mutate(current);
    assert.equal(samePR(pr,current,merge),false);
  }
});
test("same repository and fork checkpoints require actual current run receipt",()=>{
  for(const fork of [false,true]) {
    const {pr,run,job,receipt,merge}=checkpointFixture(fork);
    assert.equal(checkpointCandidates(pr,[run]).length,1);
    assert.deepEqual(assessCheckpoint(pr,merge,run,[job],[receipt]),{state:"success",receipt_id:123});
    assert.equal(assessCheckpoint(pr,merge,run,[job],[]).state,"blocked");
  }
});
test("manual runs, wrong repositories and stale explicit PR associations rejected",()=>{
  for(const mutate of [
    x=>x.event="workflow_dispatch",x=>x.head_repository.id=99,
    x=>x.repository.id=99,x=>x.head_branch="other",
    x=>x.pull_requests=[],x=>x.pull_requests[0].base={...x.pull_requests[0].base,sha:"d".repeat(40)},
    x=>x.pull_requests[0].number=363,x=>x.run_attempt=0,
  ]) {
    const {pr,run}=checkpointFixture();
    const separate=structuredClone(run);mutate(separate);
    assert.equal(checkpointCandidates(pr,[separate]).length,0);
  }
});
test("fork fallback requires exact merge, PR number, attempt and completed step",()=>{
  for(const mutate of [
    x=>x.receipt.name=x.receipt.name.replace("362","363"),
    x=>x.receipt.name=x.receipt.name.replace(x.merge,"d".repeat(40)),
    x=>x.receipt.name=x.receipt.name.slice(0,-1)+"1",
    x=>x.receipt.expired=true,x=>x.receipt.digest=null,
    x=>x.receipt.workflow_run.id=99,x=>x.job.run_attempt=1,
    x=>x.job.head_sha="d".repeat(40),
    x=>x.job.steps[1].conclusion="skipped",
    x=>x.job.steps[3].conclusion="failure",x=>x.run.conclusion="cancelled",
  ]) {
    const f=checkpointFixture(true);mutate(f);
    assert.equal(assessCheckpoint(f.pr,f.merge,f.run,[f.job],[f.receipt]).state,"blocked");
  }
});
test("duplicate receipt and stale attempt cannot authorize checkpoint",()=>{
  const {pr,run,job,receipt,merge}=checkpointFixture(true);
  assert.equal(assessCheckpoint(pr,merge,run,[job],[receipt,{...receipt,id:124}]).state,"blocked");
  const latest={...run,id:43,status:"in_progress"};
  assert.equal(checkpointCandidates(pr,[run,latest])[0].id,43);
  assert.equal(assessCheckpoint(pr,merge,latest,[job],[receipt]).state,"waiting");
});


function ownFixture() {
  const names = ["gitflow policy validation", "gitflow worktree isolation", "quality gate"];
  const identity = {run_id: 70, run_attempt: 2, head_sha: "a".repeat(40)};
  const own = names.slice(0,2).map(name => ({name,...identity,status:"completed",conclusion:"success"}));
  const old = names.slice(0,2).map(name => ({name,status:"completed",conclusion:"cancelled"}));
  return {names, identity, own, checks:[...old,{name:names[2],status:"completed",conclusion:"success"}]};
}
test("cancelled previous suite cannot replace exact current successful prerequisites",()=>{
  const f=ownFixture();
  assert.equal(assess(f.names,f.checks).state,"blocked");
  assert.equal(assess(f.names,bindOwnChecks(f.names,f.checks,f.own,f.identity)).state,"success");
});
test("current GitFlow prerequisite must be successful and match run attempt and head",()=>{
  for(const change of [
    f=>f.own[0].run_id=69, f=>f.own[0].run_attempt=1,
    f=>f.own[0].head_sha="b".repeat(40),
    f=>f.own[0].conclusion="cancelled", f=>f.own[0].conclusion="failure",
    f=>f.own[0].conclusion="skipped", f=>f.own[0].status="queued",
    f=>f.own.pop(), f=>f.own.push({...f.own[0]}),
    f=>f.checks.push(null), f=>f.names.shift(),
  ]) {
    const f=ownFixture();change(f);
    assert.throws(()=>bindOwnChecks(f.names,f.checks,f.own,f.identity));
  }
});
test("unrelated required failures and contradictory duplicate contexts remain blocked",()=>{
  const f=ownFixture();
  f.checks.push({name:"quality gate",status:"completed",conclusion:"cancelled"});
  assert.equal(assess(f.names,bindOwnChecks(f.names,f.checks,f.own,f.identity)).state,"blocked");
});
