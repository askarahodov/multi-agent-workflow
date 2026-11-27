import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, symlinkSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { validateGovernance, trackedFiles } from './check-change-governance.mjs';

const read = p => JSON.parse(readFileSync(new URL('../'+p,import.meta.url),'utf8'));
const day='2026-11-27', candidate='a'.repeat(40);
function fixture() {
  const register=read('docs/governance/risk-register.json');
  const changes=read('docs/governance/change-proposals.json');
  const context={tracked:trackedFiles(),requirements:read('docs/product/requirements.json').requirements,
    contracts:read('docs/architecture/contract-registry.json').contracts,
    traceability:read('docs/product/traceability.json').records};
  return {register,changes,context,p:changes.proposals[0]};
}
function run(f=fixture()) { return validateGovernance(f.register,f.changes,f.context,day); }
function bad(change,message) { const f=fixture();change(f);assert.throws(()=>run(f),message); }
function approved(f) {
  f.p.status='decision_recorded';f.p.decision='approved';f.p.author='author-one';f.p.candidate_sha=candidate;
  f.p.approvals=f.p.review_roles.map((role,i)=>({role,actor:'reviewer-'+(i+1),decision:'approved',
    candidate_sha:candidate,decided_on:day,
    reference:'https://github.com/askarahodov/multi-agent-workflow/pull/1#issuecomment-'+(i+1)}));
}
function exception(f) {
  const security=f.p.approvals.find(a=>a.role==='security');
  f.p.exceptions=[{id:'EXC-001',risk_id:'RISK-002',scope:'test environment',reason:'fixture',
    owner:'orchestration-server',status:'recorded',expires_on:'2026-12-01',candidate_sha:candidate,
    approval_reference:security.reference}];
}
test('real tracked baseline builds conservative impact without granting permissions',()=>{
  const report=run(),p=report.plans[0];
  assert.equal(report.risk_count,5);
  assert.equal(report.authorization,false);
  assert.equal(p.authorization,false);
  assert.equal(p.production_authorized,false);
  assert.equal(p.approval_provenance,'NOT_VERIFIED');
  assert.ok(p.contract_ids.includes('CT-12'));
  assert.ok(p.components.includes('native-worker'));
  assert.ok(p.components.includes('frontend'));
  assert.ok(p.components.includes('quality-gates'));
  assert.ok(p.requirement_ids.includes('NFR-COMP-001'));
  assert.ok(p.requirement_ids.includes('FR-UI-001'));
  assert.ok(p.test_refs.includes('services/orchestration-server/tests/test_realtime_events.py'));
  assert.ok(p.related_issues.includes(209));
  assert.ok(p.suggested_tasks.every(x=>x.status==='proposed'));
});
test('duplicate risk/proposal and missing mandated risk reject',()=>{
  bad(f=>f.register.risks.push(f.register.risks[0]),/duplicate/);
  bad(f=>f.changes.proposals.push(f.p),/duplicate/);
  bad(f=>f.register.risks=f.register.risks.filter(r=>r.id!=='RISK-001'),/required risk issue/);
});
test('closed issue cannot mark risk resolved and issue snapshots must agree',()=>{
  bad(f=>f.register.risks[0].status='closed',/invalid risk metadata/);
  bad(f=>f.register.risks[1].issues[1].state='closed',/contradictory/);
});
test('unknown versions, mismatched baseline and invalid calendar reject',()=>{
  bad(f=>f.changes.schema_version=2,/version/);
  bad(f=>f.changes.baseline_sha='b'.repeat(40),/baseline/);
  bad(f=>f.register.observed_on='2026-02-30',/date/);
});
test('orphan IDs, traversal, untracked evidence and empty documentation fail',()=>{
  bad(f=>f.p.contracts=['CT-999'],/contract ids/);
  bad(f=>f.p.requirements=['UNKNOWN'],/requirement ids/);
  bad(f=>f.p.risks=['RISK-999'],/risk ids/);
  bad(f=>f.p.paths=['../secret'],/affected paths/);
  bad(f=>f.register.risks[0].evidence_paths=['docs/missing.md'],/risk evidence/);
  bad(f=>f.p.doc_refs=[],/doc refs/);
});
test('inferred test and source references must remain tracked',()=>{
  bad(f=>f.context.tracked.delete('services/orchestration-server/tests/test_realtime_events.py'),/impact test/);
  bad(f=>f.context.tracked.delete('services/orchestration-server/docs/openapi.json'),/impact source/);
});
test('breaking plan requires contract, migration, rollback and reviewers',()=>{
  bad(f=>f.p.contracts=[],/contract ids/);
  bad(f=>f.p.migration.steps=[],/migration steps/);
  bad(f=>f.p.rollback.trigger='',/rollback rationale/);
  bad(f=>f.p.review_roles=f.p.review_roles.filter(x=>x!=='security'),/review role/);
  bad(f=>f.p.review_roles=f.p.review_roles.filter(x=>x!=='operator'),/review role/);
});
test('even structurally valid approval records grant no authority',()=>{
  const f=fixture();approved(f);
  const result=run(f);
  assert.equal(result.plans[0].authorization,false);
  assert.equal(result.plans[0].approval_provenance,'NOT_VERIFIED');
  assert.equal(result.plans[0].scope_expansion_authorized,false);
});
test('approval fails on stale SHA, self-review, duplicate reviewer or role, missing or contradictory receipt',()=>{
  bad(f=>{approved(f);f.p.approvals[0].candidate_sha='b'.repeat(40);},/approval record/);
  bad(f=>{approved(f);f.p.approvals[0].actor='AUTHOR-ONE';},/approval record/);
  bad(f=>{approved(f);f.p.approvals[1].actor=f.p.approvals[0].actor;},/approval record/);
  bad(f=>{approved(f);f.p.approvals[1].role=f.p.approvals[0].role;},/approval record/);
  bad(f=>{approved(f);f.p.approvals.pop();},/missing or contradictory/);
  bad(f=>{approved(f);f.p.approvals[0].decision='rejected';},/contradictory/);
  bad(f=>{approved(f);f.p.approvals[0].reference='https://example.invalid/approval';},/approval record/);
  bad(f=>{approved(f);f.p.approvals[0].decided_on='2026-12-01';},/approval record/);
});
test('decision cannot be silently asserted on draft',()=>{
  bad(f=>f.p.decision='approved',/outside decision_recorded/);
  bad(f=>{f.p.status='in_review';},/exact candidate/);
});
test('recorded exceptions require security record and expiry; even valid record is not authority',()=>{
  const f=fixture();approved(f);exception(f);
  assert.equal(run(f).authorization,false);
  bad(f=>{approved(f);exception(f);f.p.exceptions[0].expires_on=day;},/security decision|expired/);
  bad(f=>{approved(f);exception(f);f.p.exceptions[0].approval_reference=f.p.approvals[0].reference;},/security decision/);
  bad(f=>{approved(f);exception(f);f.p.exceptions[0].candidate_sha='b'.repeat(40);},/candidate/);
  bad(f=>{approved(f);exception(f);f.p.exceptions.push(f.p.exceptions[0]);},/duplicate exception/);
  bad(f=>{approved(f);exception(f);f.p.exceptions[0].status='expired';},/not expired/);
});
test('unrecognized authority field is rejected rather than granting scope',()=>{
  bad(f=>f.p.production_authorized=true,/invalid fields/);
  bad(f=>{approved(f);exception(f);f.p.exceptions[0].effective=true;},/invalid fields/);
});
test('actual git index excludes symlink and untracked files',()=>{
  const dir=mkdtempSync(join(tmpdir(),'change-governance-'));
  try {
    const git=(...args)=>execFileSync('git',args,{cwd:dir,stdio:'ignore'});
    git('init','-q');writeFileSync(join(dir,'tracked.md'),'a');
    writeFileSync(join(dir,'untracked.md'),'b');symlinkSync('tracked.md',join(dir,'link.md'));
    git('add','tracked.md','link.md');
    assert.deepEqual([...trackedFiles(dir)],['tracked.md']);
  } finally {rmSync(dir,{recursive:true,force:true});}
});

