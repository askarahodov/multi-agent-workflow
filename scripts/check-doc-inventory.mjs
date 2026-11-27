import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
const scope = /^docs\/.+\.(md|json|ya?ml)$/;
const safe = p => typeof p === 'string' && scope.test(p) && !p.includes('\\') && p.split('/').every(s => s && s !== '..' && s !== '.');
const owners = new Set(["UI","Deployment","QA & release","Local runtime","Developer tooling","Documentation","Workflow engine","Agents & providers","Agent runtime","Python shared kernel","Repository automation","Cross-service tests"]);
export function validateInventory(inventory, tracked, read) {
  if (inventory.version !== 1 || !/^[a-f0-9]{40}$/.test(inventory.baseline) || !Array.isArray(inventory.records)) throw Error('invalid inventory header');
  const expected = new Set(tracked.filter(p => scope.test(p)));
  const seen = new Map();
  for (const e of inventory.records) {
    if (!safe(e.path) || seen.has(e.path) || !expected.has(e.path)) throw Error('duplicate, missing or unsafe path: '+e.path);
    if (!owners.has(e.owner) || !['canonical','historical','superseded','draft'].includes(e.status) ||
        !['ru','technical-exception','historical-original','translation-required','unknown'].includes(e.language) ||
        !['source-checked','UNKNOWN'].includes(e.review) || typeof e.reason !== 'string' || !e.reason.trim() ||
        typeof e.version !== 'string' || !e.version.trim()) throw Error('invalid metadata: '+e.path);
    seen.set(e.path,e);
  }
  for (const p of expected) if (!seen.has(p)) throw Error('unregistered document: '+p);
  for (const [p,e] of seen) {
    if (p.startsWith('docs/developer/architecture-decisions/') && p.endsWith('.md') && !p.endsWith('/adr-index.md')) {
      const canonical = 'docs/adr/'+p.split('/').at(-1);
      if (e.status !== 'superseded' || e.canonical !== canonical || seen.get(canonical)?.status !== 'canonical' ||
          !/^[a-f0-9]{40}$/.test(e.originalBlob) ||
          read(p).trim() !== '<!--@include: ../../adr/'+canonical.split('/').at(-1)+'-->') throw Error('noncanonical ADR alias: '+p);
    } else if (e.status === 'superseded' && (!safe(e.canonical) || seen.get(e.canonical)?.status !== 'canonical' || e.canonical === p)) throw Error('invalid superseded target: '+p);
  }
  return seen.size;
}
// Git object IDs, not mutable review text, establish preservation of historical originals.
export function validateHistorical(inventory, current, baseRecords = [], baseBlobs = new Map()) {
  const records = new Map(inventory.records.map(e=>[e.path,e]));
  for (const e of baseRecords.filter(e=>e.status==='historical')) {
    if (records.get(e.path)?.status !== 'historical' || records.get(e.path)?.originalBlob !== e.originalBlob) throw Error('historical record removed or reclassified: '+e.path);
  }
  for (const e of inventory.records.filter(e=>e.status==='historical')) {
    if (!/^[a-f0-9]{40}$/.test(e.originalBlob || '') || current.get(e.path) !== e.originalBlob ||
        (baseBlobs.has(e.path) && baseBlobs.get(e.path) !== e.originalBlob)) throw Error('historical original changed: '+e.path);
  }
}
// The first conversion of an existing duplicate ADR into an include must
// point to the original Git blob, not a caller-invented hash. Subsequent
// updates preserve the original mapping even if the canonical ADR evolves.
export function validateAdrProvenance(inventory, baseRecords, baseBlobs) {
  const isAlias = e => e.path.startsWith('docs/developer/architecture-decisions/') &&
    e.path.endsWith('.md') && !e.path.endsWith('/adr-index.md');
  const old = new Map(baseRecords.filter(isAlias).map(e=>[e.path,e]));
  const current = new Map(inventory.records.filter(isAlias).map(e=>[e.path,e]));
  for (const [path,e] of old) {
    if (e.status !== 'superseded') continue;
    const next = current.get(path);
    if (!next || next.status !== 'superseded' || next.canonical !== e.canonical ||
        next.originalBlob !== e.originalBlob) throw Error('ADR alias provenance removed or changed: '+path);
  }
  for (const [path,e] of current) {
    if (old.get(path)?.status === 'superseded') continue;
    if (baseBlobs.has(path)) {
      if (baseBlobs.get(path) !== e.originalBlob ||
          baseBlobs.get(e.canonical) !== e.originalBlob) throw Error('ADR duplicate origin not verified: '+path);
    } else {
      // New aliases are allowed only if they refer to a canonical original
      // already present in the base; no invented historical provenance.
      if (baseBlobs.get(e.canonical) !== e.originalBlob) throw Error('ADR alias origin not verified: '+path);
    }
  }
}

