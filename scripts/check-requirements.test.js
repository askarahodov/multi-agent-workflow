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

test('one CI receipt/test identity cannot be relabelled as two acceptance cases', () => {
  const [r,m,sha]=fixture();
  r.requirements[0].acceptance_cases=[
    {id:'positive-case',kind:'positive',expected:'success'},
    {id:'negative-case',kind:'negative',expected:'denied'},
  ];
  const row=m.records[0];
  Object.assign(row,{status:'verified',candidate_sha:sha,pull_request:3,evidence:[
    {kind:'ci',reference:'run/1',commit_sha:sha,verdict:'pass',test_id:'suite::test',case_id:'positive-case'},
    {kind:'ci',reference:' run/1 ',commit_sha:sha,verdict:'pass',test_id:'suite::test ',case_id:'negative-case'},
  ]});
  assert.throws(()=>validateTraceability(r,m),/One CI test receipt/);
  row.evidence[1].test_id='suite::test[negative]';
  assert.equal(validateTraceability(r,m).verified,1);
  row.evidence[1].test_id='suite::test';
  row.evidence[1].reference='run/2';
  assert.equal(validateTraceability(r,m).verified,1);
  row.evidence.push({...row.evidence[0],case_id:'unknown-case'});
  assert.throws(()=>validateTraceability(r,m),/Unknown or malformed acceptance-case/);
  row.evidence.pop();
  row.evidence.push({...row.evidence[0],kind:'approval'});
  assert.throws(()=>validateTraceability(r,m),/Unknown or malformed acceptance-case/);
});

test('independent approval cannot conceal self approval or an unidentified reviewer', () => {
  const [r,m,sha]=fixture();
  r.requirements[0].status='approved';
  const row=m.records[0];
  Object.assign(row,{status:'accepted',candidate_sha:sha,pull_request:3,
    implementer:'author',contract_refs:['services/example.py'],evidence:[
      {kind:'ci',reference:'run/1',commit_sha:sha,verdict:'pass',test_id:'test'},
      {kind:'approval',reference:'review/1',commit_sha:sha,verdict:'pass',reviewer:'reviewer'},
    ]});
  assert.equal(validateTraceability(r,m).accepted,1);
  for(const reviewer of [' AUTHOR ', '', undefined]) {
    row.evidence.push({kind:'approval',reference:'review/2',commit_sha:sha,verdict:'pass',reviewer});
    assert.throws(()=>validateTraceability(r,m),/Invalid or self approval evidence/);
    row.evidence.pop();
  }
});

test('generated gap report displays candidate, unverified evidence and missing scenarios', () => {
  const [r,m,sha]=fixture();
  r.requirements[0].acceptance_cases=[
    {id:'positive-case',kind:'positive',expected:'success'},
    {id:'negative-case',kind:'negative',expected:'denied'},
  ];
  const row=m.records[0];
  Object.assign(row,{status:'implemented',candidate_sha:sha,pull_request:3,evidence:[
    {kind:'ci',reference:'run/1',commit_sha:sha,verdict:'pass',test_id:'suite::positive',case_id:'positive-case'},
  ]});
  const report=renderGapReport(r,m);
  assert.ok(report.includes('Evidence (заявленные, не проверенные)'));
  assert.ok(report.includes('#3 | '+sha));
  assert.ok(report.includes('"reference":"run/1"'));
  assert.ok(report.includes('"test_id":"suite::positive"'));
  assert.ok(report.endsWith(' | negative-case'));
});


