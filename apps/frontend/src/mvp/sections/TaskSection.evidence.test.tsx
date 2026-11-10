import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import type {ApiAdapter,RunResponse,TaskResponse,TaskQaStatus} from '../../api/types';
import {useMvpStore} from '../mvpStore';
import TaskSection from './TaskSection';

const run:RunResponse={id:'run-A',project_id:'project-A',name:'Verified run',
  status:'running',version:1,input_data:{_workflow_version_id:'immutable-v1'}};
const task:TaskResponse={id:'task-A',workflow_run_id:run.id,title:'Protected task',
  status:'pending',priority:1,attempt_count:0,max_attempts:2,version:1,contract_id:'contract-A'};
const qa=(taskId='task-A'):TaskQaStatus=>({task_id:taskId,status:'verified',
  commit_sha:'a'.repeat(40),issued_by:'independent QA',
  gate_run_ids:{tester:'gate-t',reviewer:'gate-r',security:'gate-s'}});
function adapter():ApiAdapter{
  return {
    getTask:vi.fn(async()=>task),
    getRun:vi.fn(async()=>run),
    listTaskAttempts:vi.fn(async()=>[]),
    listTaskGitEvidence:vi.fn(async()=>[]),
    getTaskQaStatus:vi.fn(async()=>({task_id:task.id,status:'pending'})),
  } as unknown as ApiAdapter;
}
beforeEach(()=>{act(()=>useMvpStore.setState({
  api:adapter(),projectId:'project-A',runId:run.id,taskId:task.id,activeSection:'task',
}));});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
describe('read-only task ownership and evidence',()=>{
  it('never requests attempts/Git/QA before independently verifying run and project',async()=>{
    const api=useMvpStore.getState().api;
    let release!:(value:RunResponse)=>void;
    vi.mocked(api.getRun).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
    render(<TaskSection/>);
    await waitFor(()=>expect(api.getRun).toHaveBeenCalledWith(run.id));
    expect(api.listTaskAttempts).not.toHaveBeenCalled();
    expect(api.listTaskGitEvidence).not.toHaveBeenCalled();
    expect(api.getTaskQaStatus).not.toHaveBeenCalled();
    await act(async()=>release({...run,project_id:'other-project'}));
    expect(await screen.findByTestId('task-scope-error')).toHaveTextContent('не подтверждена');
    expect(screen.queryByTestId('task-run-verified')).not.toBeInTheDocument();
    expect(api.listTaskAttempts).not.toHaveBeenCalled();
  });
  it('rejects a task from another selected run without fetching evidence',async()=>{
    const api=useMvpStore.getState().api;
    vi.mocked(api.getTask).mockResolvedValue({...task,workflow_run_id:'foreign-run'});
    render(<TaskSection/>);
    expect(await screen.findByTestId('task-scope-error')).toHaveTextContent('не подтверждена');
    expect(api.getRun).not.toHaveBeenCalled();
    expect(api.getTaskQaStatus).not.toHaveBeenCalled();
  });
  it('displays independently verified QA only for matching complete receipt',async()=>{
    const api=useMvpStore.getState().api;
    vi.mocked(api.getTaskQaStatus).mockResolvedValue(qa());
    vi.mocked(api.listTaskAttempts).mockResolvedValue([{
      id:'attempt-A',task_id:task.id,attempt_number:1,status:'completed',version:1,
    }]);
    vi.mocked(api.listTaskGitEvidence).mockResolvedValue([{
      task_id:task.id,attempt_id:'attempt-A',commit_sha:'a'.repeat(40),
      changed_paths:['out/result.json'],provenance:'worker_reported',
    }]);
    render(<TaskSection/>);
    expect(await screen.findByTestId('task-run-verified')).toHaveTextContent('project-A');
    expect(await screen.findByText('QA подтверждена операторским подписанным свидетельством.'))
      .toBeInTheDocument();
    expect(screen.getByTestId('task-git-artifact')).toHaveTextContent('out/result.json');
    expect(screen.queryByTestId('task-qa-invalid')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-claim-button')).not.toBeInTheDocument();
  });
  it('fails closed on forged QA status and foreign Git/attempt records',async()=>{
    const api=useMvpStore.getState().api;
    vi.mocked(api.getTaskQaStatus).mockResolvedValue({...qa(),gate_run_ids:undefined});
    vi.mocked(api.listTaskGitEvidence).mockResolvedValue([{
      task_id:'other-task',attempt_id:'attempt-A',commit_sha:'a'.repeat(40),
      changed_paths:['out/file'],provenance:'worker_reported',
    }]);
    vi.mocked(api.listTaskAttempts).mockResolvedValue([{
      id:'foreign-attempt',task_id:'other-task',attempt_number:1,status:'completed',version:1,
    }]);
    render(<TaskSection/>);
    expect(await screen.findByTestId('task-qa-invalid')).toHaveTextContent('Нет достоверного');
    expect(await screen.findByTestId('task-git-invalid')).toHaveTextContent('артефакты скрыты');
    expect(await screen.findByTestId('task-attempts-invalid')).toHaveTextContent('записи скрыты');
    expect(screen.queryByText('QA подтверждена операторским подписанным свидетельством.'))
      .not.toBeInTheDocument();
    expect(screen.queryByTestId('task-git-artifact')).not.toBeInTheDocument();
  });
  it('does not revive old task details after project A -> B -> A during delayed verification',async()=>{
    const api=useMvpStore.getState().api;
    let release!:(value:RunResponse)=>void;
    vi.mocked(api.getRun).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
    render(<TaskSection/>);
    await waitFor(()=>expect(api.getRun).toHaveBeenCalledOnce());
    act(()=>useMvpStore.getState().selectProject('project-B'));
    expect(screen.getByText('Задача не выбрана.')).toBeInTheDocument();
    act(()=>useMvpStore.getState().selectProject('project-A'));
    await act(async()=>release(run));
    expect(screen.queryByTestId('task-run-verified')).not.toBeInTheDocument();
    expect(api.getTaskQaStatus).not.toHaveBeenCalled();
  });
  it('revokes positive QA and rechecks ownership before refresh can show it again',async()=>{
    const api=useMvpStore.getState().api;
    vi.mocked(api.getTaskQaStatus).mockResolvedValueOnce(qa()).mockResolvedValueOnce({
      task_id:task.id,status:'pending',
    });
    render(<TaskSection/>);
    expect(await screen.findByText('QA подтверждена операторским подписанным свидетельством.'))
      .toBeInTheDocument();
    const initialCalls=vi.mocked(api.getRun).mock.calls.length;
    fireEvent.click(screen.getByRole('button',{name:'Обновить'}));
    expect(screen.queryByText('QA подтверждена операторским подписанным свидетельством.'))
      .not.toBeInTheDocument();
    await waitFor(()=>expect(vi.mocked(api.getRun).mock.calls.length).toBeGreaterThan(initialCalls));
    expect(await screen.findByText(/Ожидается независимая QA/)).toBeInTheDocument();
    expect(screen.queryByTestId('task-qa-invalid')).not.toBeInTheDocument();
  });
});
