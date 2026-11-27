import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdtempSync,writeFileSync,mkdirSync,rmSync,symlinkSync,unlinkSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {artifact,classify,validateEvolution,checkGit} from './check-contract-evolution.mjs';

const root=new URL('../',import.meta.url);
const read=p=>readFileSync(new URL(p,root),'utf8');
const path='services/orchestration-server/docs/openapi.json';
const successor='services/orchestration-server/docs/openapi-v2.json';
const rawReal=read(path);
const real=JSON.parse(rawReal);
const encoded=x=>JSON.stringify(x);
const op={responses:{'200':{description:'Synthetic compatibility test'}}};
function fixture(){
  const a={id:'CT-12',sources:[path],consumers:['frontend','native-worker'],related_tests:['tests/contract.py'],
    lifecycle:{observed_versions:['0.1.0'],support_status:'observed_only',notes:'test'}};
  const base={contracts:[a],versioning:{schema_version:1,status:'draft',changes:[]}};
  const next=structuredClone(base);
  const old=new Map([[path,encoded(real)]]);
  const head=new Map(old);
  const tracked=new Set([path,successor,'tests/contract.py']);
  return {base,next,old,head,tracked};
}
function run(f){return validateEvolution(f.base,f.next,p=>f.old.get(p),p=>f.head.get(p),f.tracked);}
function record(f,kind,to,doc){
  const a=artifact(f.old.get(path),path),b=artifact(encoded(doc),to);
  f.head.set(to,encoded(doc));
  f.next.contracts[0].lifecycle.observed_versions.push(b.version);
  f.next.versioning.changes.push({id:'CV-001',contract:'CT-12',kind,from_path:path,to_path:to,
    from_digest:a.digest,to_digest:b.digest,from_version:a.version,to_version:b.version,
    migration:'Keep old client behavior.',rollback:'Return to old endpoint.',notification:'Notify frontend and native-worker.',
    consumer_tests:['tests/contract.py']});
}
test('actual baseline API allows an additive new operation only with exact evidence and version increment',()=>{
  const f=fixture(),doc=structuredClone(real);
  doc.paths['/synthetic-new-endpoint']={get:op};doc.info.version='0.2.0';
  assert.equal(classify(artifact(encoded(real),path),artifact(encoded(doc),path)),'additive_openapi');
  record(f,'additive_openapi',path,doc);
  const report=run(f);
  assert.equal(report.changes[0].kind,'additive_openapi');assert.equal(report.authorization,false);
  f.next.versioning.changes[0].to_digest='a'.repeat(64);
  assert.throws(()=>run(f),/exact change record/);
});
test('removal, required field, response change and unknown constraint are not additive',()=>{
  for(const kind of ['remove-path','response','required','security','no-bump']){
    const f=fixture(),doc=structuredClone(real),first=Object.keys(doc.paths)[0];
    doc.info.version='0.2.0';
    if(kind==='remove-path')delete doc.paths[first];
    else if(kind==='response')doc.paths[first][Object.keys(doc.paths[first])[0]].responses['418']={description:'new'};
    else if(kind==='required'){const schema=Object.values(doc.components.schemas).find(x=>Array.isArray(x.required));schema.required.push('synthetic');}
    else if(kind==='security')doc.security=[{unexpected:[]}];
    else{doc.paths['/synthetic-new-endpoint']={get:op};doc.info.version='0.1.0';}
    if(kind!=='no-bump')record(f,'additive_openapi',path,doc);
    else f.head.set(path,encoded(doc));
    assert.throws(()=>run(f),/in-place breaking/);
  }
});
test('breaking parallel successor must preserve old wire artifact, explicit migration and tests',()=>{
  const f=fixture(),doc=structuredClone(real);doc.info.version='1.0.0';
  delete doc.paths[Object.keys(doc.paths)[0]];
  f.next.contracts[0].sources.push(successor);
  record(f,'parallel_successor',successor,doc);
  assert.equal(run(f).changes[0].kind,'parallel_successor');
  f.next.versioning.changes[0].consumer_tests=[];
  assert.throws(()=>run(f),/invalid contract change record/);
  f.next.versioning.changes[0].consumer_tests=['tests/contract.py'];
  f.next.versioning.changes[0].rollback='';
  assert.throws(()=>run(f),/invalid contract change record/);
  f.next.versioning.changes[0].rollback='rollback';
  f.next.contracts[0].sources=[successor];
  assert.throws(()=>run(f),/schema removed/);
});
test('JSON formatting is harmless but unknown JSON schema and YAML changes are blocked',()=>{
  const schema='apps/frontend/src/workflow/workflow.schema.json';
  const x=JSON.parse(read(schema)),y=structuredClone(x);
  assert.equal(classify(artifact(JSON.stringify(x),schema),artifact(JSON.stringify(x,null,4),schema)),'unchanged');
  y.properties.schema_version.const='2.0';
  assert.equal(classify(artifact(encoded(x),schema),artifact(encoded(y),schema)),'breaking_or_unknown');
  const yaml='services/runtime-hardening/hardening/api/lifecycle-events-asyncapi.yaml';
  assert.equal(classify(artifact(read(yaml),yaml),artifact(read(yaml)+'\n# changed\n',yaml)),'breaking_or_unknown');
});
test('cannot suppress consumers or rewrite historical migration decision',()=>{
  const f=fixture();f.next.contracts[0].consumers.pop();
  assert.throws(()=>run(f),/consumer removed/);
  const g=fixture(),doc=structuredClone(real);doc.paths['/synthetic-new-endpoint']={get:op};doc.info.version='0.2.0';
  record(g,'additive_openapi',path,doc);
  g.base=structuredClone(g.next);g.old=new Map(g.head);
  g.next.versioning.changes[0].rollback='rewritten';
  assert.throws(()=>run(g),/historical migration record/);
});
test('actual Git tree comparison is ancestry-bound and refuses missing or symlinked tracked artifacts',()=>{
  const dir=mkdtempSync(join(tmpdir(),'contract-evolution-')),cwd=process.cwd();
  try{
    const git=(...args)=>execFileSync('git',args,{cwd:dir,encoding:'utf8'}).trim();
    git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid');
    const put=(p,s)=>{mkdirSync(join(dir,p,'..'),{recursive:true});writeFileSync(join(dir,p),s);};
    const f=fixture();put(path,encoded(real));put('docs/architecture/contract-registry.json',encoded(f.base));put('tests/contract.py','# fixture');
    git('add','.');git('commit','-qm','baseline');const base=git('rev-parse','HEAD');
    process.chdir(dir);
    assert.equal(checkGit(base).tracked_artifacts,1);
    assert.throws(()=>checkGit('0'.repeat(40)),/missing trusted base/);
    const doc=structuredClone(real);delete doc.paths[Object.keys(doc.paths)[0]];
    put(path,encoded(doc));git('add','.');git('commit','-qm','breaking');
    assert.throws(()=>checkGit(base),/in-place breaking/);
    unlinkSync(join(dir,path));symlinkSync('missing.json',join(dir,path));
    git('add','.');git('commit','-qm','symlink');
    assert.throws(()=>checkGit(base),/untracked schema/);
  }finally{process.chdir(cwd);rmSync(dir,{recursive:true,force:true});}
});
test('canonical current inventory has version labels matching every actual machine-readable source',()=>{
  const registry=JSON.parse(read('docs/architecture/contract-registry.json'));
  const files=new Set(registry.contracts.flatMap(c=>c.sources.concat(c.related_tests)));
  const report=validateEvolution(registry,registry,read,read,files);
  assert.equal(report.tracked_artifacts,10);
  assert.equal(report.changes.length,0);
  assert.equal(report.authorization,false);
});

