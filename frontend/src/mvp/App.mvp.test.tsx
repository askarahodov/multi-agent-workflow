import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import App from '../App';
import { diffToEvents, snapshotToKey } from './sections/AgentLogSection';
import { useMvpStore } from './mvpStore';
import { MockAdapter } from '../api/mockAdapter';
import type { RunSnapshot } from '../api/types';

/** Inject the offline mock into the shared mvp store (like the editor panels do). */
function mountWithMock() {
  const api = new MockAdapter();
  act(() => {
    useMvpStore.setState({
      api,
      activeSection: 'project',
      projectId: 'proj_seed',
      runId: null,
      taskId: null,
    });
  });
  return api;
}

beforeEach(() => {
  cleanup();
  useMvpStore.getState().setSection('project');
  useMvpStore.getState().selectProject('proj_seed');
  useMvpStore.getState().selectRun(null);
  useMvpStore.getState().selectTask(null);
});

function snapshot(
  runStatus: string,
  tasks: Array<{ id: string; title: string; status: string }>,
): RunSnapshot {
  return {
    run: {
      id: 'run-1',
      project_id: 'proj_seed',
      name: 'My Run',
      status: runStatus,
      version: 1,
      created_at: '2026-10-09T00:00:00Z',
    },
    tasks: tasks.map((t) => ({
      id: t.id,
      workflow_run_id: 'run-1',
      title: t.title,
      status: t.status,
      priority: 0,
      attempt_count: 0,
      max_attempts: 1,
      version: 1,
    })),
  };
}

describe('App — MVP v1 navigation shell', () => {
  it('renders the sidebar navigation with all six MVP sections plus the editor', () => {
    const api = new MockAdapter();
    act(() => useMvpStore.setState({ api }));
    render(<App />);
    expect(screen.getByTestId('nav-project')).toBeInTheDocument();
    expect(screen.getByTestId('nav-board')).toBeInTheDocument();
    expect(screen.getByTestId('nav-conveyor')).toBeInTheDocument();
    expect(screen.getByTestId('nav-runs')).toBeInTheDocument();
    expect(screen.getByTestId('nav-task')).toBeInTheDocument();
    expect(screen.getByTestId('nav-agent-log')).toBeInTheDocument();
    expect(screen.getByTestId('nav-editor')).toBeInTheDocument();
  });

  it('switches to the runs section and shows the create form', () => {
    const api = new MockAdapter();
    act(() => useMvpStore.setState({ api }));
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-runs'));
    expect(screen.getByTestId('run-name-input')).toBeInTheDocument();
    expect(screen.getByTestId('run-create-button')).toBeInTheDocument();
  });

  it('creates and launches a run against the mock, listing it on the runs panel', async () => {
    const api = mountWithMock();
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-runs'));

    fireEvent.change(screen.getByTestId('run-name-input'), { target: { value: 'Launch Test' } });
    fireEvent.change(screen.getByTestId('task-title-input-0'), { target: { value: 'Research' } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('run-create-button'));
    });

    await waitFor(() => {
      // The run name appears in the runs list; if the created run is also the
      // selected run it renders in the detail card too, so assert >= 1 match.
      expect(screen.getAllByText('Launch Test').length).toBeGreaterThanOrEqual(1);
    });
    expect(api.listRuns).toBeDefined();
    const runs = await api.listRuns({});
    expect(runs.items.some((r) => r.name === 'Launch Test')).toBe(true);
  });
});

describe('SDLC dependency editor', () => {
  it('submits an ordered chain of earlier-stage IDs only when explicitly enabled', async () => {
    const api = mountWithMock();
    const launch = vi.spyOn(api, 'launchRun');
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-runs'));
    fireEvent.change(screen.getByTestId('run-name-input'), { target: { value: 'Sequential SDLC' } });
    fireEvent.change(screen.getByTestId('task-title-input-0'), { target: { value: 'Research' } });
    fireEvent.click(screen.getByTestId('add-task-row'));
    fireEvent.change(screen.getByTestId('task-title-input-1'), { target: { value: 'Architecture' } });
    fireEvent.click(screen.getByTestId('sequential-task-dependencies'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('run-create-button'));
    });
    await waitFor(() => expect(launch).toHaveBeenCalledOnce());
    expect(launch.mock.calls[0][0].tasks).toEqual([
      { title: 'Research', description: undefined, depends_on: [] },
      { title: 'Architecture', description: undefined, depends_on: [0] },
    ]);
  });
});

describe('Native SDLC QA evidence in task card', () => {
  it('shows independently signed QA after a fresh UI mount', async () => {
    const api = mountWithMock();
    const run = await api.launchRun({
      project_id: 'proj_seed',
      name: 'QA evidence display',
      tasks: [{ title: 'Implementation' }],
    });
    const task = (await api.listRunTasks(run.id)).items[0];
    vi.spyOn(api, 'getTaskQaStatus').mockResolvedValue({
      task_id: task.id,
      status: 'verified',
      attempt_id: 'attempt-verified',
      commit_sha: 'a'.repeat(40),
      gate_run_ids: {
        tester: 'g-tester',
        reviewer: 'g-reviewer',
        security: 'g-security',
      },
      issued_by: 'key-admin123456',
      issued_at: 1700000000,
    });
    act(() => useMvpStore.setState({
      api, activeSection: 'task', taskId: task.id,
    }));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('task-qa-status')).toHaveTextContent(
        'QA подтверждена операторским подписанным свидетельством',
      );
    });
    cleanup();
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('task-qa-status')).toHaveTextContent(
        'tester · reviewer · security',
      );
    });
  });
});

describe('AgentLogSection — snapshot diff (pure)', () => {
  it('emits a run-status event on the first poll', () => {
    const key = snapshotToKey(snapshot('running', []));
    const events = diffToEvents(null, key, 'My Run');
    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe('run');
    expect(events[0].level).toBe('info');
    expect(events[0].message).toContain('running');
  });

  it('emits a task event only when a task status changes between snapshots', () => {
    const before = snapshotToKey(
      snapshot('running', [{ id: 't1', title: 'Research', status: 'pending' }]),
    );
    const after = snapshotToKey(
      snapshot('running', [{ id: 't1', title: 'Research', status: 'completed' }]),
    );
    const events = diffToEvents(before, after, 'My Run');
    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe('task');
    expect(events[0].level).toBe('success');
    expect(events[0].task_id).toBe('t1');
    expect(events[0].message).toContain('completed');
  });

  it('emits nothing when nothing changed between snapshots', () => {
    const before = snapshotToKey(
      snapshot('running', [{ id: 't1', title: 'Research', status: 'pending' }]),
    );
    const same = snapshotToKey(
      snapshot('running', [{ id: 't1', title: 'Research', status: 'pending' }]),
    );
    expect(diffToEvents(before, same, 'My Run')).toHaveLength(0);
  });

  it('maps failed run to error level', () => {
    const key = snapshotToKey(snapshot('failed', []));
    const events = diffToEvents(null, key, 'My Run');
    expect(events[0].level).toBe('error');
  });
});
