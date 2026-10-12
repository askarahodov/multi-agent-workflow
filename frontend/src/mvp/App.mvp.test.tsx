import { beforeEach, describe, expect, it } from 'vitest';
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
