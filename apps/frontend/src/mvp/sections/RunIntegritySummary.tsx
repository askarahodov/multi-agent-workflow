/** Run-scoped server evidence overview. This is never a release approval. */
import { useEffect, useState } from 'react';
import type { ApiAdapter, RunResponse, RunReleaseApprovalStatus, TaskQaStatus, TaskResponse } from '../../api/types';
import { Card, formatDate, StatusBadge } from '../ui';
import {trustedTaskQa} from './taskEvidenceValidation';

const MAX_QA_OVERVIEW = 25;
interface QaOverview { checked: number; verified: number; disabled: number; unknown: number }
type QaRead = { key: string; overview: QaOverview | null; loading: boolean };

type ApprovalRead = {
  runId: string;
  refreshKey: number;
  receipt: RunReleaseApprovalStatus | null;
  error: boolean;
};

function validApproval(value: RunReleaseApprovalStatus, runId: string): boolean {
  if (!value || value.run_id !== runId || typeof value.required !== 'boolean') return false;
  if (value.status === 'approved') {
    return typeof value.approved_at === 'string' &&
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
  const reliable = !loading && !error;
  const currentQa = qaRead?.key === qaKey ? qaRead : null;
  const overview = currentQa?.overview ?? null;
  const qaLoading = reliable && ids.length > 0 &&
    ids.length <= MAX_QA_OVERVIEW && (!currentQa || currentQa.loading);

  useEffect(() => {
    let active = true;
    if (!reliable || !ids.length || ids.length > MAX_QA_OVERVIEW) {
      setQaRead({ key: qaKey, overview: null, loading: false });
      return () => { active = false; };
    }
    setQaRead({ key: qaKey, overview: null, loading: true });
    const load = async () => {
      const entries: PromiseSettledResult<TaskQaStatus>[] = [];
      // Bounded fanout avoids flooding the agent-management API.
      for (let index = 0; index < ids.length; index += 5) {
        entries.push(...await Promise.allSettled(
          ids.slice(index, index + 5).map(id => api.getTaskQaStatus(id)),
        ));
        if (!active) return;
      }
      const next: QaOverview = { checked: ids.length, verified: 0, disabled: 0, unknown: 0 };
      entries.forEach((item, index) => {
        if (item.status !== 'fulfilled' || item.value.task_id !== ids[index]) {
          next.unknown++;
        } else if (item.value.status === 'disabled') {
          next.disabled++;
        } else if (trustedTaskQa(item.value, ids[index])) {
          next.verified++;
        } else {
          next.unknown++;
        }
      });
      if (active) setQaRead({ key: qaKey, overview: next, loading: false });
    };
    void load().catch(() => {
      if (active) setQaRead({ key: qaKey, overview: null, loading: false });
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
        if (active) setApproval({ runId: run.id, refreshKey, receipt, error: false });
      })
      .catch(() => {
        if (active) setApproval({ runId: run.id, refreshKey, receipt: null, error: true });
      });
    return () => { active = false; };
  }, [api, run.id, refreshKey]);

  const currentApproval = approval?.runId === run.id &&
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
      {loading ? <p>Обновляется серверный список задач…</p> : null}
      {error ? <p role="alert">Невозможно подтвердить задачи: данные сервера недоступны.</p> : null}
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
          'Все задачи имеют QA receipts по tester/reviewer/security. Это НЕ разрешение на выпуск.' :
          'Нет полного набора подтверждённых QA receipts. Нельзя считать запуск готовым к выпуску.'}
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
