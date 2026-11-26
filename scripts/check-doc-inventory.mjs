import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
const scope = /^docs\/.+\.(md|json|ya?ml)$/;
const safe = p => typeof p === 'string' && scope.test(p) && !p.includes('\\') && p.split('/').every(s => s && s !== '..' && s !== '.');
const owners = new Set(['UI','Deployment','QA & release','Local runtime','Developer tooling','Documentation']);
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
export function validateDocImpact(paths, body) {
  const affected = paths.some(p => /^(services\/|packages\/|apps\/frontend\/src\/|deploy\/|\.env\.example$|Makefile$)/.test(p));
  const docs = paths.some(p => p.startsWith('docs/') && p.endsWith('.md'));
  if (affected && !docs && !/^Doc impact: none\s+—\s+\S.+$/m.test(body || '')) throw Error('API/config/behavior change requires docs or explicit Doc impact: none — reason');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const read = p => readFileSync(p,'utf8');
  const tracked = execFileSync('git',['ls-files','-z','docs'],{encoding:'utf8'}).split('\0').filter(Boolean);
  console.log('Registered documentation:',validateInventory(JSON.parse(read('docs/governance/documentation-inventory.json')),tracked,read));
  if (process.env.DOC_BASE_SHA) {
    if (!/^[a-f0-9]{40}$/.test(process.env.DOC_BASE_SHA)) throw Error('invalid base SHA');
    const paths = execFileSync('git',['diff','--name-only','-z',process.env.DOC_BASE_SHA+'...HEAD'],{encoding:'utf8'}).split('\0').filter(Boolean);
    validateDocImpact(paths, process.env.DOC_PR_BODY);
  }
}
