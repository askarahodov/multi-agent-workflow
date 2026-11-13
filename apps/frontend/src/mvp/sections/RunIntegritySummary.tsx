/** Run-scoped server evidence overview. This is never a release approval. */
import { useEffect, useState } from 'react';
import type { ApiAdapter, AttemptResponse, GitEvidenceResponse, RunResponse, RunReleaseApprovalStatus, TaskQaStatus, TaskResponse } from '../../api/types';
import { Card, formatDate, StatusBadge } from '../ui';
import {trustedTaskQa, trustedTaskGitReports} from './taskEvidenceValidation';

const MAX_QA_OVERVIEW = 25;
interface QaOverview { checked: number; verified: number; disabled: number; unknown: number }
type QaRead = { api: ApiAdapter; key: string; overview: QaOverview | null; loading: boolean };

function validAttemptEvidence(
  task: TaskResponse, qa: TaskQaStatus, attempts: AttemptResponse[], git: GitEvidenceResponse[],
): boolean {
  // A signed/verified receipt is not enough: the read-only run dashboard must
  // prove the exact same completed attempt and worker-reported commit as the
  // task card, without trusting an unverified or foreign list.
  if (task.status !== 'completed' || !trustedTaskQa(qa, task.id) ||
      typeof qa.attempt_id !== 'string' || !qa.attempt_id ||
      !Array.isArray(attempts) || !Array.isArray(git) ||
      !trustedTaskGitReports(git, task.id)) return false;
  const ids = new Set<string>();
  for (const attempt of attempts) {
    if (!attempt || attempt.task_id !== task.id ||
        typeof attempt.id !== 'string' || !attempt.id || ids.has(attempt.id)) return false;
    ids.add(attempt.id);
  }
  return attempts.some(attempt =>
    attempt.id === qa.attempt_id && attempt.status === 'completed'
  ) && git.some(artifact =>
    artifact.attempt_id === qa.attempt_id && artifact.commit_sha === qa.commit_sha
  );
}

type ApprovalRead = {
  api: ApiAdapter;
  runId: string;
  refreshKey: number;
  receipt: RunReleaseApprovalStatus | null;
  error: boolean;
};

function validApproval(value: RunReleaseApprovalStatus, runId: string): boolean {
  if (!value || value.run_id !== runId || typeof value.required !== 'boolean') return false;
  if (value.status === 'approved') {
    return value.required === true && typeof value.approved_at === 'string' &&
      Number.isFinite(Date.parse(value.approved_at));
  }
  return (value.status === 'pending' && value.required === true ||
    value.status === 'not_configured' && value.required === false) &&
    value.approved_at === null;
}

export function runNextAction(run: RunResponse, tasks: TaskResponse[], reliable: boolean): string {
  if (typeof run.input_data?._workflow_version_id !== 'string' ||
      !run.input_data._workflow_version_id) {
    return 'Версия источника не подтверждена. Проверяйте происхождение задач и запрещайте выпуск до независимой сверки.';
  }
  if (!reliable) {
    return 'Серверный список задач не подтверждён. Обновите запуск; отсутствие данных не означает успех или готовность к выпуску.';
  }
  if (tasks.some(task => task.status === 'blocked')) {
    return 'Есть заблокированные задачи. Откройте карточку и карантин; повтор без операторской сверки побочных действий запрещён.';
  }
  if (run.status === 'cancelled') {
    return 'Запуск отменён. Проверьте серверные результаты; не возобновляйте побочные действия автоматически.';
  }
  if (tasks.some(task => task.status === 'failed') || run.status === 'failed') {
    return 'Есть сбой выполнения. Изучите попытки и журнал; новые попытки контролирует серверный worker.';
  }
  if (!tasks.length) return 'Задач нет. Нельзя подтверждать выполнение или выпуск без серверных задач.';
  if (run.status === 'completed' && tasks.every(task => task.status === 'completed')) {
    return 'Все задачи имеют статус completed. Независимая QA и разрешение человека на выпуск проверяются отдельно.';
  }
  if (tasks.some(task => task.status === 'in_progress') || run.status === 'running') {
    return 'Есть выполняющиеся задачи. Проверьте журнал и доступность worker; running не доказывает наличие live-потока.';
  }
  return 'Ожидайте серверного worker или откройте журнал причин ожидания. Создание запуска не означает выполнение.';
}

