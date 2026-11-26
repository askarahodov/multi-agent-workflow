import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const ID = /^(FR|NFR)-[A-Z]+-\d{3}$/;
const SHA = /^[a-f0-9]{40}$/;
const STATES = new Set(['draft', 'approved']);
const nonempty = x => typeof x === 'string' && x.trim().length > 0;

export function validateRequirements(doc) {
  if (doc?.schema_version !== '0.1' || !STATES.has(doc.status) ||
      !SHA.test(doc.baseline_sha ?? '') ||
      !Array.isArray(doc.requirements) || !doc.requirements.length) {
    throw new Error('Unsupported or missing requirements document');
  }
  const expected = new Map();
  for (const r of doc.requirements) {
    if (!r || typeof r.id !== 'string' || !ID.test(r.id) || expected.has(r.id) ||
        !['MUST','SHOULD','COULD'].includes(r.priority) || !nonempty(r.owner) ||
        !nonempty(r.requirement) || !nonempty(r.acceptance) ||
        !Number.isSafeInteger(r.issue) || r.issue <= 0 ||
        !STATES.has(r.status) || (doc.status === 'approved' && r.status !== 'approved') ||
        !Array.isArray(r.verification) || !r.verification.length ||
        !r.verification.every(nonempty) ||
        new Set(r.verification.map(x => x.trim().toLowerCase())).size !== r.verification.length) {
      throw new Error('Invalid or duplicate requirement: ' + String(r?.id));
    }
    expected.set(r.id, r);
  }
  return expected;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const doc = JSON.parse(readFileSync('docs/product/requirements.json', 'utf8'));
    console.log('Requirements registry: ' + validateRequirements(doc).size + ' valid IDs; status=' + doc.status);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
