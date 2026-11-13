import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ApiAdapter, RunResponse, TaskResponse, TaskQaStatus, AttemptResponse, GitEvidenceResponse } from '../../api/types';
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
  task_id: id, status: 'verified', attempt_id: 'attempt-' + id, commit_sha: 'a'.repeat(40),
  issued_by: 'operator', gate_run_ids: { tester: 't', reviewer: 'r', security: 's' },
});
const attemptsFor = (id: string): AttemptResponse[] => [{
  id: 'attempt-' + id, task_id: id, attempt_number: 1,
  status: 'completed', version: 1,
}];
const gitFor = (id: string): GitEvidenceResponse[] => [{
  task_id: id, attempt_id: 'attempt-' + id, commit_sha: 'a'.repeat(40),
  provenance: 'worker_reported', changed_paths: ['src/verified.py'],
}];
function adapter(fn: (id: string) => Promise<TaskQaStatus>) {
  return {
    getTaskQaStatus: vi.fn(fn),
    listTaskAttempts: vi.fn(async (id: string) => attemptsFor(id)),
    listTaskGitEvidence: vi.fn(async (id: string) => gitFor(id)),
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
    expect(screen.getByTestId('run-integrity-summary')).toHaveTextContent('завершённой попыткой');
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
    expect(screen.getByText(/Нет полного набора согласованных QA/)).toBeInTheDocument();
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
  it('re-reads QA on refresh even when task IDs are unchanged and revokes stale verified status immediately', async () => {
    let pending: ((r: TaskQaStatus) => void) | undefined;
    let version = 0;
    const api = adapter(async id => {
      if (version === 0) return receipt(id);
      return new Promise<TaskQaStatus>(resolve => { pending = resolve; });
    });
    const view = render(<RunIntegritySummary api={api} run={run} tasks={[tasks[0]]}
      loading={false} error={null} refreshKey={0} />);
    expect(await screen.findByText(/1 из 1 подтверждено/)).toBeInTheDocument();
    expect(screen.getByText(/Для всех задач QA receipt совпал/)).toBeInTheDocument();
    version = 1;
    view.rerender(<RunIntegritySummary api={api} run={run} tasks={[tasks[0]]}
      loading={false} error={null} refreshKey={1} />);
    // The previously verified value must not survive the first render of
    // the refreshed generation, even while the next response is in flight.
    expect(screen.queryByText(/Для всех задач QA receipt совпал/)).not.toBeInTheDocument();
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('загрузка');
    await waitFor(() => expect(vi.mocked(api.getTaskQaStatus)).toHaveBeenCalledTimes(2));
    await act(async () => pending?.({
      task_id: tasks[0].id, status: 'pending',
    }));
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('0 из 1 подтверждено');
    expect(screen.getByText(/Нет полного набора согласованных QA/)).toBeInTheDocument();
  });

  it('rejects a late successful reply from the previous refresh generation', async () => {
    const responders: Array<(r: TaskQaStatus) => void> = [];
    const api = adapter(() => new Promise(resolve => { responders.push(resolve); }));
    const view = render(<RunIntegritySummary api={api} run={run} tasks={[tasks[0]]}
      loading={false} error={null} refreshKey={0} />);
    expect(responders).toHaveLength(1);
    view.rerender(<RunIntegritySummary api={api} run={run} tasks={[tasks[0]]}
      loading={false} error={null} refreshKey={1} />);
    expect(responders).toHaveLength(2);
    await act(async () => responders[0](receipt(tasks[0].id)));
    expect(screen.queryByText(/Для всех задач QA receipt совпал/)).not.toBeInTheDocument();
    await act(async () => responders[1]({ task_id: tasks[0].id, status: 'pending' }));
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('0 из 1 подтверждено');
  });

  it('invalidates a QA receipt after task version/attempt changes on the same run', async () => {
    const api = adapter(async id => receipt(id));
    const view = render(<RunIntegritySummary api={api} run={run} tasks={[tasks[0]]}
      loading={false} error={null} />);
    expect(await screen.findByText(/1 из 1 подтверждено/)).toBeInTheDocument();
    const changed = { ...tasks[0], version: 2, attempt_count: 3, status: 'in_progress' };
    view.rerender(<RunIntegritySummary api={api} run={run} tasks={[changed]}
      loading={false} error={null} />);
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('загрузка');
    await waitFor(() => expect(vi.mocked(api.getTaskQaStatus)).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('не проверено');
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

    const contradictory = adapter(async id => receipt(id));
    vi.mocked(contradictory.getRunReleaseApproval).mockResolvedValue({
      run_id: run.id, required: false, status: 'approved',
      approved_at: '2026-11-10T00:00:00Z',
    });
    const third = render(<RunIntegritySummary api={contradictory} run={run} tasks={tasks}
      loading={false} error={null} />);
    expect(await screen.findByText(/Подтверждения выпуска нет/)).toBeInTheDocument();
    expect(screen.queryByText(/Операторское разрешение сохранено/)).not.toBeInTheDocument();
    third.unmount();

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
  it('refuses a mixed-run page without fetching QA or claiming completed progress',()=>{
    const api=adapter(async id=>receipt(id));
    render(<RunIntegritySummary api={api} run={run}
      tasks={[tasks[0],{...tasks[1],workflow_run_id:'another-run'}]}
      loading={false} error={null}/>);
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('неизвестна');
    expect(screen.getByTestId('run-next-action')).toHaveTextContent('Серверный список задач не подтверждён');
    expect(screen.getByRole('alert')).toHaveTextContent('другому запуску');
    expect(api.getTaskQaStatus).not.toHaveBeenCalled();
  });
  it('rejects duplicated task identities instead of counting one QA twice',()=>{
    const api=adapter(async id=>receipt(id));
    render(<RunIntegritySummary api={api} run={run}
      tasks={[tasks[0],{...tasks[0]}]} loading={false} error={null}/>);
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('неизвестна');
    expect(api.getTaskQaStatus).not.toHaveBeenCalled();
  });


  it('refuses forged QA attempt, mismatched commit and a failed attempt', async () => {
    for (const variant of ['wrong-attempt', 'wrong-commit', 'failed-attempt'] as const) {
      const api = adapter(async id => variant === 'wrong-attempt'
        ? {...receipt(id), attempt_id: 'forged'}
        : variant === 'wrong-commit'
          ? {...receipt(id), commit_sha: 'b'.repeat(40)}
          : receipt(id));
      if (variant === 'failed-attempt') {
        vi.mocked(api.listTaskAttempts).mockImplementation(async id =>
          attemptsFor(id).map(a => ({...a, status: 'failed'})));
      }
      const view = render(<RunIntegritySummary api={api} run={run}
        tasks={[tasks[0]]} loading={false} error={null} />);
      expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
      expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('1 не проверено');
      expect(screen.getByTestId('run-integrity-summary')).not.toHaveTextContent(
        'Для всех задач QA receipt совпал',
      );
      view.unmount();
    }
  });

  it('rejects foreign, duplicate or malformed evidence lists instead of counting QA', async () => {
    const api = adapter(async id => receipt(id));
    vi.mocked(api.listTaskAttempts).mockResolvedValue([
      {...attemptsFor(tasks[0].id)[0], task_id: 'other-task'},
    ]);
    const view = render(<RunIntegritySummary api={api} run={run}
      tasks={[tasks[0]]} loading={false} error={null} />);
    expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
    view.unmount();

    const duplicate = adapter(async id => receipt(id));
    vi.mocked(duplicate.listTaskAttempts).mockImplementation(async id => [
      ...attemptsFor(id), ...attemptsFor(id),
    ]);
    const view2 = render(<RunIntegritySummary api={duplicate} run={run}
      tasks={[tasks[0]]} loading={false} error={null} />);
    expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
    view2.unmount();

    const unsafe = adapter(async id => receipt(id));
    vi.mocked(unsafe.listTaskGitEvidence).mockImplementation(async id => [
      {...gitFor(id)[0], changed_paths: ['../private.key']},
    ]);
    render(<RunIntegritySummary api={unsafe} run={run}
      tasks={[tasks[0]]} loading={false} error={null} />);
    expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
  });

  it('keeps QA unknown if the attempts or git endpoints fail', async () => {
    for (const failing of ['attempts', 'git'] as const) {
      const api = adapter(async id => receipt(id));
      if (failing === 'attempts') vi.mocked(api.listTaskAttempts)
        .mockRejectedValue(new Error('attempts down'));
      else vi.mocked(api.listTaskGitEvidence)
        .mockRejectedValue(new Error('git down'));
      const view = render(<RunIntegritySummary api={api} run={run}
        tasks={[tasks[0]]} loading={false} error={null} />);
      expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
      view.unmount();
    }
  });

  it('cannot re-use a verified QA or operator approval from another API adapter', async () => {
    const first = adapter(async id => receipt(id));
    vi.mocked(first.getRunReleaseApproval).mockResolvedValue({
      run_id: run.id, required: true, status: 'approved',
      approved_at: '2026-11-10T00:00:00Z',
    });
    const next = adapter(async id => ({ task_id: id, status: 'pending' }));
    const view = render(<RunIntegritySummary api={first} run={run}
      tasks={[tasks[0]]} loading={false} error={null} />);
    expect(await screen.findByText(/1 из 1 подтверждено/)).toBeInTheDocument();
    expect(await screen.findByText(/Операторское разрешение сохранено/)).toBeInTheDocument();

    view.rerender(<RunIntegritySummary api={next} run={run}
      tasks={[tasks[0]]} loading={false} error={null} />);
    // No stale approval/QA even on the synchronous render before new effects.
    expect(screen.queryByText(/Операторское разрешение сохранено/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1 из 1 подтверждено/)).not.toBeInTheDocument();
    expect(screen.getByTestId('run-qa-summary')).toHaveTextContent('загрузка');
    expect(await screen.findByText(/0 из 1 подтверждено/)).toBeInTheDocument();
    expect(await screen.findByText(/политика выключена/)).toBeInTheDocument();
  });

});
