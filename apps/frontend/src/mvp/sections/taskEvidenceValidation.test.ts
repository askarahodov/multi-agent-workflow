import { describe, expect, it } from 'vitest';
import type { TaskQaStatus } from '../../api/types';
import { trustedTaskGitReports, trustedTaskQa } from './taskEvidenceValidation';

const receipt = (): TaskQaStatus => ({
  task_id: 'task-A',
  status: 'verified',
  commit_sha: 'a'.repeat(40),
  issued_by: 'independent QA',
  gate_run_ids: { tester: 'gate-t', reviewer: 'gate-r', security: 'gate-s' },
});

describe('independent QA receipt display validation', () => {
  it('accepts a matching, complete receipt with three distinct gate runs', () => {
    expect(trustedTaskQa(receipt(), 'task-A')).toBe(true);
  });

  it('fails closed when two roles share a gate execution identity', () => {
    expect(trustedTaskQa({
      ...receipt(),
      gate_run_ids: { tester: 'same-run', reviewer: 'same-run', security: 'gate-s' },
    }, 'task-A')).toBe(false);
  });

  it('does not treat whitespace variants as independent gate executions', () => {
    expect(trustedTaskQa({
      ...receipt(),
      gate_run_ids: { tester: 'same', reviewer: ' same ', security: 'gate-s' },
    }, 'task-A')).toBe(false);
  });

  it('fails closed when all roles reuse one gate run', () => {
    expect(trustedTaskQa({
      ...receipt(),
      gate_run_ids: { tester: 'same', reviewer: 'same', security: 'same' },
    }, 'task-A')).toBe(false);
  });

  it('rejects unverified, incomplete, foreign and unsigned receipts', () => {
    expect(trustedTaskQa({ ...receipt(), status: 'pending' }, 'task-A')).toBe(false);
    expect(trustedTaskQa(receipt(), 'task-B')).toBe(false);
    expect(trustedTaskQa({ ...receipt(), issued_by: '  ' }, 'task-A')).toBe(false);
    expect(trustedTaskQa({
      ...receipt(), gate_run_ids: { tester: 'gate-t', reviewer: '  ', security: 'gate-s' },
    }, 'task-A')).toBe(false);
  });
});

describe('worker-reported Git path integrity', () => {
  const artifact = (changed_paths: string[]) => [{
    task_id: 'task-A', attempt_id: 'attempt-A', commit_sha: 'a'.repeat(40),
    provenance: 'worker_reported' as const, changed_paths,
  }];
  it('accepts bounded relative artifact paths without claiming Git readback', () => {
    expect(trustedTaskGitReports(artifact(['src/result.json']), 'task-A')).toBe(true);
  });
  it.each([
    ['/absolute/path'], ['../outside'], ['src/../private'],
    ['src//file'], ['src/./file'], ['src/' + String.fromCharCode(92) + 'file'], [''],
  ])('rejects unsafe reported path %j', changedPath => {
    expect(trustedTaskGitReports(artifact([changedPath]), 'task-A')).toBe(false);
  });
  it('rejects an empty path list or excessive path count', () => {
    expect(trustedTaskGitReports(artifact([]), 'task-A')).toBe(false);
    expect(trustedTaskGitReports(artifact(Array.from({ length: 101 }, (_, i) =>
      'src/file-' + i)), 'task-A')).toBe(false);
  });
  it('rejects foreign task identity and untrusted provenance', () => {
    expect(trustedTaskGitReports(artifact(['src/ok']), 'other')).toBe(false);
    expect(trustedTaskGitReports([{ ...artifact(['src/ok'])[0],
      provenance: 'unverified' } as never], 'task-A')).toBe(false);
  });
});
