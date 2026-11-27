import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateTraceability, renderGapReport, verifySourcePaths } from './check-requirements.js';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, renameSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function fixture() {
  const sha = 'a'.repeat(40);
  return [{
    schema_version: '0.1', status:'draft', baseline_sha:'a'.repeat(40), requirements: [{id:'FR-TEST-001', priority:'MUST', owner:'qa', requirement:'Test', acceptance:'Pass', verification:['ci'], issue:1, status:'draft'}]
  }, {schema_version:'0.1', requirement_source:'docs/product/requirements.json', records:[{requirement_id:'FR-TEST-001',issue:1,status:'planned',evidence:[],blockers:[],architecture_refs:['docs/adr/example.md'],contract_refs:[],release:null}]} , sha];
}
test('complete planned baseline', () => { const [r,m]=fixture(); assert.equal(validateTraceability(r,m).planned,1); });
test('missing and duplicate IDs fail', () => { const [r,m]=fixture(); m.records=[]; assert.throws(()=>validateTraceability(r,m)); const [r2,m2]=fixture(); r2.requirements.push({...r2.requirements[0]}); assert.throws(()=>validateTraceability(r2,m2)); });
test('orphan and wrong issue fail', () => { const [r,m]=fixture(); m.records[0].issue=2; assert.throws(()=>validateTraceability(r,m)); m.records[0].requirement_id='FR-OTHER-001'; assert.throws(()=>validateTraceability(r,m)); });
test('missing and stale evidence fail', () => { const [r,m,sha]=fixture(); Object.assign(m.records[0],{status:'verified',candidate_sha:sha,pull_request:3}); assert.throws(()=>validateTraceability(r,m)); m.records[0].evidence=[{kind:'ci',reference:'run',commit_sha:'b'.repeat(40),verdict:'pass',test_id:'test'}]; assert.throws(()=>validateTraceability(r,m),/Stale/); m.records[0].evidence[0].commit_sha=sha; assert.equal(validateTraceability(r,m).verified,1); });
test('acceptance requires approved requirement and independent review record', () => { const [r,m,sha]=fixture(); Object.assign(m.records[0],{status:'accepted',candidate_sha:sha,pull_request:3,implementer:'author',evidence:[{kind:'ci',reference:'run',commit_sha:sha,verdict:'pass',test_id:'test'}]}); assert.throws(()=>validateTraceability(r,m)); r.requirements[0].status='approved'; assert.throws(()=>validateTraceability(r,m)); m.records[0].evidence.push({kind:'approval',reference:'review',commit_sha:sha,verdict:'pass',reviewer:'reviewer'}); m.records[0].contract_refs=['services/example.py']; assert.equal(validateTraceability(r,m).accepted,1); m.records[0].blockers=['unresolved']; assert.throws(()=>validateTraceability(r,m)); });
test('invalid IDs, duplicate refs and path traversal fail', () => {
  const [r,m]=fixture();
  r.requirements[0].id='bad'; assert.throws(()=>validateTraceability(r,m));
  r.requirements[0].id='FR-TEST-001';
  m.records[0].architecture_refs=['docs/../secret']; assert.throws(()=>validateTraceability(r,m));
  m.records[0].architecture_refs=['docs/a.md','docs/a.md']; assert.throws(()=>validateTraceability(r,m));
});
test('source references exist and gap report is generated from canonical registry', () => {
  const [r,m]=fixture(); const root=mkdtempSync(join(tmpdir(),'maw-trace-'));
  try {
    assert.throws(()=>verifySourcePaths(m,root));
    mkdirSync(join(root,'docs','adr'),{recursive:true});
    writeFileSync(join(root,'docs','adr','example.md'),'# Test');
    verifySourcePaths(m,root);
    assert.match(renderGapReport(r,m),/MUST \| FR-TEST-001 \| #1 \| planned/);
  } finally { rmSync(root,{recursive:true,force:true}); }
});
test('self review and stale release fail', () => {
  const [r,m,sha]=fixture(); r.requirements[0].status='approved';
  m.records[0].contract_refs=['services/example.py'];
  Object.assign(m.records[0],{status:'accepted',candidate_sha:sha,pull_request:3,implementer:'author',evidence:[
    {kind:'ci',reference:'run',commit_sha:sha,verdict:'pass',test_id:'test'},
    {kind:'approval',reference:'review',commit_sha:sha,verdict:'pass',reviewer:' AUTHOR '}],release:null});
  assert.throws(()=>validateTraceability(r,m),/approval/);
  m.records[0].evidence[1].reviewer='reviewer';
  m.records[0].release={tag:'v1',commit_sha:'b'.repeat(40)};
  assert.throws(()=>validateTraceability(r,m),/release/);
  m.records[0].release.commit_sha=sha; assert.equal(validateTraceability(r,m).accepted,1);
});

// A source-only rename/deletion must invalidate the existing RTM even if
// neither the requirements nor the matrix changed.
test('source-only contract rename invalidates a previously valid matrix', () => {
  const [r,m]=fixture(); const root=mkdtempSync(join(tmpdir(),'maw-rtm-contract-'));
  try {
    mkdirSync(join(root,'docs','adr'),{recursive:true});
    mkdirSync(join(root,'packages','shared'),{recursive:true});
    writeFileSync(join(root,'docs','adr','example.md'),'# Test');
    const source=join(root,'packages','shared','auth_middleware.py');
    writeFileSync(source,'# contract');
    m.records[0].contract_refs=['packages/shared/auth_middleware.py'];
    validateTraceability(r,m); verifySourcePaths(m,root);
    renameSync(source,join(root,'packages','shared','auth.py'));
    assert.throws(()=>verifySourcePaths(m,root));
  } finally { rmSync(root,{recursive:true,force:true}); }
});


test('canonical registry and matrix cover the same baseline requirements', () => {
  const [r,m] = fixture();
  const extra = {...r.requirements[0], id:'NFR-AVL-001', issue:332};
  r.requirements.push(extra);
  assert.throws(() => validateTraceability(r,m), /Missing traceability/);
  m.records.push({...m.records[0], requirement_id:extra.id, issue:extra.issue});
  assert.equal(validateTraceability(r,m).planned,2);
  r.requirements[1].verification = ['ci',' CI '];
  assert.throws(() => validateTraceability(r,m), /Invalid or duplicate requirement/);
});

test('approved requirement with passing CI/review cannot be accepted or released with TBD contract', () => {
  const [r,m,sha]=fixture(); r.requirements[0].status='approved';
  const row=m.records[0];
  Object.assign(row,{status:'accepted',candidate_sha:sha,pull_request:3,implementer:'author',evidence:[
    {kind:'ci',reference:'run',commit_sha:sha,verdict:'pass',test_id:'test'},
    {kind:'approval',reference:'review',commit_sha:sha,verdict:'pass',reviewer:'reviewer'}]});
  assert.throws(()=>validateTraceability(r,m), /Unresolved contract mapping/);
  row.release={tag:'v1',commit_sha:sha};
  assert.throws(()=>validateTraceability(r,m), /Unresolved contract mapping/);
  row.contract_refs=['services/example.py']; assert.equal(validateTraceability(r,m).accepted,1);
  row.release=null; row.status='verified'; row.contract_refs=[];
  assert.equal(validateTraceability(r,m).verified,1);
});
test('actual canonical registry covers both critical requirements with valid trace states', () => {
  const r=JSON.parse(readFileSync('docs/product/requirements.json','utf8'));
  const m=JSON.parse(readFileSync('docs/product/traceability.json','utf8'));
  validateTraceability(r,m); verifySourcePaths(m);
  assert.equal(m.records.length,r.requirements.length);
  for (const id of ['FR-ORCH-004','FR-INT-001']) {
    const row=m.records.find(x=>x.requirement_id===id);
    assert.ok(row);
    if (['planned','blocked'].includes(row.status)) assert.deepEqual(row.evidence,[]);
    assert.ok(r.requirements.find(x=>x.id===id).acceptance_cases.some(x=>x.kind==='negative'));
  }
});

test('one generic CI PASS cannot verify or accept a requirement with named acceptance cases', () => {
  const [r,m,sha]=fixture();
  r.requirements[0].status='approved';
  r.requirements[0].acceptance_cases=[
    {id:'valid-output',kind:'positive',expected:'accepted'},
    {id:'invalid-output',kind:'negative',expected:'denied'},
  ];
  const row=m.records[0]; Object.assign(row,{status:'verified',candidate_sha:sha,pull_request:3,
    contract_refs:['services/example.py'],implementer:'author',evidence:[
      {kind:'ci',reference:'run',commit_sha:sha,verdict:'pass',test_id:'generic'},
      {kind:'approval',reference:'review',commit_sha:sha,verdict:'pass',reviewer:'reviewer'}]});
  assert.throws(()=>validateTraceability(r,m), /Missing acceptance-case CI evidence.*valid-output/);
  row.evidence[0].case_id='valid-output';
  assert.throws(()=>validateTraceability(r,m), /Missing acceptance-case CI evidence.*invalid-output/);
  row.evidence.push({kind:'ci',reference:'run',commit_sha:sha,verdict:'fail',test_id:'negative',case_id:'invalid-output'});
  assert.throws(()=>validateTraceability(r,m), /Missing acceptance-case CI evidence.*invalid-output/);
  row.evidence.at(-1).verdict='pass';
  assert.equal(validateTraceability(r,m).verified,1);
  row.status='accepted'; assert.equal(validateTraceability(r,m).accepted,1);
});


test('positive CI evidence cannot conceal non-passing current candidate receipts', () => {
  const [r,m,sha]=fixture();
  const row=m.records[0];
  r.requirements[0].status='approved';
  r.requirements[0].acceptance_cases=[
    {id:'positive-case',kind:'positive',expected:'success'},
    {id:'negative-case',kind:'negative',expected:'denied'},
  ];
  Object.assign(row,{status:'verified',candidate_sha:sha,pull_request:3,
    implementer:'author',contract_refs:['services/example.py'],evidence:[
      {kind:'ci',reference:'run/1',commit_sha:sha,verdict:'pass',test_id:'positive',case_id:'positive-case'},
      {kind:'ci',reference:'run/1',commit_sha:sha,verdict:'pass',test_id:'negative',case_id:'negative-case'},
      {kind:'approval',reference:'review/1',commit_sha:sha,verdict:'pass',reviewer:'reviewer'},
    ]});
  assert.equal(validateTraceability(r,m).verified,1);
  for (const state of ['verified','accepted']) {
    row.status=state;
    for (const verdict of ['fail','pending','cancelled','unknown',undefined]) {
      row.evidence.push({kind:'ci',reference:'run/2',commit_sha:sha,verdict,
        test_id:'negative',case_id:'negative-case'});
      assert.throws(()=>validateTraceability(r,m),/Contradictory or non-passing CI evidence/);
      row.evidence.pop();
    }
    assert.equal(validateTraceability(r,m)[state],1);
  }
});

test('accepted cannot hide a negative or unresolved approval with a positive receipt', () => {
  const [r,m,sha]=fixture();
  r.requirements[0].status='approved';
  const row=m.records[0];
  Object.assign(row,{status:'accepted',candidate_sha:sha,pull_request:3,
    implementer:'author',contract_refs:['services/example.py'],evidence:[
      {kind:'ci',reference:'run/1',commit_sha:sha,verdict:'pass',test_id:'test'},
      {kind:'approval',reference:'review/1',commit_sha:sha,verdict:'pass',reviewer:'reviewer'},
    ]});
  assert.equal(validateTraceability(r,m).accepted,1);
  for (const verdict of ['fail','pending','revoked',undefined]) {
    row.evidence.push({kind:'approval',reference:'review/2',commit_sha:sha,verdict,reviewer:'reviewer'});
    assert.throws(()=>validateTraceability(r,m),/Contradictory or non-passing approval evidence/);
    row.evidence.pop();
  }
  assert.equal(validateTraceability(r,m).accepted,1);
});
