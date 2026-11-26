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

test('critical Contract Gate and integration scenarios cannot be omitted or relabeled', () => {
  const baseline = JSON.parse(readFileSync('docs/product/requirements.json', 'utf8'));
  const rows = validateRequirements(baseline);
  for (const id of ['FR-ORCH-004','FR-INT-001']) {
    assert.ok(rows.has(id), 'Missing critical requirement '+id);
    const fresh = () => structuredClone(baseline);
    for (const scenario of rows.get(id).acceptance_cases) {
      const d = fresh(), r = d.requirements.find(x=>x.id===id);
      r.acceptance_cases = r.acceptance_cases.filter(c=>c.id!==scenario.id);
      assert.throws(()=>validateRequirements(d), /Missing critical acceptance cases/);
    }
    for (const patch of [{acceptance_cases:[]},{verification:['integration']},{acceptance_cases:undefined}]) {
      const d=fresh(); Object.assign(d.requirements.find(x=>x.id===id),patch);
      assert.throws(()=>validateRequirements(d), /acceptance cases/);
    }
    const d=fresh(), r=d.requirements.find(x=>x.id===id);
    r.acceptance_cases[0].kind='negative';
    assert.throws(()=>validateRequirements(d), /Missing critical acceptance cases/);
  }
});
test('acceptance cases reject duplicate IDs and empty outcomes', () => {
  const doc=fixture(), r=doc.requirements[0];
  r.acceptance_cases=[{id:'case-one',kind:'negative',expected:'denied'}];
  assert.equal(validateRequirements(doc).size,1);
  r.acceptance_cases.push({...r.acceptance_cases[0]});
  assert.throws(()=>validateRequirements(doc), /Invalid acceptance cases/);
  r.acceptance_cases.pop(); r.acceptance_cases[0].expected='';
  assert.throws(()=>validateRequirements(doc), /Invalid acceptance cases/);
});
