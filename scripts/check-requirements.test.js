import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateTraceability } from './check-requirements.js';

function fixture() {
  const sha = 'a'.repeat(40);
  return [{
    schema_version: '0.1', requirements: [{id:'FR-TEST-001', priority:'MUST', owner:'qa', requirement:'Test', acceptance:'Pass', verification:['ci'], issue:1, status:'draft'}]
  }, {schema_version:'0.1', requirement_source:'docs/product/requirements.json', records:[{requirement_id:'FR-TEST-001',issue:1,status:'planned',evidence:[],blockers:[]}]} , sha];
}
test('complete planned baseline', () => { const [r,m]=fixture(); assert.equal(validateTraceability(r,m).planned,1); });
test('missing and duplicate IDs fail', () => { const [r,m]=fixture(); m.records=[]; assert.throws(()=>validateTraceability(r,m)); const [r2,m2]=fixture(); r2.requirements.push({...r2.requirements[0]}); assert.throws(()=>validateTraceability(r2,m2)); });
test('orphan and wrong issue fail', () => { const [r,m]=fixture(); m.records[0].issue=2; assert.throws(()=>validateTraceability(r,m)); m.records[0].requirement_id='FR-OTHER-001'; assert.throws(()=>validateTraceability(r,m)); });
test('missing and stale evidence fail', () => { const [r,m,sha]=fixture(); Object.assign(m.records[0],{status:'verified',candidate_sha:sha,pull_request:3}); assert.throws(()=>validateTraceability(r,m)); m.records[0].evidence=[{kind:'ci',reference:'run',commit_sha:'b'.repeat(40),verdict:'pass',test_id:'test'}]; assert.throws(()=>validateTraceability(r,m),/Stale/); m.records[0].evidence[0].commit_sha=sha; assert.equal(validateTraceability(r,m).verified,1); });
test('acceptance requires approved requirement and independent review record', () => { const [r,m,sha]=fixture(); Object.assign(m.records[0],{status:'accepted',candidate_sha:sha,pull_request:3,evidence:[{kind:'ci',reference:'run',commit_sha:sha,verdict:'pass',test_id:'test'}]}); assert.throws(()=>validateTraceability(r,m)); r.requirements[0].status='approved'; assert.throws(()=>validateTraceability(r,m)); m.records[0].evidence.push({kind:'approval',reference:'review',commit_sha:sha,verdict:'pass',reviewer:'reviewer'}); assert.equal(validateTraceability(r,m).accepted,1); m.records[0].blockers=['unresolved']; assert.throws(()=>validateTraceability(r,m)); });
