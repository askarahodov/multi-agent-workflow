/** Read-only QA/Git evidence checks shared by the run and task views.
 * A server-reported "verified" field is never enough on its own. */
import type { GitEvidenceResponse, TaskQaStatus } from '../../api/types';

const SHA=/^[0-9a-f]{40}$/;
export function trustedTaskQa(value:TaskQaStatus|null|undefined,taskId:string):boolean{
  return !!(value && value.task_id===taskId && value.status==='verified' &&
    SHA.test(value.commit_sha??'') && typeof value.issued_by==='string' &&
    value.issued_by.trim() &&
    (['tester','reviewer','security'] as const).every(role=>
      typeof value.gate_run_ids?.[role]==='string' &&
      !!value.gate_run_ids[role].trim()) &&
    new Set(['tester','reviewer','security'].map(role=>
      value.gate_run_ids?.[role as 'tester' | 'reviewer' | 'security'])).size===3);
}
export function trustedTaskGitReports(
  values:GitEvidenceResponse[]|null|undefined,taskId:string,
):values is GitEvidenceResponse[]{
  return Array.isArray(values)&&values.every(item=>!!item &&
    item.task_id===taskId && typeof item.attempt_id==='string' && !!item.attempt_id &&
    SHA.test(item.commit_sha) && item.provenance==='worker_reported' &&
    Array.isArray(item.changed_paths) &&
    item.changed_paths.every(path=>typeof path==='string' && !!path && path.length<=4096));
}
