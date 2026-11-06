import { beforeEach, describe, expect, it } from 'vitest';
import { useMvpStore } from './mvpStore';

beforeEach(() => {
  useMvpStore.setState({ projectId: null, runId: null, taskId: null });
});

describe('project → run → task selection integrity', () => {
  it('clears run and task atomically when the project changes', () => {
    const { selectProject, selectRun, selectTask } = useMvpStore.getState();
    selectProject('project-a');
    selectRun('run-a');
    selectTask('task-a');

    const snapshots: Array<[string | null, string | null, string | null]> = [];
    const unsubscribe = useMvpStore.subscribe((state) => {
      snapshots.push([state.projectId, state.runId, state.taskId]);
    });
    selectProject('project-b');
    unsubscribe();

    expect(snapshots).toEqual([['project-b', null, null]]);
    expect(useMvpStore.getState()).toMatchObject({
      projectId: 'project-b', runId: null, taskId: null,
    });
  });

  it('clears the old task when a different run is selected', () => {
    const { selectProject, selectRun, selectTask } = useMvpStore.getState();
    selectProject('project-a');
    selectRun('run-a');
    selectTask('task-a');
    selectRun('run-b');
    expect(useMvpStore.getState()).toMatchObject({
      projectId: 'project-a', runId: 'run-b', taskId: null,
    });
  });

  it('preserves dependent selections when reselecting the same identifiers', () => {
    const { selectProject, selectRun, selectTask } = useMvpStore.getState();
    selectProject('project-a');
    selectRun('run-a');
    selectTask('task-a');
    selectProject('project-a');
    selectRun('run-a');
    expect(useMvpStore.getState()).toMatchObject({
      projectId: 'project-a', runId: 'run-a', taskId: 'task-a',
    });
  });

  it('clears dependent selections on deselect, including selecting no project', () => {
    const { selectProject, selectRun, selectTask } = useMvpStore.getState();
    selectProject('project-a');
    selectRun('run-a');
    selectTask('task-a');
    selectRun(null);
    expect(useMvpStore.getState().taskId).toBeNull();
    selectRun('run-b');
    selectTask('task-b');
    selectProject(null);
    expect(useMvpStore.getState()).toMatchObject({
      projectId: null, runId: null, taskId: null,
    });
  });
});
