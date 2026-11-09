/** Run-scoped server evidence overview. This is never a release approval. */
import { useEffect, useState } from 'react';
import type { ApiAdapter, RunResponse, TaskQaStatus, TaskResponse } from '../../api/types';
import { Card, StatusBadge } from '../ui';

const MAX_QA_OVERVIEW = 25;
interface QaOverview { checked: number; verified: number; disabled: number; unknown: number }

function trustedReceipt(receipt: TaskQaStatus, taskId: string): boolean {
  return receipt.task_id === taskId && receipt.status === 'verified' &&
    /^[0-9a-f]{40}$/.test(receipt.commit_sha ?? '') &&
    Boolean(receipt.issued_by?.trim()) &&
    (['tester', 'reviewer', 'security'] as const).every(gate =>
      Boolean(receipt.gate_run_ids?.[gate]));
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

export default function RunIntegritySummary({ api, run, tasks, loading, error }: {
  api: ApiAdapter; run: RunResponse; tasks: TaskResponse[];
  loading: boolean; error: Error | null;
}) {
  const [overview, setOverview] = useState<QaOverview | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const ids = tasks.map(task => task.id);
  const signature = ids.join('|');
  const reliable = !loading && !error;

  useEffect(() => {
    let active = true;
    setOverview(null);
    setQaLoading(false);
    if (!reliable || !ids.length || ids.length > MAX_QA_OVERVIEW) {
      return () => { active = false; };
    }
    setQaLoading(true);
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
        } else if (trustedReceipt(item.value, ids[index])) {
          next.verified++;
        } else {
          next.unknown++;
        }
      });
      if (active) { setOverview(next); setQaLoading(false); }
    };
    void load().catch(() => { if (active) { setOverview(null); setQaLoading(false); } });
    return () => { active = false; };
  }, [api, run.id, signature, reliable]); // eslint-disable-line react-hooks/exhaustive-deps

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
        <StatusBadge status="pending" tone="warn" label="Выпуск не подтверждён" />
        {' '}Разрешение человека на release не выводится из статуса задач,
        Git SHA от worker или этого экрана. Не выполняйте merge/deploy без release approval.
      </p>
    </div>
  </Card>;
}
