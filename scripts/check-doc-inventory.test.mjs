import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateInventory, validateDocImpact, validateExamples, validateHistorical } from './check-doc-inventory.mjs';
const source='docs/adr/ADR-010.md', alias='docs/developer/architecture-decisions/ADR-010.md';
const entry=(path, extra={})=>({path,owner:'Documentation',status:'canonical',language:'technical-exception',reason:'ADR',review:'UNKNOWN',version:'1',...extra});
const registry=()=>({version:1,baseline:'a'.repeat(40),records:[entry(source),entry(alias,{status:'superseded',canonical:source,originalBlob:'b'.repeat(40)})]});
const read=()=> '<!--@include: ../../adr/ADR-010.md-->\n';
test('valid canonical ADR and alias',()=>assert.equal(validateInventory(registry(),[source,alias],read),2));
test('unregistered and deleted documents fail',()=>{assert.throws(()=>validateInventory(registry(),[source,alias,'docs/new.md'],read),/unregistered/);assert.throws(()=>validateInventory(registry(),[source],read),/missing/);});
test('duplicate and traversal fail',()=>{let a=registry();a.records.push(entry(source));assert.throws(()=>validateInventory(a,[source,alias],read),/duplicate/);a=registry();a.records.push(entry('docs/../x.md'));assert.throws(()=>validateInventory(a,[source,alias,'docs/../x.md'],read),/unsafe/);});
test('missing rationale and invalid status fail',()=>{let a=registry();a.records[0].reason='';assert.throws(()=>validateInventory(a,[source,alias],read),/metadata/);a=registry();a.records[0].status='accepted';assert.throws(()=>validateInventory(a,[source,alias],read),/metadata/);});
test('independent ADR copy and wrong target fail',()=>{assert.throws(()=>validateInventory(registry(),[source,alias],()=> '# duplicate'),/noncanonical/);let a=registry();a.records[1].canonical='docs/adr/other.md';assert.throws(()=>validateInventory(a,[source,alias],read),/noncanonical/);});
test('doc impact needs docs or reason',()=>{assert.throws(()=>validateDocImpact(['services/x/api.py'],''),/requires docs/);assert.throws(()=>validateDocImpact(['deploy/x.yml'],'Doc impact: none — '),/requires docs/);validateDocImpact(['services/x/api.py','docs/guide.md'],'');validateDocImpact(['Makefile'],'Doc impact: none — internal formatting only');validateDocImpact(['scripts/test.js'],'');});

const exampleRegistry=()=>({version:1,examples:[{document:'docs/guide.md',files:['api.json'],make:['check'],api:[{spec:'api.json',method:'get',path:'/health'}]}]});
const exampleFiles=['docs/guide.md','api.json','Makefile'];
const exampleRead=p=>p==='Makefile'?'check: lint\n':JSON.stringify({paths:{'/health':{get:{}}}});
test('checked examples bind document, tracked paths, make and OpenAPI',()=>assert.equal(validateExamples(exampleRegistry(),exampleFiles,exampleRead),1));
test('missing and traversal example paths fail',()=>{let a=exampleRegistry();a.examples[0].files.push('../secret');assert.throws(()=>validateExamples(a,exampleFiles,exampleRead),/missing example path/);assert.throws(()=>validateExamples(exampleRegistry(),['docs/guide.md','Makefile'],exampleRead),/missing example path/);});
test('stale make target fails',()=>{let a=exampleRegistry();a.examples[0].make=['obsolete'];assert.throws(()=>validateExamples(a,exampleFiles,exampleRead),/missing make target/);});
test('wrong API method or route fails',()=>{let a=exampleRegistry();a.examples[0].api[0].method='post';assert.throws(()=>validateExamples(a,exampleFiles,exampleRead),/missing API operation/);a=exampleRegistry();a.examples[0].api[0].path='/boards';assert.throws(()=>validateExamples(a,exampleFiles,exampleRead),/missing API operation/);});
test('historical report alone does not satisfy doc impact',()=>assert.throws(()=>validateDocImpact(['services/x/api.py','docs/audit/old.md'],''),/requires docs/));

test('deleted, archived and superseded docs do not satisfy impact',()=>{for(const doc of ['docs/deleted.md','docs/historical.md','docs/alias.md'])assert.throws(()=>validateDocImpact(['services/x/api.py',doc],'',new Set(['docs/active.md'])),/requires docs/);validateDocImpact(['services/x/api.py','docs/active.md'],'',new Set(['docs/active.md']));});

const archive=()=>({records:[entry('docs/archive.md',{status:'historical',language:'historical-original',originalBlob:'c'.repeat(40)})]});
test('historical originals retain exact Git blob',()=>{const a=archive(),m=new Map([['docs/archive.md','c'.repeat(40)]]);validateHistorical(a,m,a.records,m);assert.throws(()=>validateHistorical(a,new Map([['docs/archive.md','d'.repeat(40)]])),/original changed/);assert.throws(()=>validateHistorical(a,new Map()),/original changed/);});
test('historical record cannot be removed or reclassified to evade preservation',()=>{const a=archive(),m=new Map([['docs/archive.md','c'.repeat(40)]]);assert.throws(()=>validateHistorical({records:[]},m,a.records,m),/removed or reclassified/);assert.throws(()=>validateHistorical({records:[entry('docs/archive.md')]},m,a.records,m),/removed or reclassified/);});
test('new registry cannot bless an altered existing archive',()=>{const a=archive(),m=new Map([['docs/archive.md','c'.repeat(40)]]);assert.throws(()=>validateHistorical(a,m,[],new Map([['docs/archive.md','d'.repeat(40)]])),/original changed/);});

// A checked example may reference any tracked file, not only docs/ or services/.
// Keep the trigger unconditional so deletion/rename of root or tooling paths
// cannot silently omit the documentation check (including large PR diffs).
test('docs workflow has no path filters on PR or protected main push',()=>{
  const workflow=readFileSync(new URL('../.github/workflows/docs-dependency-check.yml',import.meta.url),'utf8');
  const triggers=workflow.match(/^on:\s*\n([\s\S]*?)(?=^[a-z][\w-]*:|$(?![\s\S]))/m)?.[1];
  assert.ok(triggers,'workflow on block missing');
  assert.match(triggers,/^  pull_request:\s*$/m);
  assert.match(triggers,/^  push:\s*$/m);
  assert.match(triggers,/^    branches: \[main\]$/m);
  assert.doesNotMatch(triggers,/^\s+paths(?:-ignore)?:/m);
});
