// Contract artifact comparison against the trusted Git base; read-only.
// No approval, runtime compatibility, or production authorization is inferred.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const REGISTRY='docs/architecture/contract-registry.json';
const SHA=/^[a-f0-9]{40}$/;
const DIGEST=/^[a-f0-9]{64}$/;
const VERSION=/^[0-9]+(?:\.[0-9]+){0,2}$/;
const METHOD=new Set(['get','post','put','patch','delete','head','options','trace']);
const SAFE=/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/;
const text=x=>typeof x==='string'&&x.trim().length>0;
const validPath=x=>typeof x==='string'&&SAFE.test(x)&&x.split('/').every(p=>p!=='.'&&p!=='..');
const need=(ok,msg)=>{if(!ok)throw Error(msg);};
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const exact=(x,fields)=>object(x)&&Object.keys(x).length===fields.length&&fields.every(k=>Object.hasOwn(x,k));
const unique=(a,p,nonempty=true)=>Array.isArray(a)&&(!nonempty||a.length>0)&&a.every(p)&&new Set(a).size===a.length;
const sorted=x=>Array.isArray(x)?x.map(sorted):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,sorted(x[k])])):x;
const stable=x=>JSON.stringify(sorted(x));
const equal=(a,b)=>stable(a)===stable(b);
const sha=x=>typeof x==='string'&&DIGEST.test(x);
const version=x=>typeof x==='string'&&VERSION.test(x);
const major=x=>Number(x.split('.')[0]);
const versionParts=x=>x.split('.').map(Number).concat([0,0]).slice(0,3);
const newer=(a,b)=>{const x=versionParts(a),y=versionParts(b);for(let i=0;i<3;i++){if(x[i]!==y[i])return x[i]>y[i];}return false;};
const hash=x=>createHash('sha256').update(x).digest('hex');

