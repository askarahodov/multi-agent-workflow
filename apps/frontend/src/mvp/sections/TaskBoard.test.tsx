import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import TaskBoard, { collectPages, loadProjectBoard, statusColumn } from './TaskBoard';
import { useMvpStore } from '../../mvp/mvpStore';
import { MockAdapter } from '../../api/mockAdapter';
import type { RunResponse, TaskResponse } from '../../api/types';

const run=(id:string,project_id:string): RunResponse => ({id,project_id,name:id,status:'running',version:1});
const task=(id:string,workflow_run_id:string,status='pending'): TaskResponse => ({
  id,workflow_run_id,title:id,status,priority:1,attempt_count:0,max_attempts:2,version:1,
});
function setup() {
  const api = new MockAdapter();
  const runs = [run('run-a','proj-a'),run('run-b','proj-b')];
  const tasks = [task('a1','run-a'),task('a2','run-a','awaiting_qa'),task('b1','run-b','quarantined')];
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

describe('project-isolated runtime board',()=>{
  it('fetches every cursor page and excludes foreign project tasks before rendering',async ()=>{
    const {api}=setup();
    render(<TaskBoard/>);
    expect(await screen.findByTestId('board-task-pending-a1')).toBeInTheDocument();
    expect(screen.getByTestId('board-task-qa-a2')).toBeInTheDocument();
    expect(screen.queryByText('b1')).not.toBeInTheDocument();
    expect(api.listRunTasks).toHaveBeenCalledWith('run-a',expect.objectContaining({after:'task-page-2'}));
    expect(api.listRunTasks).not.toHaveBeenCalledWith('run-b',expect.anything());
    fireEvent.click(screen.getByTestId('board-task-qa-a2'));
    expect(useMvpStore.getState().taskId).toBe('a2');
    expect(useMvpStore.getState().runId).toBe('run-a');
  });

  it('switches project, never displays stale tasks, and does not invent a running status',async ()=>{
    setup();render(<TaskBoard/>);
    await screen.findByTestId('board-task-qa-a2');
    fireEvent.change(screen.getByTestId('board-project-filter'),{target:{value:'proj-b'}});
    await screen.findByTestId('board-task-quarantine-b1');
    expect(screen.queryByTestId('board-task-qa-a2')).not.toBeInTheDocument();
    expect(useMvpStore.getState().runId).toBeNull();
  });

  it('fails closed on inconsistent task/run ownership or repeating cursor',async ()=>{
    const {api}=setup();
    vi.mocked(api.listRunTasks).mockResolvedValue({items:[task('wrong','another-run')],next_cursor:null});
    await expect(loadProjectBoard(api,'proj-a')).rejects.toThrow('другому запуску');
    await expect(collectPages(async ()=>({items:[],next_cursor:'repeat'}))).rejects.toThrow('повторяющийся курсор');
    expect(statusColumn('custom_native_unknown')).toBe('other');
    expect(statusColumn('awaiting_qa')).toBe('qa');
    expect(statusColumn('quarantined')).toBe('quarantine');
  });

  it('refreshes from server without ever mutating task status',async ()=>{
    const {api}=setup();const claim=vi.spyOn(api,'claimTask');
    render(<TaskBoard/>);await screen.findByTestId('board-task-pending-a1');
    fireEvent.click(screen.getByRole('button',{name:'Обновить'}));
    await waitFor(()=>expect(api.listRuns).toHaveBeenCalledTimes(4));
    expect(claim).not.toHaveBeenCalled();
  });
});
