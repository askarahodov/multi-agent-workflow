import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import TaskBoard, { collectPages, loadProjectBoard, statusColumn } from './TaskBoard';
import { useMvpStore } from '../../mvp/mvpStore';
import { MockAdapter } from '../../api/mockAdapter';
import type { RunResponse, TaskResponse } from '../../api/types';

const run = (id: string, project_id: string): RunResponse => ({ id, project_id, name: id, status: 'running', version: 1 });
const task = (id: string, workflow_run_id: string, status = 'pending'): TaskResponse => ({
  id, workflow_run_id, title: id, status, priority: 1, attempt_count: 0, max_attempts: 2, version: 1,
});

function setup() {
  const api = new MockAdapter();
  const runs = [run('run-a','proj-a'), run('run-b','proj-b')];
  const tasks = [task('a1','run-a'), task('a2','run-a','awaiting_qa'), task('b1','run-b','quarantined')];
  vi.spyOn(api,'listProjects').mockResolvedValue([
    {id:'proj-a',name:'Project A',version:1},{id:'proj-b',name:'Project B',version:1},
  ]);
  vi.spyOn(api,'listRuns').mockImplementation(async (params) => ({
    items: params?.after ? [runs[1]] : [runs[0]], next_cursor: params?.after ? null:'page-two',
  }));
  vi.spyOn(api,'listRunTasks').mockImplementation(async (id,params) => ({
    items: id==='run-a' ? params?.after ? [tasks[1]]:[tasks[0]]:[tasks[2]],
    next_cursor: id==='run-a'&&!params?.after ? 'task-page-2':null,
  }));
  act(()=>useMvpStore.setState({api,projectId:'proj-a',runId:null,taskId:null,activeSection:'board'}));
  return {api};
}
beforeEach(()=>{ cleanup(); });
afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe('TaskBoard core helpers', () => {
  it('collectPages fetches all pages respecting cursor', async () => {
    let page = 0;
    const lister = async (after?: string) => {
      if (page >= 2) return { items: [], next_cursor: undefined };
      page += 1;
      return { items: [page], next_cursor: page < 2 ? 'next' : undefined };
    };
    const result = await collectPages(lister, 5);
    expect(result).toEqual([1, 2]);
  });

  it('loadProjectBoard fetches runs and tasks', async () => {
    const { api } = setup();
    const { runs, tasks } = await loadProjectBoard(api, 'proj-a');
    expect(runs.length).toBe(2);
    expect(tasks.length).toBe(3);
  });

  it('statusColumn groups by status correctly', () => {
    const { api } = setup();
    const { tasks } = await loadProjectBoard(api, 'proj-a');
    const cols = statusColumn(tasks);
    expect(cols.pending.length).toBe(1);
    expect(cols.awaiting_qa.length).toBe(1);
    expect(cols.quarantined.length).toBe(1);
  });
});
