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
  if (process.env.DOC_BASE_SHA) {
    if (!/^[a-f0-9]{40}$/.test(process.env.DOC_BASE_SHA)) throw Error('invalid base SHA');
    const paths = execFileSync('git',['diff','--name-only','-z',process.env.DOC_BASE_SHA+'...HEAD'],{encoding:'utf8'}).split('\0').filter(Boolean);
    const active = new Set(inventory.records.filter(e => ['canonical','draft'].includes(e.status)).map(e=>e.path));
    validateDocImpact(paths, process.env.DOC_PR_BODY, active);
  }
}
