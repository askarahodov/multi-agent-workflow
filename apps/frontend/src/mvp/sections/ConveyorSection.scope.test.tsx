import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ConveyorSection, { listConveyorRuns } from './ConveyorSection';
import { MockAdapter } from '../../api/mockAdapter';
import { useMvpStore } from '../mvpStore';
import type { RunResponse, TaskResponse } from '../../api/types';

const run = (id: string, project_id: string): RunResponse => ({
  id, project_id, name: id, status: 'running', version: 1,
});
const task = (id: string, workflow_run_id: string): TaskResponse => ({
  id, workflow_run_id, title: id, status: 'pending',
  priority: 0, attempt_count: 0, max_attempts: 1, version: 1,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => cleanup());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('project-scoped conveyor', () => {
  it('paginates every run, excludes foreign-project results and rejects cursor loops', async () => {
    const api = new MockAdapter();
    const list = vi.spyOn(api, 'listRuns').mockImplementation(async (params) => ({
      items: params?.after ? [run('local-second', 'p1'), run('foreign', 'p2')]
        : [run('local-first', 'p1'), run('also-foreign', 'p2')],
      next_cursor: params?.after ? null : 'second',
    }));
    const rows = await listConveyorRuns(api, 'p1');
    expect(rows.map((item) => item.id)).toEqual(['local-first', 'local-second']);
    expect(list).toHaveBeenCalledWith({ projectId: 'p1', after: 'second', limit: 100 });
    list.mockResolvedValue({ items: [], next_cursor: 'duplicate' });
    await expect(listConveyorRuns(api, 'p1')).rejects.toThrow('повторяет курсор');
  });

  it('hides foreign run options and clears selected task on project switch', async () => {
    const api = new MockAdapter();
    const a = run('run-a', 'p1'), b = run('run-b', 'p2');
    vi.spyOn(api, 'listRuns').mockResolvedValue({ items: [a, b], next_cursor: null });
    vi.spyOn(api, 'listRunTasks').mockImplementation(async (id) => ({
      items: [task('task-' + id, id)], next_cursor: null,
    }));
    act(() => useMvpStore.setState({ api, projectId: 'p1', runId: a.id, taskId: 'task-a' }));
    render(<ConveyorSection />);
    expect(await screen.findByText('task-run-a')).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'run-b' })).not.toBeInTheDocument();

    act(() => useMvpStore.getState().selectProject('p2'));
    expect(useMvpStore.getState().runId).toBeNull();
    expect(useMvpStore.getState().taskId).toBeNull();
    expect(screen.queryByText('task-run-a')).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'run-a' })).not.toBeInTheDocument();
    await screen.findByRole('option', { name: 'run-b' });
    fireEvent.change(screen.getByTestId('conveyor-run-select'), { target: { value: 'run-b' } });
    expect(await screen.findByText('task-run-b')).toBeInTheDocument();
    expect(screen.queryByText('task-run-a')).not.toBeInTheDocument();
  });

  it('never displays a previous run response during a new selection or after a late completion', async () => {
    const api = new MockAdapter();
    const old = run('old-run', 'p1'), next = run('next-run', 'p1');
    vi.spyOn(api, 'listRuns').mockResolvedValue({ items: [old, next], next_cursor: null });
    const delayed = deferred<{ items: TaskResponse[]; next_cursor: null }>();
    vi.spyOn(api, 'listRunTasks').mockImplementation((id) => id === old.id
      ? delayed.promise : Promise.resolve({ items: [task('next-task', next.id)], next_cursor: null }));
    act(() => useMvpStore.setState({ api, projectId: 'p1', runId: old.id, taskId: null }));
    render(<ConveyorSection />);
    await screen.findByRole('option', { name: next.id });
    act(() => useMvpStore.getState().selectRun(next.id));
    expect(await screen.findByText('next-task')).toBeInTheDocument();

    await act(async () => delayed.resolve({ items: [task('old-task', old.id)], next_cursor: null }));
    expect(screen.queryByText('old-task')).not.toBeInTheDocument();
    expect(screen.getByText('next-task')).toBeInTheDocument();

    // A server returning mismatched task ownership must also be masked.
    vi.mocked(api.listRunTasks).mockResolvedValue({
      items: [task('wrong-owner', old.id)], next_cursor: null,
    });
    act(() => useMvpStore.getState().selectRun(old.id));
    act(() => useMvpStore.getState().selectRun(next.id));
    await waitFor(() => expect(api.listRunTasks).toHaveBeenCalledWith(next.id));
    expect(screen.queryByText('wrong-owner')).not.toBeInTheDocument();
  });
});