export default function RunIntegritySummary({ api, run, tasks, loading, error, refreshKey = 0 }: {
  api: ApiAdapter; run: RunResponse; tasks: TaskResponse[];
  loading: boolean; error: Error | null; refreshKey?: number;
}) {
  // A QA receipt can change while task IDs remain stable. Bind every read to
  // the exact run, refresh generation and task snapshot so a stale response
  // cannot briefly render as verified for a new generation.
  const [qaRead, setQaRead] = useState<QaRead | null>(null);
  const [approval, setApproval] = useState<ApprovalRead | null>(null);
  const ids = tasks.map(task => task.id);
  const signature = tasks.map(task =>
    [task.id, task.version, task.attempt_count, task.status].join(':')).join('|');
  const qaKey = [run.id, refreshKey, signature].join('/');
  // Caller-provided task arrays are not a trusted complete server result.
  // Reject mixed-run/duplicated/invalid records in the standalone summary too.
  const taskIds=new Set<string>();
  const taskListValid=tasks.every(task=>{
    if(!task || typeof task.id!=='string'||!task.id||
       task.workflow_run_id!==run.id || taskIds.has(task.id))return false;
    taskIds.add(task.id);return true;
  });
  const reliable = !loading && !error && taskListValid;
  const currentQa = qaRead?.api === api && qaRead.key === qaKey ? qaRead : null;
  const overview = currentQa?.overview ?? null;
  const qaLoading = reliable && ids.length > 0 &&
    ids.length <= MAX_QA_OVERVIEW && (!currentQa || currentQa.loading);

  useEffect(() => {
    let active = true;
    if (!reliable || !ids.length || ids.length > MAX_QA_OVERVIEW) {
      setQaRead({ api, key: qaKey, overview: null, loading: false });
      return () => { active = false; };
    }
    setQaRead({ api, key: qaKey, overview: null, loading: true });
    const load = async () => {
      const entries: PromiseSettledResult<[
        TaskQaStatus, AttemptResponse[], GitEvidenceResponse[],
      ]>[] = [];
      // At most five tasks and three evidence reads per group; a single
      // failed/malformed endpoint makes only its task unknown, never "green".
      // No mutation or trust in model-supplied status fields is involved.
      for (let index = 0; index < ids.length; index += 5) {
        entries.push(...await Promise.allSettled(
          ids.slice(index, index + 5).map(async id => Promise.all([
            api.getTaskQaStatus(id),
            api.listTaskAttempts(id),
            api.listTaskGitEvidence(id),
          ])),
        ));
        if (!active) return;
      }
      const next: QaOverview = { checked: ids.length, verified: 0, disabled: 0, unknown: 0 };
      entries.forEach((item, index) => {
        if (item.status !== 'fulfilled' || !item.value?.[0] ||
            item.value[0].task_id !== ids[index]) {
          next.unknown++;
        } else if (item.value[0].status === 'disabled') {
          // A disabled strict QA policy is not proof of a tested commit.
          next.disabled++;
        } else if (validAttemptEvidence(
          tasks[index], item.value[0], item.value[1], item.value[2],
        )) {
          next.verified++;
        } else {
          next.unknown++;
        }
      });
      if (active) setQaRead({ api, key: qaKey, overview: next, loading: false });
    };
    void load().catch(() => {
      if (active) setQaRead({ api, key: qaKey, overview: null, loading: false });
    });
    return () => { active = false; };
  }, [api, qaKey, reliable]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let active = true;
    setApproval(null);
    // This is a read-only, dedicated operator-authored receipt. Never
    // infer approval from completed tasks, Git evidence or QA signatures.
    void Promise.resolve().then(() => api.getRunReleaseApproval(run.id))
      .then(receipt => {
        if (!validApproval(receipt, run.id)) throw new Error('Invalid release evidence');
        if (active) setApproval({ api, runId: run.id, refreshKey, receipt, error: false });
      })
      .catch(() => {
        if (active) setApproval({ api, runId: run.id, refreshKey, receipt: null, error: true });
      });
    return () => { active = false; };
  }, [api, run.id, refreshKey]);

  const currentApproval = approval?.api === api && approval.runId === run.id &&
    approval.refreshKey === refreshKey ? approval : null;
  const completed = tasks.filter(task => task.status === 'completed').length;
  const blocked = tasks.filter(task => task.status === 'blocked' || task.status === 'failed').length;
  const attempts = tasks.reduce((total, task) => total + task.attempt_count, 0);
  const allQaVerified = reliable && tasks.length > 0 && tasks.length <= MAX_QA_OVERVIEW &&
    !qaLoading && overview?.checked === tasks.length &&
    overview.verified === tasks.length && overview.unknown === 0 && overview.disabled === 0;

  return <Card title="Этапы, QA и ожидаемое действие">
    <div data-testid="run-integrity-summary">
      <p>Задач завершено: <strong>{reliable ? completed : 'не подтверждено'}</strong>
        {' / '}{reliable ? tasks.length : '—'}.
        {' '}Заблокировано или с ошибкой: <strong>{reliable ? blocked : '—'}</strong>.
        {' '}Попыток: <strong>{reliable ? attempts : '—'}</strong>.
      </p>
      <p data-testid="run-next-action" role="status">{runNextAction(run, tasks, reliable)}</p>
      <p data-testid="run-execution-mode" style={{ fontSize: 12 }}>
        Источник данных: серверный запуск. Режим фактического выполнения,
        доступность native worker и стоимость LLM не подтверждены этой сводкой.
        Реальную телеметрию и бюджет следует проверять отдельно перед платным запуском.
      </p>
      {loading ? <p>Обновляется серверный список задач…</p> : null}
      {error || !taskListValid ?
        <p role="alert">Невозможно подтвердить задачи: данные сервера недоступны или относятся к другому запуску.</p> : null}
      <div data-testid="run-qa-summary">
        <strong>Независимая QA:</strong>{' '}
        {qaLoading ? 'загрузка подтверждений…' :
          !reliable ? 'неизвестна — список задач недоступен' :
          !tasks.length ? 'неизвестна — задач нет' :
          tasks.length > MAX_QA_OVERVIEW ? 'неизвестна — слишком много задач для ограниченного обзора' :
          overview ? overview.verified + ' из ' + overview.checked + ' подтверждено; ' +
            overview.disabled + ' без строгой QA, ' + overview.unknown + ' не проверено' :
            'неизвестна — подтверждения не загружены'}
      </div>
      <p style={{ fontSize: 12 }}>
        {allQaVerified ?
          'Для всех задач QA receipt совпал с завершённой попыткой и worker-reported Git commit. Сам Git commit ещё требует независимой серверной проверки; это НЕ разрешение на выпуск.' :
          'Нет полного набора согласованных QA, завершённых попыток и Git evidence. Нельзя считать запуск готовым к выпуску.'}
      </p>
      <p data-testid="run-release-boundary" style={{ fontSize: 12 }}>
        {!currentApproval ? (
          <StatusBadge status="pending" tone="warn" label="Выпуск не подтверждён — проверка..." />
        ) : currentApproval.error || !currentApproval.receipt ? (
          <StatusBadge status="pending" tone="warn" label="Выпуск не подтверждён — статус неизвестен" />
        ) : currentApproval.receipt.status === 'approved' ? (
          <StatusBadge status="completed" tone="success" label="Операторское разрешение сохранено" />
        ) : currentApproval.receipt.status === 'pending' ? (
          <StatusBadge status="pending" tone="warn" label="Выпуск не подтверждён — ожидает оператора" />
        ) : (
          <StatusBadge status="pending" tone="warn" label="Выпуск не подтверждён — политика выключена" />
        )}
        {' '}{currentApproval?.receipt?.status === 'approved'
          ? 'Отдельный операторский ключ зарегистрировал release approval ' +
            formatDate(currentApproval.receipt.approved_at ?? undefined) + '. Это не подтверждает merge/deploy.'
          : currentApproval?.receipt?.status === 'pending'
            ? 'Для данного запуска включён отдельный операторский release gate. Никакого автоматического одобрения нет.'
            : currentApproval?.receipt?.status === 'not_configured'
              ? 'На сервере не включён отдельный операторский release gate. Его отсутствие не является разрешением на выпуск.'
              : 'Подтверждения выпуска нет; повторите чтение после восстановления API.'}
        {' '}Ни статус задач, ни QA receipts не заменяют ручное разрешение.
      </p>
    </div>
  </Card>;
}
