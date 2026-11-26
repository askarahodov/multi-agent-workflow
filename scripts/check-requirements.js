import { readFileSync, statSync, realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { resolve, relative, isAbsolute } from 'node:path';

import { validateRequirements } from './validate-requirements.mjs';
const SHA = /^[a-f0-9]{40}$/;
const STATES = new Set(['planned', 'implemented', 'verified', 'accepted', 'blocked']);
const nonempty = x => typeof x === 'string' && x.trim().length > 0;
const positive = x => Number.isSafeInteger(x) && x > 0;

function validRefs(refs) {
  return Array.isArray(refs) && refs.every(p => nonempty(p) &&
    /^(docs|services|packages|apps)\/[A-Za-z0-9._/-]+$/.test(p) &&
    !p.split('/').some(part => part === '.' || part === '..' || !part)) &&
    new Set(refs).size === refs.length;
}

export function verifySourcePaths(matrix, root = process.cwd()) {
  const canonicalRoot = realpathSync(root);
  for (const record of matrix.records) {
    for (const ref of [...record.architecture_refs, ...record.contract_refs]) {
      const target = realpathSync(resolve(canonicalRoot, ref));
      const rel = relative(canonicalRoot, target);
      if (!rel || rel === '..' || rel.startsWith('../') || rel.startsWith('..\\') ||
          isAbsolute(rel) || !statSync(target).isFile()) {
        throw new Error('Invalid source reference: ' + ref);
      }
    }
  }
}

export function validateTraceability(requirements, matrix) {
  if (requirements?.schema_version !== '0.1' || matrix?.schema_version !== '0.1' ||
      !Array.isArray(requirements.requirements) || !requirements.requirements.length ||
      !Array.isArray(matrix.records) || matrix.requirement_source !== 'docs/product/requirements.json') {
    throw new Error('Unsupported or missing requirements/traceability document');
  }
  const expected = validateRequirements(requirements);
  const seen = new Set();
  const counts = Object.fromEntries([...STATES].map(s => [s, 0]));
  for (const record of matrix.records) {
    const r = expected.get(record?.requirement_id);
    if (!r || seen.has(record.requirement_id) || record.issue !== r.issue ||
        !STATES.has(record.status) || !Array.isArray(record.evidence) ||
        !Array.isArray(record.blockers) || !record.blockers.every(nonempty) ||
        !validRefs(record.architecture_refs) || !validRefs(record.contract_refs) ||
        !(record.release === null || (nonempty(record.release?.tag) && SHA.test(record.release?.commit_sha ?? '')))) {
      throw new Error('Invalid, duplicate or orphan trace record: ' + String(record?.requirement_id));
    }
    seen.add(record.requirement_id);
    if (record.status === 'blocked' && !record.blockers.length) throw new Error('Blocked requirement needs reason');
    if (record.release !== null && (record.status !== 'accepted' ||
        record.release.commit_sha !== record.candidate_sha)) throw new Error('Unaccepted or stale release: ' + r.id);
    if (['planned','blocked'].includes(record.status) && record.evidence.length) {
      throw new Error('Unverified record may not claim evidence: ' + r.id);
    }
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
      if (['verified','accepted'].includes(record.status)) {
        for (const scenario of r.acceptance_cases ?? []) {
          if (!record.evidence.some(e => e.kind === 'ci' && e.verdict === 'pass' &&
              e.case_id === scenario.id && nonempty(e.test_id))) {
            throw new Error('Missing acceptance-case CI evidence: ' + r.id + '/' + scenario.id);
          }
        }
      }
      if (record.status === 'accepted' && !record.contract_refs.length) {
        throw new Error('Unresolved contract mapping (TBD): ' + r.id);
      }
      if (record.status === 'accepted' && (r.status !== 'approved' || record.blockers.length || !record.architecture_refs.length ||
          !nonempty(record.implementer) ||
          !record.evidence.some(e => e.kind === 'approval' && e.verdict === 'pass' && nonempty(e.reviewer) && e.reviewer.trim().toLowerCase() !== record.implementer.trim().toLowerCase()))) {
        throw new Error('Missing approval or unresolved blockers: ' + r.id);
      }
    }
    counts[record.status]++;
  }
  if (seen.size !== expected.size) throw new Error('Missing traceability record(s)');
  return counts;
}

export function renderGapReport(requirements, matrix) {
  const counts = validateTraceability(requirements, matrix);
  const byId = new Map(requirements.requirements.map(r => [r.id, r]));
  const lines = ['Трассируемость: ' + JSON.stringify(counts),
    'Приоритет | Требование | Issue | Статус | ADR/архитектура | Контракты | Релиз | Пробелы'];
  for (const r of matrix.records) {
    const req = byId.get(r.requirement_id);
    lines.push([req.priority, r.requirement_id, '#' + r.issue, r.status,
      r.architecture_refs.join(', ') || 'TBD', r.contract_refs.join(', ') || 'TBD',
      r.release?.tag ?? 'не подтверждён', r.blockers.join('; ') || 'нет записанных'].join(' | '));
  }
  return lines.join('\n');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const requirements = JSON.parse(readFileSync('docs/product/requirements.json', 'utf8'));
    const matrix = JSON.parse(readFileSync('docs/product/traceability.json', 'utf8'));
    validateTraceability(requirements, matrix);
    verifySourcePaths(matrix);
    console.log(renderGapReport(requirements, matrix));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