test('duplicate JSON keys, route shadowing and test removal fail closed',()=>{
  assert.throws(()=>artifact('{"info":{"version":"0.1.0","version":"0.2.0"},"openapi":"3.1.0","paths":{}}',path),/duplicate JSON member/);
  assert.throws(()=>artifact('{"info":{"version":"0.1.0","\u0076ersion":"0.2.0"},"openapi":"3.1.0","paths":{}}',path),/duplicate JSON member/);
  const a=structuredClone(real),b=structuredClone(real);
  a.paths['/synthetic/{id}']={get:op};b.paths['/synthetic/{id}']={get:op};
  b.paths['/synthetic/special']={get:op};b.info.version='0.2.0';
  assert.equal(classify(artifact(encoded(a),path),artifact(encoded(b),path)),'breaking_or_unknown');
  const f=fixture();f.next.contracts[0].related_tests=['tests/other.py'];
  assert.throws(()=>run(f),/consumer test removed/);
});

test('exact real int64 constraints cannot round into unchanged or hide inside additive API changes',()=>{
  const before=rawReal;
  const needle=/("maximum"\s*:\s*)9223372036854775807\b/;
  assert.match(before,needle);
  const changed=before.replace(needle,(_m,p)=>p+'9223372036854775806');
  assert.notEqual(changed,before);
  assert.match(changed,/"maximum"\s*:\s*9223372036854775806\b/);
  const a=artifact(before,path),b=artifact(changed,path);
  assert.notEqual(a.digest,b.digest);
  assert.equal(classify(a,b),'breaking_or_unknown');
  const f=fixture();f.old.set(path,before);f.head.set(path,changed);
  assert.throws(()=>run(f),/in-place breaking/);
  const additive=raw=>raw.replace(/"version"\s*:\s*"0\.1\.0"/,'"version":"0.2.0"')
    .replace(/"paths"\s*:\s*\{/,'"paths":{"/synthetic-precise-endpoint":{"get":{"responses":{"200":{"description":"Synthetic"}}}},');
  const rawAdded=additive(before),good=artifact(rawAdded,path);
  assert.equal(classify(a,good),'additive_openapi');
  assert.equal(classify(a,artifact(additive(changed),path)),'breaking_or_unknown');
  f.head.set(path,rawAdded);
  f.next.contracts[0].lifecycle.observed_versions.push(good.version);
  f.next.versioning.changes.push({id:'CV-001',contract:'CT-12',kind:'additive_openapi',
    from_path:path,to_path:path,from_digest:a.digest,to_digest:good.digest,
    from_version:a.version,to_version:good.version,migration:'test',rollback:'test',
    notification:'test',consumer_tests:['tests/contract.py']});
  assert.equal(run(f).changes.length,1);
  f.head.set(path,additive(changed));
  assert.throws(()=>run(f),/in-place breaking/);
});
test('exact decimal canonicalization preserves fractions, huge exponents and JSON types',()=>{
  const wrap=x=>'{"info":{"version":"1.0.0"},"openapi":"3.1.0","paths":{},"value":'+x+'}';
  const dig=x=>artifact(wrap(x),path).digest;
  for(const [a,b] of [['1','1.000e0'],['-0','0.0e99'],['123.4500','12345e-2'],
      ['1e1000000','10e999999'],['0.00001','1e-5'],['-9223372036854775808','-92233720368547758080e-1']])
    assert.equal(dig(a),dig(b),a+' = '+b);
  for(const [a,b] of [['9223372036854775807','9223372036854775806'],
      ['0.123456789012345678901','0.123456789012345678902'],['1e1000000','2e1000000'],
      ['1e-1000000','0'],['1','"1e0"'],['1','{"token":"1e0"}']])
    assert.notEqual(dig(a),dig(b),a+' != '+b);
  assert.throws(()=>artifact(wrap('1'.repeat(4097)),path),/safe parsing limit/);
});
test('real git comparison rejects rounded int64 mutation and registry version impersonation',()=>{
  const dir=mkdtempSync(join(tmpdir(),'contract-numeric-')),cwd=process.cwd();
  try{
    const git=(...args)=>execFileSync('git',args,{cwd:dir,encoding:'utf8'}).trim();
    git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid');
    const put=(p,s)=>{mkdirSync(join(dir,p,'..'),{recursive:true});writeFileSync(join(dir,p),s);};
    const f=fixture(),registryPath='docs/architecture/contract-registry.json';
    put(path,rawReal);put(registryPath,encoded(f.base));put('tests/contract.py','# fixture');
    git('add','.');git('commit','-qm','baseline');const base=git('rev-parse','HEAD');
    process.chdir(dir);
    assert.equal(checkGit(base).tracked_artifacts,1);
    put(path,rawReal.replace(/("maximum"\s*:\s*)9223372036854775807\b/,(m,p)=>p+'9223372036854775806'));
    git('add','.');git('commit','-qm','numeric narrowing');
    assert.throws(()=>checkGit(base),/in-place breaking/);
    put(path,rawReal);put(registryPath,encoded(f.base).replace('"schema_version":1','"schema_version":1.0000000000000000000001'));
    git('add','.');git('commit','-qm','non-exact policy version');
    assert.throws(()=>checkGit(base),/invalid versioning policy/);
  }finally{process.chdir(cwd);rmSync(dir,{recursive:true,force:true});}
});
