import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const ID = /^(FR|NFR)-[A-Z]+-\d{3}$/;
const SHA = /^[a-f0-9]{40}$/;
const STATES = new Set(['planned', 'implemented', 'verified', 'accepted', 'blocked']);
const nonempty = x => typeof x === 'string' && x.trim().length > 0;
const positive = x => Number.isSafeInteger(x) && x > 0;

export function validateTraceability(requirements, matrix) {
  if (requirements?.schema_version !== '0.1' || matrix?.schema_version !== '0.1' ||
      !Array.isArray(requirements.requirements) || !requirements.requirements.length ||
      !Array.isArray(matrix.records) || matrix.requirement_source !== 'docs/product/requirements.json') {
    throw new Error('Unsupported or missing requirements/traceability document');
  }
  const expected = new Map();
  for (const r of requirements.requirements) {
    if (!r || !ID.test(r.id ?? '') || expected.has(r.id) ||
        !['MUST','SHOULD','COULD'].includes(r.priority) || !nonempty(r.owner) ||
        !nonempty(r.requirement) || !nonempty(r.acceptance) || !positive(r.issue) ||
        !['draft','approved'].includes(r.status) || !Array.isArray(r.verification) ||
        !r.verification.length || !r.verification.every(nonempty)) {
      throw new Error('Invalid or duplicate requirement: ' + String(r?.id));
    }
    expected.set(r.id, r);
  }
  const seen = new Set();
  const counts = Object.fromEntries([...STATES].map(s => [s, 0]));
  for (const record of matrix.records) {
    const r = expected.get(record?.requirement_id);
    if (!r || seen.has(record.requirement_id) || record.issue !== r.issue ||
        !STATES.has(record.status) || !Array.isArray(record.evidence) ||
        !Array.isArray(record.blockers) || !record.blockers.every(nonempty)) {
      throw new Error('Invalid, duplicate or orphan trace record: ' + String(record?.requirement_id));
    }
    seen.add(record.requirement_id);
    if (record.status === 'blocked' && !record.blockers.length) throw new Error('Blocked requirement needs reason');
    if (['implemented','verified','accepted'].includes(record.status)) {
      if (!SHA.test(record.candidate_sha ?? '') || !positive(record.pull_request) || !record.evidence.length) {
        throw new Error('Missing implementation evidence: ' + r.id);
      }
      for (const e of record.evidence) {
        if (!e || e.commit_sha !== record.candidate_sha || !nonempty(e.kind) || !nonempty(e.reference)) {
          throw new Error('Stale or malformed evidence: ' + r.id);
        }
      }
      if (['verified','accepted'].includes(record.status) &&
          !record.evidence.some(e => e.kind === 'ci' && e.verdict === 'pass' && nonempty(e.test_id))) {
        throw new Error('Missing verification evidence: ' + r.id);
      }
      if (record.status === 'accepted' && (r.status !== 'approved' || record.blockers.length ||
          !record.evidence.some(e => e.kind === 'approval' && e.verdict === 'pass' && nonempty(e.reviewer)))) {
        throw new Error('Missing approval or unresolved blockers: ' + r.id);
      }
    }
    counts[record.status]++;
  }
  if (seen.size !== expected.size) throw new Error('Missing traceability record(s)');
  return counts;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const requirements = JSON.parse(readFileSync('docs/product/requirements.json', 'utf8'));
    const matrix = JSON.parse(readFileSync('docs/product/traceability.json', 'utf8'));
    console.log(JSON.stringify(validateTraceability(requirements, matrix)));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