test('ADR-only change and explicit requirement propagate through RTM to CT consumers and tests',()=>{
  const f=fixture();
  f.p.paths=['docs/adr/ADR-020-agent-runtime-isolation.md'];
  f.p.requirements=['FR-RUN-001'];
  f.p.contracts=[]; f.p.breaking=false; f.p.change_kinds=['adr'];
  const p=run(f).plans[0];
  assert.ok(p.source_refs.includes('services/agent-management/agent_management/schemas.py'));
  for (const id of ['CT-07','CT-14']) {
    assert.ok(p.contract_ids.includes(id),id);
    const ct=f.context.contracts.find(c=>c.id===id);
    for(const consumer of [ct.producer,...ct.consumers]) assert.ok(p.components.includes(consumer),consumer);
    for(const ref of ct.related_tests) assert.ok(p.test_refs.includes(ref),ref);
  }
  assert.ok(p.components.includes('agent-management'));
  assert.equal(p.authorization,false);
  // Implicit requirement discovery must work without an explicit contract.
  const explicitOnly=fixture();
  explicitOnly.p.paths=['docs/governance/change-risk-management.md'];
  explicitOnly.p.requirements=['FR-RUN-001'];
  explicitOnly.p.contracts=[]; explicitOnly.p.breaking=false; explicitOnly.p.change_kinds=['requirements'];
  assert.ok(run(explicitOnly).plans[0].contract_ids.includes('CT-07'));
});
test('impact fixed point is independent of registry order; missing inferred RTM path fails',()=>{
  const f=fixture();
  const first=run(f);
  f.context.traceability.reverse(); f.context.contracts.reverse(); f.context.requirements.reverse();
  assert.deepEqual(run(f),first);
  const missing=fixture();
  missing.p.paths=['docs/governance/change-risk-management.md'];
  missing.p.requirements=['FR-RUN-001']; missing.p.contracts=[]; missing.p.breaking=false;
  missing.p.change_kinds=['requirements'];
  missing.context.tracked.delete('services/agent-management/agent_management/schemas.py');
  assert.throws(()=>run(missing),/impact source/);
  const absent=fixture();
  absent.context.traceability=absent.context.traceability.filter(r=>r.requirement_id!==absent.p.requirements[0]);
  assert.throws(()=>run(absent),/missing requirement trace/);
});