export function validateExamples(registry, tracked, read) {
  if (registry.version !== 1 || !Array.isArray(registry.examples) || registry.examples.length === 0) throw Error('invalid examples registry');
  const files = new Set(tracked);
  const safePath = p => typeof p === 'string' && !p.includes('\\') && p.split('/').every(x => x && x !== '.' && x !== '..') && files.has(p);
  const seen = new Set();
  for (const e of registry.examples) {
    if (!safe(e.document) || !safePath(e.document) || seen.has(e.document) || !Array.isArray(e.files) || !e.files.length) throw Error('invalid example document: '+e.document);
    seen.add(e.document);
    for (const p of e.files) if (!safePath(p)) throw Error('missing example path: '+p);
    for (const target of e.make ?? []) {
      if (!/^[a-z][a-z0-9-]*$/.test(target) || !safePath('Makefile') || !new RegExp('^'+target+':','m').test(read('Makefile'))) throw Error('missing make target: '+target);
    }
    for (const op of e.api ?? []) {
      if (!safePath(op.spec) || !e.files.includes(op.spec) || !/^(get|post|put|patch|delete|head|options)$/.test(op.method) || typeof op.path !== 'string' || !op.path.startsWith('/')) throw Error('invalid API example');
      const spec = JSON.parse(read(op.spec));
      if (!Object.hasOwn(spec.paths ?? {}, op.path) || !Object.hasOwn(spec.paths[op.path], op.method)) throw Error('missing API operation: '+op.method+' '+op.path);
    }
  }
  return seen.size;
}
export function validateDocImpact(paths, body, active) {
  const affected = paths.some(p => /^(services\/|packages\/|apps\/frontend\/src\/|deploy\/|\.env\.example$|Makefile$)/.test(p));
  const docs = paths.some(p => p.startsWith('docs/') && p.endsWith('.md') && !/^docs\/(audit|research|reviews|integration-audit|branch-cleanup|developer\/evidence)\//.test(p) && (!active || active.has(p)));
  if (affected && !docs && !/^Doc impact: none\s+—\s+\S.+$/m.test(body || '')) throw Error('API/config/behavior change requires docs or explicit Doc impact: none — reason');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const read = p => readFileSync(p,'utf8');
  const tracked = execFileSync('git',['ls-files','-z','docs'],{encoding:'utf8'}).split('\0').filter(Boolean);
  const inventory = JSON.parse(read('docs/governance/documentation-inventory.json'));
  console.log('Registered documentation:',validateInventory(inventory,tracked,read));
  const all = execFileSync('git',['ls-files','-z'],{encoding:'utf8'}).split('\0').filter(Boolean);
  console.log('Checked examples:',validateExamples(JSON.parse(read('docs/governance/checked-examples.json')),all,read));
  const blobs = ref => new Map(execFileSync('git',['ls-tree','-r','-z',ref,'docs'],{encoding:'utf8'}).split('\0').filter(Boolean).map(line=>{const tab=line.indexOf('\t');return [line.slice(tab+1),line.slice(0,tab).split(' ')[2]];}));
  const current = blobs('HEAD');
  validateHistorical(inventory,current);
  const prBase = process.env.DOC_BASE_SHA;
  const pushBase = process.env.DOC_HISTORY_BASE_SHA;
  if (prBase && pushBase) throw Error('ambiguous documentation base');
  const base = prBase || pushBase;
  if (base) {
    if (!/^[a-f0-9]{40}$/.test(base) || /^0+$/.test(base)) throw Error('invalid base SHA');
    // A protected-main push must have an available predecessor; an
    // unrelated or force-rewritten history is not trusted as provenance.
    execFileSync('git',['merge-base','--is-ancestor',base,'HEAD']);
    const baseBlobs = blobs(base);
    const basePath='docs/governance/documentation-inventory.json';
    const baseRecords = baseBlobs.has(basePath) ? JSON.parse(execFileSync('git',['show',base+':'+basePath],{encoding:'utf8'})).records : [];
    validateHistorical(inventory,current,baseRecords,baseBlobs);
    validateAdrProvenance(inventory,baseRecords,baseBlobs);
    if (prBase) {
      // Disable rename detection so both old and new paths participate:
      // moving a service source outside its scope must not hide its impact.
      const paths = execFileSync('git',['diff','--no-renames','--name-only','-z',base+'...HEAD'],{encoding:'utf8'}).split('\0').filter(Boolean);
      const active = new Set(inventory.records.filter(e => ['canonical','draft'].includes(e.status)).map(e=>e.path));
      validateDocImpact(paths, process.env.DOC_PR_BODY, active);
    }
  }
}
