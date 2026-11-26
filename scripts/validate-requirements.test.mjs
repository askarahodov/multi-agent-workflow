import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateRequirements } from './validate-requirements.mjs';

function fixture() {
  return { schema_version:'0.1', status:'draft', baseline_sha:'a'.repeat(40),
    requirements:[{id:'FR-TEST-001', priority:'MUST', owner:'qa', requirement:'Test',
      acceptance:'Pass', verification:['ci'], issue:1, status:'draft'}] };
}
test('valid draft and actual registry', () => {
  assert.equal(validateRequirements(fixture()).size, 1);
  const doc = JSON.parse(readFileSync('docs/product/requirements.json', 'utf8'));
  const rows = validateRequirements(doc);
  for (const id of ['NFR-AVL-001','NFR-SCALE-001','NFR-COST-001','NFR-MAINT-001']) {
    assert.ok(rows.has(id), 'Missing required NFR ' + id);
  }
});
test('reject duplicate, malformed and missing ID', () => {
  const d = fixture(); d.requirements.push({...d.requirements[0]});
  assert.throws(() => validateRequirements(d), /duplicate/);
  d.requirements.pop(); d.requirements[0].id = 'bad';
  assert.throws(() => validateRequirements(d));
  delete d.requirements[0].id;
  assert.throws(() => validateRequirements(d));
});
test('reject missing criteria, owner, invalid issue and empty or duplicate verification', () => {
  for (const patch of [{owner:' '},{acceptance:''},{issue:0},{verification:[]},
    {verification:['ci',' CI ']},{priority:'P0'},{status:'implemented'}]) {
    const d = fixture(); Object.assign(d.requirements[0],patch);
    assert.throws(() => validateRequirements(d));
  }
});
test('reject invalid baseline and false document approval', () => {
  const d = fixture(); d.baseline_sha='HEAD';
  assert.throws(() => validateRequirements(d));
  d.baseline_sha='a'.repeat(40); d.status='approved';
  assert.throws(() => validateRequirements(d));
  d.requirements[0].status='approved';
  assert.equal(validateRequirements(d).size,1);
});