export function artifact(raw,path) {
  need(typeof raw==='string'&&validPath(path),'invalid artifact');
  if(path.endsWith('.json')){
    const j=JSON.parse(raw);
    need(object(j),'invalid JSON contract');
    const ver=j.info?.version??j.properties?.schema_version?.const??j.properties?.schemaVersion?.const??j.version;
    need(version(ver),'unknown declared version: '+path);
    return {format:j.openapi?'openapi':'json-schema',version:ver,digest:hash(stable(j)),document:j};
  }
  // YAML is opaque by design. Do not infer compatibility from a partial parser.
  // Only the observed version header is read; changes to any byte require parallel evolution.
  const matches=[...raw.matchAll(/^  version:\s*["']?([0-9]+(?:\.[0-9]+){0,2})["']?\s*$/gm)];
  need(matches.length===1,'ambiguous YAML contract version: '+path);
  return {format:'opaque-yaml',version:matches[0][1],digest:hash(raw),document:null};
}

export function classify(before,after) {
  if(before.digest===after.digest)return 'unchanged';
  if(before.format!=='openapi'||after.format!=='openapi')return 'breaking_or_unknown';
  const a=before.document,b=after.document;
  if(!object(a.paths)||!object(b.paths)||!object(a.info)||!object(b.info))return 'breaking_or_unknown';
  const withoutPathsAndVersion=j=>{const {paths,info,...rest}=j;const {version,...meta}=info;return {...rest,info:meta};};
  if(!equal(withoutPathsAndVersion(a),withoutPathsAndVersion(b)))return 'breaking_or_unknown';
  let additions=0;
  for(const [path,oldItem] of Object.entries(a.paths)){
    const next=b.paths[path];
    if(!object(oldItem)||!object(next))return 'breaking_or_unknown';
    for(const [key,value] of Object.entries(oldItem))
      if(!Object.hasOwn(next,key)||!equal(value,next[key]))return 'breaking_or_unknown';
    // Existing path-level fields are immutable; only new complete operations may be added.
    for(const key of Object.keys(next).filter(k=>!Object.hasOwn(oldItem,k))){
      if(!METHOD.has(key)||!object(next[key])||!object(next[key].responses))return 'breaking_or_unknown';
      additions++;
    }
  }
  for(const path of Object.keys(b.paths).filter(p=>!Object.hasOwn(a.paths,p))){
    const item=b.paths[path];
    if(!path.startsWith('/')||!object(item)||!Object.keys(item).length||
      Object.entries(item).some(([k,v])=>!METHOD.has(k)||!object(v)||!object(v.responses)))return 'breaking_or_unknown';
    additions++;
  }
  if(!additions||!newer(after.version,before.version)||major(after.version)!==major(before.version))
    return 'breaking_or_unknown';
  return 'additive_openapi';
}

function contracts(registry, requireLifecycle) {
  need(object(registry)&&Array.isArray(registry.contracts)&&registry.contracts.length>0,'missing canonical contract registry');
  const byId=new Map(), byPath=new Map();
  for(const c of registry.contracts){
    need(/^CT-\d+$/.test(c.id)&&!byId.has(c.id)&&unique(c.sources,validPath)&&unique(c.consumers,text)
      &&unique(c.related_tests,validPath),'invalid canonical contract metadata');
    if(requireLifecycle){
      const v=c.lifecycle;
      need(exact(v,['observed_versions','support_status','notes'])&&unique(v.observed_versions,version,false)&&text(v.notes)
        &&['unknown','observed_only','observed_mixed'].includes(v.support_status)
        &&(v.support_status==='unknown'?v.observed_versions.length===0:v.observed_versions.length>0)
        &&(v.support_status!=='observed_mixed'||v.observed_versions.length>=2),'invalid lifecycle '+c.id);
    }
    byId.set(c.id,c);
    for(const p of c.sources.filter(p=>/\.(json|ya?ml)$/.test(p))){
      need(!byPath.has(p),'ambiguous schema ownership: '+p);
      byPath.set(p,c.id);
    }
  }
  return {byId,byPath};
}

function records(registry, required){
  if(!required&&!registry.versioning)return [];
  const v=registry.versioning;
  need(exact(v,['schema_version','status','changes'])&&v.schema_version===1&&v.status==='draft'&&Array.isArray(v.changes),'invalid versioning policy');
  const ids=new Set();
  for(const x of v.changes){
    need(exact(x,['id','contract','kind','from_path','to_path','from_digest','to_digest','from_version','to_version','migration','rollback','notification','consumer_tests'])
      &&/^CV-\d{3,}$/.test(x.id)&&!ids.has(x.id)&&/^CT-\d+$/.test(x.contract)
      &&['additive_openapi','parallel_successor'].includes(x.kind)&&validPath(x.from_path)&&validPath(x.to_path)
      &&sha(x.from_digest)&&sha(x.to_digest)&&x.from_digest!==x.to_digest&&version(x.from_version)&&version(x.to_version)
      &&[x.migration,x.rollback,x.notification].every(text)&&unique(x.consumer_tests,validPath),'invalid contract change record');
    ids.add(x.id);
  }
  return v.changes;
}

// A change record is a migration proposal, never independent approval.
// Same-path breaking changes and removal of a supported artifact are blocked.
export function validateEvolution(oldRegistry,newRegistry,readOld,readNew,tracked){
  const old=contracts(oldRegistry,false),next=contracts(newRegistry,true);
  const prior=records(oldRegistry,false),current=records(newRegistry,true);
  const byRecord=new Map(current.map(x=>[x.id,x]));
  for(const r of prior)need(equal(byRecord.get(r.id),r),'historical migration record modified: '+r.id);
  const fresh=current.filter(x=>!prior.some(p=>p.id===x.id));
  const used=new Set(),changes=[];
  const bind=(kind,cid,fromPath,toPath,a,b)=>{
    const matches=fresh.filter(x=>x.kind===kind&&x.contract===cid&&x.from_path===fromPath&&x.to_path===toPath
      &&x.from_digest===a.digest&&x.to_digest===b.digest&&x.from_version===a.version&&x.to_version===b.version);
    need(matches.length===1,'missing or ambiguous exact change record: '+toPath);
    const record=matches[0],contract=next.byId.get(cid);
    need(contract.related_tests.every(p=>record.consumer_tests.includes(p))
      &&record.consumer_tests.every(p=>tracked.has(p)),'consumer verification incomplete: '+toPath);
    used.add(record.id);changes.push({contract:cid,path:toPath,kind,record:record.id});
  };
  for(const [id,c] of old.byId){
    const n=next.byId.get(id);
    need(n,'contract removed: '+id);
    need(c.consumers.every(x=>n.consumers.includes(x)),'consumer removed without retirement policy: '+id);
    // Do not permit removal of a known version or silent downgrade of mixed support.
    if(c.lifecycle)need(c.lifecycle.observed_versions.every(v=>n.lifecycle.observed_versions.includes(v))&&
      (c.lifecycle.support_status!=='observed_mixed'||n.lifecycle.support_status==='observed_mixed'),
      'observed version removed without retirement policy: '+id);
  }
  const oldArtifacts=new Map(),newArtifacts=new Map();
  for(const [path,id] of old.byPath){
    need(next.byPath.get(path)===id,'schema removed, renamed or reassigned: '+path);
    oldArtifacts.set(path,artifact(readOld(path),path));
  }
  for(const [path,id] of next.byPath){
    need(tracked.has(path),'untracked schema: '+path);
    const a=artifact(readNew(path),path);
    need(next.byId.get(id).lifecycle.observed_versions.includes(a.version),'schema version missing from support inventory: '+path);
    newArtifacts.set(path,a);
  }
  for(const [path,a] of oldArtifacts){
    const b=newArtifacts.get(path),kind=classify(a,b);
    if(kind==='unchanged')continue;
    need(kind==='additive_openapi','in-place breaking/unknown schema change: '+path);
    bind(kind,old.byPath.get(path),path,path,a,b);
  }
  for(const [path,b] of newArtifacts){
    if(oldArtifacts.has(path))continue;
    const cid=next.byPath.get(path);
    const candidates=fresh.filter(x=>x.kind==='parallel_successor'&&x.contract===cid&&x.to_path===path);
    need(candidates.length===1,'new schema requires explicit predecessor and migration: '+path);
    const from=candidates[0].from_path,a=oldArtifacts.get(from);
    need(a&&old.byPath.get(from)===cid&&newArtifacts.get(from)?.digest===a.digest
      &&newer(b.version,a.version)&&major(b.version)>major(a.version)&&a.format===b.format,
      'parallel successor must preserve predecessor and increment major version: '+path);
    bind('parallel_successor',cid,from,path,a,b);
  }
  need(used.size===fresh.length,'unused or stale contract change record');
  return {changes,tracked_artifacts:newArtifacts.size,compatibility:'STRUCTURAL_ONLY',
          authorization:false,live_mixed_version:'NOT_VERIFIED'};
}

const git=(args)=>execFileSync('git',args,{encoding:'utf8',maxBuffer:16*1024*1024});
function blobs(ref){
  const map=new Map();
  for(const line of git(['ls-tree','-r','-z',ref]).split('\0').filter(Boolean)){
    const tab=line.indexOf('\t'),[mode,type,oid]=line.slice(0,tab).split(' ');
    if(type==='blob'&&['100644','100755'].includes(mode))map.set(line.slice(tab+1),oid);
  }
  return map;
}
export function checkGit(base,head='HEAD'){
  need(typeof base==='string'&&SHA.test(base)&&!/^0+$/.test(base),'missing trusted base SHA');
  need(head==='HEAD'||typeof head==='string'&&SHA.test(head),'invalid head');
  git(['merge-base','--is-ancestor',base,head]);
  const before=blobs(base),after=blobs(head);
  const read=(map,path)=>{need(validPath(path)&&map.has(path),'missing ordinary tracked blob: '+path);return git(['cat-file','blob',map.get(path)]);};
  return validateEvolution(JSON.parse(read(before,REGISTRY)),JSON.parse(read(after,REGISTRY)),
    p=>read(before,p),p=>read(after,p),new Set(after.keys()));
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  try{console.log(JSON.stringify(checkGit(process.env.CONTRACT_BASE_SHA),null,2));}
  catch(e){console.error(e.message);process.exitCode=1;}
}
