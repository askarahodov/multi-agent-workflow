import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ApiAdapter, RunResponse, TaskResponse, TaskQaStatus } from '../../api/types';
import RunIntegritySummary, { runNextAction } from './RunIntegritySummary';

const run: RunResponse = {
  id: 'run-qa', project_id: 'p1', name: 'Test workflow', status: 'completed',
  version: 1, input_data: { _workflow_version_id: 'published-v1' },
};
const tasks: TaskResponse[] = [
  { id: 'task-1', workflow_run_id: run.id, title: 'Implement',
    status: 'completed', priority: 1, attempt_count: 2, max_attempts: 3, version: 1 },
  { id: 'task-2', workflow_run_id: run.id, title: 'Review',
    status: 'completed', priority: 1, attempt_count: 1, max_attempts: 3, version: 1 },
];
const receipt = (id: string): TaskQaStatus => ({
  task_id: id, status: 'verified', commit_sha: 'a'.repeat(40),
  issued_by: 'operator', gate_run_ids: { tester: 't', reviewer: 'r', security: 's' },
});
function adapter(fn: (id: string) => Promise<TaskQaStatus>) {
  return {
    getTaskQaStatus: vi.fn(fn),
    getRunReleaseApproval: vi.fn(async (id: string) => ({
      run_id: id, required: false, status: 'not_configured', approved_at: null,
    })),
  } as unknown as ApiAdapter;
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe('run QA summary is fail-closed', () => {
  it('shows server-verified receipts without ever granting release', async () => {
    const api = adapter(async id => receipt(id));
    render(<RunIntegritySummary api={api} run={run} tasks={tasks} loading={false} error={null} />);
    expect(await screen.findByText(/2 из 2 подтверждено/)).toBeInTheDocument();
    expect(screen.getByTestId('run-integrity-summary')).toHaveTextContent('Попыток: 3');
    expect(screen.getByTestId('run-integrity-summary')).toHaveTextContent('НЕ разрешение на выпуск');
    expect(screen.getByTestId('run-release-boundary')).toHaveTextContent('Выпуск не подтверждён');
    expect(vi.mocked(api.getTaskQaStatus)).toHaveBeenCalledTimes(2);
  });
  it('refuses mismatched receipt identity, incomplete signatures and API failure', async () => {
    const api = adapter(async id => id === 'task-1'
      ? { ...receipt(id), task_id: 'wrong-task' }
      : { ...receipt(id), gate_run_ids: undefined });
    render(<RunIntegritySummary api={api} run={run} tasks={tasks} loading={false} error={null} />);
    expect(await screen.findByText(/0 из 2 подтверждено; 0 без строгой QA, 2 не проверено/)).toBeInTheDocument();
    cleanup();
    const failure = adapter(async () => { throw new Error('unavailable'); });
    render(<RunIntegritySummary api={failure} run={run} tasks={tasks} loading={false} error={null} />);
    expect(await screen.findByText(/0 из 2 подтверждено; 0 без строгой QA, 2 не проверено/)).toBeInTheDocument();
    expect(screen.getByText(/Нет полного набора подтверждённых QA receipts/)).toBeInTheDocument();
  });
  it('does not claim task progress or request QA after task-list GET failure', () => {
    const api = adapter(async id => receipt(id));
    render(<RunIntegritySummary api={api} run={run} tasks={tasks}
      loading={false} error={new Error('task GET failed')} />);
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('неизвестна');
    expect(screen.getByTestId('run-next-action')).toHaveTextContent('Серверный список задач не подтверждён');
    expect(screen.getByRole('alert')).toHaveTextContent('данные сервера недоступны');
    expect(vi.mocked(api.getTaskQaStatus)).not.toHaveBeenCalled();
  });
  it('ignores late QA receipts after unmount and does not fan out for huge runs', async () => {
    let done!: (r: TaskQaStatus) => void;
    const api = adapter(() => new Promise(resolve => { done = resolve; }));
    const first = render(<RunIntegritySummary api={api} run={run} tasks={[tasks[0]]}
      loading={false} error={null} />);
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('загрузка');
    first.unmount();
    await act(async () => done(receipt(tasks[0].id)));
    const many = Array.from({ length: 26 }, (_, n) => ({ ...tasks[0], id: 'many-' + n }));
    render(<RunIntegritySummary api={api} run={run} tasks={many} loading={false} error={null} />);
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('слишком много задач');
    expect(vi.mocked(api.getTaskQaStatus)).toHaveBeenCalledTimes(1);
  });
  it('renders only the actual dedicated-operator receipt and survives stale/error cases', async () => {
    const verified = adapter(async id => receipt(id));
    vi.mocked(verified.getRunReleaseApproval).mockResolvedValue({
      run_id: run.id, required: true, status: 'approved',
      approved_at: '2026-11-10T00:00:00Z',
    });
    const first = render(<RunIntegritySummary api={verified} run={run} tasks={tasks}
      loading={false} error={null} />);
    expect(await screen.findByText(/Отдельный операторский ключ зарегистрировал release approval/)).toBeInTheDocument();
    expect(screen.getByTestId('run-release-boundary')).toHaveTextContent('Операторское разрешение сохранено');
    first.unmount();

    const unverified = adapter(async id => receipt(id));
    vi.mocked(unverified.getRunReleaseApproval).mockResolvedValue({
      run_id: 'other-run', required: true, status: 'approved', approved_at: '2026-11-10T00:00:00Z',
    });
    const second = render(<RunIntegritySummary api={unverified} run={run} tasks={tasks}
      loading={false} error={null} />);
    expect(await screen.findByText(/Подтверждения выпуска нет/)).toBeInTheDocument();
    expect(screen.getByTestId('run-release-boundary')).toHaveTextContent('статус неизвестен');
    second.unmount();

    const unavailable = adapter(async id => receipt(id));
    vi.mocked(unavailable.getRunReleaseApproval).mockRejectedValue(new Error('offline'));
    render(<RunIntegritySummary api={unavailable} run={run} tasks={tasks}
      loading={false} error={null} />);
    expect(await screen.findByText(/Подтверждения выпуска нет/)).toBeInTheDocument();
    expect(screen.queryByText(/Операторское разрешение сохранено/)).not.toBeInTheDocument();
  });

  it('explains blocked, unknown and legacy outcomes', () => {
    expect(runNextAction(run, [{ ...tasks[0], status: 'blocked' }], true)).toContain('операторской сверки');
    expect(runNextAction(run, tasks, false)).toContain('Серверный список задач не подтверждён');
    expect(runNextAction({ ...run, input_data: {} }, tasks, true)).toContain('Версия источника не подтверждена');
    expect(runNextAction(run, [], true)).toContain('Задач нет');
    expect(runNextAction({ ...run, status: 'cancelled' }, tasks, true)).toContain('отменён');
    expect(runNextAction(run, [{ ...tasks[0], status: 'in_progress' }], true))
      .toContain('выполняющиеся задачи');
  });
});