// The external verifier consumes actual REST shapes through an injected
// read-only transport. Fixtures are not live GitHub evidence.
import { inspectRequirementEvidence, githubReader } from './verify-requirement-evidence.mjs';
const repo='askarahodov/multi-agent-workflow', prefix='/repos/'+repo;
function externalFixture() {
  const [r,m,sha]=fixture();
  const row=m.records[0];
  r.requirements[0].status='approved';
  Object.assign(row,{status:'accepted',candidate_sha:sha,pull_request:3,implementer:'author',
    contract_refs:['services/example.py'],evidence:[
      {kind:'ci',reference:'https://github.com/'+repo+'/actions/runs/11/job/22',commit_sha:sha,verdict:'pass',test_id:'job:22/step:4'},
      {kind:'approval',reference:'https://github.com/'+repo+'/pull/3#pullrequestreview-33',commit_sha:sha,verdict:'pass',reviewer:'reviewer'},
    ]});
  const pr={number:3,state:'open',draft:false,user:{login:'author'},head:{sha,repo:{full_name:repo}},
    base:{sha:'b'.repeat(40),repo:{id:7,full_name:repo}}};
  const run={id:11,status:'completed',conclusion:'success',head_sha:sha,repository:{full_name:repo},
    head_repository:{full_name:repo},event:'pull_request',run_attempt:2,
    pull_requests:[{number:3,head:{sha},base:{repo:{id:7}}}]};
  const job={id:22,run_id:11,run_attempt:2,head_sha:sha,status:'completed',conclusion:'success',
    steps:[{number:4,name:'Contract tests',status:'completed',conclusion:'success'}]};
  const review={id:33,state:'APPROVED',commit_id:sha,user:{login:'reviewer',type:'User'}};
  const roles={permission:'write',user:{login:'reviewer'}};
  const reviews=[review];
  const calls=[];
  const get=async path=>{
    calls.push(path);
    if(path===prefix+'/pulls/3')return pr;
    if(path===prefix+'/actions/runs/11')return run;
    if(path===prefix+'/actions/runs/11/attempts/2/jobs?per_page=100&page=1')return {total_count:1,jobs:[job]};
    if(path===prefix+'/pulls/3/reviews?per_page=100&page=1')return reviews;
    if(path===prefix+'/collaborators/reviewer/permission')return roles;
    throw Error('unexpected path '+path);
  };
  return {r,m,sha,row,pr,run,job,review,reviews,roles,calls,get};
}
test('read-only external evidence inspection never promotes a requirement',async()=>{
  const x=externalFixture();
  const result=await inspectRequirementEvidence(x.r,x.m,x.get);
  assert.equal(result[0].status,'RECEIPTS_INSPECTED_NOT_ACCEPTED');
  assert.equal(result[0].receipts[0].status,'JOB_STEP_CONFIRMED');
  assert.equal(result[0].receipts[0].scenario_semantics,'NOT_VERIFIED');
  assert.equal(result[0].receipts[1].status,'GITHUB_APPROVAL_CONFIRMED');
  const [r,m]=fixture();
  assert.deepEqual(await inspectRequirementEvidence(r,m,()=>{throw Error('no request expected')}),
    [{requirement_id:'FR-TEST-001',status:'NO_CLAIM',receipts:[]}]);
});
test('external CI inspection rejects foreign refs, stale PRs, rerun jobs and unverifiable test names',async()=>{
  for(const mutate of [
    x=>x.pr.head.sha='c'.repeat(40),
    x=>x.pr.draft=true,
    x=>x.pr.head.repo.full_name='other/fork',
    x=>x.row.evidence[0].reference='https://evil.invalid/actions/runs/11/job/22',
    x=>x.run.head_sha='c'.repeat(40),
    x=>x.run.event='push',
    x=>x.run.pull_requests=[],
    x=>x.run.conclusion='cancelled',
    x=>x.job.run_attempt=1,
    x=>x.job.head_sha='c'.repeat(40),
    x=>x.job.steps[0].conclusion='skipped',
    x=>x.row.evidence[0].test_id='suite::test',
    x=>x.row.evidence[0].test_id='job:23/step:4',
  ]) {
    const x=externalFixture();mutate(x);
    await assert.rejects(inspectRequirementEvidence(x.r,x.m,x.get));
  }
});
test('external approval inspection rejects forged, stale, revoked, unauthorized and self review',async()=>{
  for(const mutate of [
    x=>x.review.state='COMMENTED',
    x=>x.review.commit_id='c'.repeat(40),
    x=>x.review.user.type='Bot',
    x=>x.pr.user.login='reviewer',
    x=>x.roles.permission='read',
    x=>x.roles.user.login='someone-else',
    x=>x.reviews.push({...x.review,id:34,state:'DISMISSED'}),
    x=>x.reviews.push({...x.review,id:34,state:'CHANGES_REQUESTED',user:{login:'other',type:'User'}}),
    x=>x.row.evidence[1].reference='https://github.com/'+repo+'/pull/4#pullrequestreview-33',
  ]) {
    const x=externalFixture();mutate(x);
    await assert.rejects(inspectRequirementEvidence(x.r,x.m,x.get));
  }
});
test('external verification fails closed on API error or changed run or base',async()=>{
  for(const failure of ['network','run','base','page']) {
    const x=externalFixture();let reads=0;
    const get=async path=>{
      const value=await x.get(path);
      if(failure==='network')throw Error('API unavailable');
      if(failure==='page' && path.includes('/jobs?'))return {...value,total_count:2};
      if(failure==='run' && path.endsWith('/runs/11') && ++reads===2)return {...value,run_attempt:3};
      if(failure==='base' && path.endsWith('/pulls/3') && ++reads===2)return {...value,base:{...value.base,sha:'d'.repeat(40)}};
      return value;
    };
    await assert.rejects(inspectRequirementEvidence(x.r,x.m,get));
  }
});
test('GitHub transport is GET-only, exact origin and rejects redirect or API errors',async()=>{
  const requests=[];
  const get=githubReader(undefined,async(url,options)=>{
    requests.push({url,options});return {ok:true,text:async()=>JSON.stringify({ok:true})};
  });
  assert.deepEqual(await get(prefix+'/pulls/3'),{ok:true});
  assert.equal(requests[0].url,'https://api.github.com'+prefix+'/pulls/3');
  assert.equal(requests[0].options.method,'GET');assert.equal(requests[0].options.redirect,'error');
  await assert.rejects(get('/repos/other/repo/pulls/3'),/rejected/);
  await assert.rejects(get(prefix+'/../other'),/rejected/);
  const broken=githubReader(undefined,async()=>({ok:false,status:403}));
  await assert.rejects(broken(prefix+'/pulls/3'),/403/);
});
