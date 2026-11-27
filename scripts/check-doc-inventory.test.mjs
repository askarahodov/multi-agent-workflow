import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync, renameSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateInventory, validateDocImpact, validateExamples, validateHistorical, validateAdrProvenance } from './check-doc-inventory.mjs';
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


test('ADR provenance is verified on conversion and preserved across revisions',()=>{
  const data=registry(), blob='b'.repeat(40), old=new Map([[source,blob],[alias,blob]]);
  validateAdrProvenance(data,[],old);
  assert.throws(()=>validateAdrProvenance(data,[],new Map([[source,blob],[alias,'d'.repeat(40)]])),/origin not verified/);
  const forged=registry();forged.records[1].originalBlob='d'.repeat(40);
  assert.throws(()=>validateAdrProvenance(forged,[],old),/origin not verified/);
  assert.throws(()=>validateAdrProvenance(forged,data.records,old),/provenance removed or changed/);
  assert.throws(()=>validateAdrProvenance({records:[entry(source)]},data.records,old),/provenance removed or changed/);
  validateAdrProvenance(data,data.records,new Map([[source,'d'.repeat(40)],[alias,'e'.repeat(40)]]));
  validateAdrProvenance(data,[],new Map([[source,blob]]));
  assert.throws(()=>validateAdrProvenance(data,[],new Map()),/origin not verified/);
});

// Exercise the actual CLI on a temporary real Git history rather than mocking
// Git path lists. No network or production repository mutation is involved.
function gitFixture(run) {
  const cwd=mkdtempSync(join(tmpdir(),'maw-doc-guard-'));
  const git=(...args)=>execFileSync('git',args,{cwd,encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
  const write=(p,v)=>{const dest=join(cwd,p);mkdirSync(join(dest,'..'),{recursive:true});writeFileSync(dest,v);};
  const commit=()=>{git('add','-A');git('commit','-qm','fixture');return git('rev-parse','HEAD');};
  const check=(env)=>execFileSync(process.execPath,[fileURLToPath(new URL('./check-doc-inventory.mjs',import.meta.url))],{
    cwd,env:{...process.env,DOC_BASE_SHA:'',DOC_HISTORY_BASE_SHA:'',DOC_PR_BODY:'',...env},encoding:'utf8',stdio:['ignore','pipe','pipe'],
  });
  try {
    git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture');
    write('docs/archive.md','original\n');
    write('docs/guide.md','guide\n');
    write('services/x/api.py','pass\n');
    const blob=git('hash-object','docs/archive.md');
    const inventory={version:1,baseline:'a'.repeat(40),records:[
      entry('docs/archive.md',{status:'historical',language:'historical-original',originalBlob:blob}),
      entry('docs/guide.md'),entry('docs/governance/documentation-inventory.json'),
      entry('docs/governance/checked-examples.json'),
    ]};
    const save=()=>write('docs/governance/documentation-inventory.json',JSON.stringify(inventory));
    save();
    write('docs/governance/checked-examples.json',JSON.stringify({version:1,examples:[{document:'docs/guide.md',files:['docs/guide.md']}]}));
    const base=commit();
    run({cwd,git,write,commit,check,inventory,save,base});
  } finally {rmSync(cwd,{recursive:true,force:true});}
}
test('protected push compares historical registry to predecessor',()=>gitFixture(({git,write,commit,check,inventory,save,base})=>{
  write('docs/guide.md','legitimate update\n');commit();
  assert.match(check({DOC_HISTORY_BASE_SHA:base}),/Registered documentation/);
  // Rewriting both bytes and self-reported hash cannot bless history.
  write('docs/archive.md','altered\n');
  inventory.records[0].originalBlob=git('hash-object','docs/archive.md');
  save();commit();
  assert.throws(()=>check({DOC_HISTORY_BASE_SHA:base}),/historical record removed or reclassified|historical original changed/);
  assert.throws(()=>check({DOC_HISTORY_BASE_SHA:'0'.repeat(40)}),/invalid base SHA/);
  assert.throws(()=>check({DOC_BASE_SHA:base,DOC_HISTORY_BASE_SHA:base}),/ambiguous documentation base/);
}));
test('real source rename and deletion require documentation impact',()=>gitFixture(({cwd,commit,check,base})=>{
  mkdirSync(join(cwd,'tools'),{recursive:true});
  renameSync(join(cwd,'services/x/api.py'),join(cwd,'tools/api.py'));
  commit();
  assert.throws(()=>check({DOC_BASE_SHA:base}),/requires docs/);
  assert.match(check({DOC_BASE_SHA:base,DOC_PR_BODY:'Doc impact: none — internal relocation reviewed'}),/Registered documentation/);
  // Main push has no PR body: only historical/structural checks apply there.
  assert.match(check({DOC_HISTORY_BASE_SHA:base}),/Registered documentation/);
}));
test('protected main workflow supplies historical predecessor',()=>{
  const workflow=readFileSync(new URL('../.github/workflows/docs-dependency-check.yml',import.meta.url),'utf8');
  assert.ok(workflow.includes("DOC_HISTORY_BASE_SHA: ${{ github.event_name == 'push' && github.event.before || '' }}"));
  assert.match(workflow,/Missing protected-main predecessor/);
});
