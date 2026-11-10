import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProblemDetailsError } from '../../api/client';
import type {
  ApiAdapter, ReconciliationRequest, ReconciliationResponse, TaskResponse,
} from '../../api/types';
import RecoverySection from './RecoverySection';
import { useMvpStore } from '../mvpStore';

const task: TaskResponse = {
  id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  workflow_run_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  title: 'Прерванная задача', status: 'blocked',
  priority: 0, attempt_count: 1, max_attempts: 2, version: 2,
};

const response: ReconciliationResponse = {
  task_id: task.id,
  decision: 'UNKNOWN',
  evidence_ref: 'qa/incident-123',
  evidence_sha256: 'a'.repeat(64),
  operator_subject: 'test-admin',
  decided_at: '2026-10-15T10:00:00Z',
};

function makeAdapter(overrides: Record<string, unknown> = {}) {
  const methods = {
    listRecoveryQuarantine: vi.fn().mockResolvedValue([task]),
    getRun: vi.fn().mockResolvedValue({
      id: task.workflow_run_id, project_id: 'project-A', name: 'Recovered run',
      status: 'running', version: 1,
    }),
    getRecoveryReconciliation: vi.fn().mockRejectedValue(
      new ProblemDetailsError({ status: 404, title: 'Not found' }),
    ),
    getRecoveryLedger: vi.fn().mockResolvedValue({
      task_id: task.id,
      ledger_status: 'AVAILABLE',
      attempts: [{ attempt_id: 'attempt-1', record_status: 'RECORDS', entries: [
        { call_ref: 'fingerprint-1234', tool: 'write_file', state: 'CLAIMED' },
      ] }],
    }),
    attestRecovery: vi.fn().mockResolvedValue(response),
    claimTask: vi.fn(),
    submitTask: vi.fn(),
    ...overrides,
  };
  return { adapter: methods as unknown as ApiAdapter, methods };
}

afterEach(() => {
  sessionStorage.removeItem('maw:recovery-uncertain-posts:v1');
  vi.clearAllMocks();
  act(() => useMvpStore.setState({ runId: null, taskId: null, projectId: null }));
});

describe('operator recovery console', () => {
  it('deep-links the selected task but hides quarantine from other runs', async () => {
    const other: TaskResponse = {
      ...task, id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
      workflow_run_id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
      title: 'Чужая карантинная задача',
    };
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockResolvedValue([other, task]),
    });
    act(() => useMvpStore.setState({
      runId: task.workflow_run_id, taskId: task.id,
    }));
    render(<RecoverySection adapter={adapter} />);
    expect(await screen.findByTestId('recovery-task-' + task.id)).toBeInTheDocument();
    await waitFor(() => expect(methods.getRecoveryLedger).toHaveBeenCalledWith(task.id));
    expect(screen.queryByTestId('recovery-task-' + other.id)).not.toBeInTheDocument();
    expect(screen.getByTestId('recovery-run-scope')).toHaveTextContent(task.workflow_run_id);
    expect(methods.getRecoveryLedger).not.toHaveBeenCalledWith(other.id);
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('clears an old selected task and its form when the run changes', async () => {
    const other: TaskResponse = {
      ...task, id: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
      workflow_run_id: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
      title: 'Новая задача',
    };
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockResolvedValue([task, other]),
    });
    act(() => useMvpStore.setState({ runId: task.workflow_run_id, taskId: task.id }));
    render(<RecoverySection adapter={adapter} />);
    await screen.findByTestId('recovery-attest');
    act(() => useMvpStore.getState().selectRun(other.workflow_run_id));
    await waitFor(() => expect(screen.queryByTestId('recovery-attest')).not.toBeInTheDocument());
    expect(screen.queryByTestId('recovery-task-' + task.id)).not.toBeInTheDocument();
    expect(await screen.findByTestId('recovery-task-' + other.id)).toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('does not attest a task absent from the server quarantine list', async () => {
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockResolvedValue([]),
    });
    act(() => useMvpStore.setState({ runId: task.workflow_run_id, taskId: task.id }));
    render(<RecoverySection adapter={adapter} />);
    expect(await screen.findByText('В выбранном запуске карантинных задач нет.')).toBeInTheDocument();
    expect(screen.queryByTestId('recovery-attest')).not.toBeInTheDocument();
    expect(methods.getRecoveryLedger).not.toHaveBeenCalled();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('does not spend tokens, claim tasks or mutate anything on mount', async () => {
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockResolvedValue([]),
    });
    render(<RecoverySection adapter={adapter} />);
    expect(await screen.findByText('Карантинных задач нет.')).toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
    expect(methods.claimTask).not.toHaveBeenCalled();
    expect(methods.submitTask).not.toHaveBeenCalled();
  });

  it('requires review before recording UNKNOWN and keeps task blocked', async () => {
    const { adapter, methods } = makeAdapter();
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    expect(await screen.findByText(/Есть вызовы CLAIMED/)).toBeInTheDocument();

    const save = screen.getByTestId('recovery-attest') as HTMLButtonElement;
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'), {
      target: { value: 'qa/incident-123' },
    });
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'), {
      target: { value: 'a'.repeat(64) },
    });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(methods.attestRecovery).toHaveBeenCalledWith(task.id, {
      decision: 'UNKNOWN', evidence_ref: 'qa/incident-123',
      evidence_sha256: 'a'.repeat(64),
    } satisfies ReconciliationRequest));
    expect(await screen.findByTestId('recovery-decision')).toHaveTextContent('UNKNOWN');
    expect(methods.claimTask).not.toHaveBeenCalled();
    expect(methods.submitTask).not.toHaveBeenCalled();
  });

  it('does not permit confirmed decision with unavailable ledger', async () => {
    const { adapter, methods } = makeAdapter({
      getRecoveryLedger: vi.fn().mockRejectedValue(
        new ProblemDetailsError({ status: 503, title: 'Unconfigured' }),
      ),
    });
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    expect(await screen.findByText(/Журнал недоступен/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Решение'), {
      target: { value: 'CONFIRMED_SIDE_EFFECT' },
    });
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'), {
      target: { value: 'qa/incident-123' },
    });
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'), {
      target: { value: 'a'.repeat(64) },
    });
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByTestId('recovery-attest')).toBeDisabled();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('shows an immutable confirmed result without a new submission form', async () => {
    const { adapter, methods } = makeAdapter({
      getRecoveryReconciliation: vi.fn().mockResolvedValue({
        ...response, decision: 'CONFIRMED_SIDE_EFFECT',
      }),
    });
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    expect(await screen.findByText(/Решение подтверждено и неизменяемо/)).toBeInTheDocument();
    expect(screen.queryByTestId('recovery-attest')).not.toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('redacts leaked credential text from quarantined task and tool-ledger entries', async () => {
    const { adapter } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockResolvedValue([{
        ...task, title: 'Failed https://worker.test/run?api_key=quarantine-secret',
      }]),
      getRecoveryLedger: vi.fn().mockResolvedValue({
        task_id: task.id, ledger_status: 'AVAILABLE',
        attempts: [{
          attempt_id: 'attempt-secret', record_status: 'RECORDS',
          entries: [{
            call_ref: 'Authorization: Bearer call-secret',
            tool: 'https://tool.test/path?stream_ticket=ledger-secret',
            state: 'CLAIMED',
          }],
        }],
      }),
    });
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    await waitFor(() => expect(document.body.textContent).toContain('CLAIMED'));
    const rendered = document.body.textContent ?? '';
    for (const secret of ['quarantine-secret', 'call-secret', 'ledger-secret']) {
      expect(rendered).not.toContain(secret);
    }
    expect(rendered).toContain('[REDACTED]');
    expect(rendered).toContain('Попытка attempt-secret');
  });

  it('reports RBAC denial without exposing a form or retrying requests', async () => {
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockRejectedValue(
        new ProblemDetailsError({ status: 403, title: 'Forbidden' }),
      ),
    });
    render(<RecoverySection adapter={adapter} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Требуется доступ администратора.');
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });
  it('rejects a run in the wrong project before reading any quarantine tasks',async()=>{
    const {adapter,methods}=makeAdapter({getRun:vi.fn().mockResolvedValue({
      id:task.workflow_run_id,project_id:'project-foreign',name:'Foreign',
      status:'running',version:1,
    })});
    act(()=>useMvpStore.setState({projectId:'project-here',
      runId:task.workflow_run_id,taskId:task.id}));
    render(<RecoverySection adapter={adapter}/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Запрос не выполнен');
    expect(methods.getRun).toHaveBeenCalledWith(task.workflow_run_id);
    expect(methods.listRecoveryQuarantine).not.toHaveBeenCalled();
    expect(methods.getRecoveryReconciliation).not.toHaveBeenCalled();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('filters the global quarantine to server-confirmed runs in the active project',async()=>{
    const foreign={...task,id:'cccccccc-cccc-cccc-cccc-cccccccccccc',
      workflow_run_id:'dddddddd-dddd-dddd-dddd-dddddddddddd',
      title:'Private foreign quarantine'};
    const {adapter,methods}=makeAdapter({
      listRecoveryQuarantine:vi.fn().mockResolvedValue([task,foreign]),
      getRun:vi.fn(async(id:string)=>({
        id,project_id:id===task.workflow_run_id?'project-here':'other-project',
        name:'Run',status:'running',version:1,
      })),
    });
    act(()=>useMvpStore.setState({projectId:'project-here',runId:null,taskId:null}));
    render(<RecoverySection adapter={adapter}/>);
    expect(await screen.findByTestId('recovery-task-'+task.id)).toBeInTheDocument();
    expect(screen.queryByText('Private foreign quarantine')).not.toBeInTheDocument();
    expect(methods.getRun).toHaveBeenCalledTimes(2);
    expect(methods.getRecoveryLedger).not.toHaveBeenCalled();
  });

  it('fails closed when prior reconciliation GET is forbidden, not just when list GET is forbidden',async()=>{
    const {adapter,methods}=makeAdapter({
      getRecoveryReconciliation:vi.fn().mockRejectedValue(
        new ProblemDetailsError({status:403,title:'Forbidden'})),
    });
    render(<RecoverySection adapter={adapter}/>);
    fireEvent.click(await screen.findByTestId('recovery-task-'+task.id));
    expect(await screen.findByText('Требуется доступ администратора.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'),{
      target:{value:'qa/incident-123'}});
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'),{
      target:{value:'a'.repeat(64)}});
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByTestId('recovery-attest')).toBeDisabled();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('rejects a wrong-task reconciliation receipt and untrusted ledger for a confirmed decision',async()=>{
    const {adapter,methods}=makeAdapter({
      getRecoveryReconciliation:vi.fn().mockResolvedValue({
        ...response,task_id:'different-task',decision:'CONFIRMED_SIDE_EFFECT',
      }),
      getRecoveryLedger:vi.fn().mockResolvedValue({
        task_id:'different-task',ledger_status:'AVAILABLE',attempts:[],
      }),
    });
    render(<RecoverySection adapter={adapter}/>);
    fireEvent.click(await screen.findByTestId('recovery-task-'+task.id));
    expect(await screen.findByText(/Сервер вернул неподтверждённое решение/))
      .toBeInTheDocument();
    expect(await screen.findByText(/Tool Ledger содержит неверифицированные/))
      .toBeInTheDocument();
    expect(screen.getByTestId('recovery-attest')).toBeDisabled();
    expect(screen.queryByTestId('recovery-decision')).not.toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('locks a committed-but-lost POST and does not retry even after a server refresh returns 404',async()=>{
    const {adapter,methods}=makeAdapter({
      attestRecovery:vi.fn().mockRejectedValue(new Error('connection reset after commit')),
    });
    render(<RecoverySection adapter={adapter}/>);
    fireEvent.click(await screen.findByTestId('recovery-task-'+task.id));
    await screen.findByTestId('recovery-attest');
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'),{
      target:{value:'qa/incident-123'}});
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'),{
      target:{value:'a'.repeat(64)}});
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('recovery-attest'));
    expect(await screen.findByTestId('recovery-uncertain')).toHaveTextContent('Исход POST неизвестен');
    expect(methods.attestRecovery).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('recovery-attest')).toBeDisabled();
    fireEvent.click(screen.getByTestId('recovery-refresh'));
    expect(await screen.findByTestId('recovery-post-locked')).toHaveTextContent(
      'Повтор запрещён');
    expect(methods.attestRecovery).toHaveBeenCalledTimes(1);
  });

  it('ignores a delayed successful POST after switching runs A → B → A',async()=>{
    let resolve!:(result:ReconciliationResponse)=>void;
    const waiting=new Promise<ReconciliationResponse>(accept=>{resolve=accept;});
    const {adapter,methods}=makeAdapter({
      attestRecovery:vi.fn(()=>waiting),
    });
    act(()=>useMvpStore.setState({runId:task.workflow_run_id,taskId:task.id}));
    render(<RecoverySection adapter={adapter}/>);
    await screen.findByTestId('recovery-attest');
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'),{
      target:{value:'qa/incident-123'}});
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'),{
      target:{value:'a'.repeat(64)}});
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('recovery-attest'));
    expect(methods.attestRecovery).toHaveBeenCalledTimes(1);
    act(()=>useMvpStore.getState().selectRun('foreign-run'));
    expect(screen.queryByTestId('recovery-decision')).not.toBeInTheDocument();
    act(()=>useMvpStore.getState().selectRun(task.workflow_run_id));
    expect(await screen.findByTestId('recovery-task-'+task.id)).toBeInTheDocument();
    act(()=>useMvpStore.getState().selectTask(task.id));
    expect(await screen.findByTestId('recovery-post-locked')).toBeInTheDocument();
    await act(async()=>resolve(response));
    expect(screen.queryByTestId('recovery-decision')).not.toBeInTheDocument();
    expect(methods.attestRecovery).toHaveBeenCalledTimes(1);
    // The next genuine server GET (not the old POST callback) resolves the lock.
    vi.mocked(methods.getRecoveryReconciliation).mockResolvedValue(response);
    fireEvent.click(screen.getByTestId('recovery-refresh'));
    expect(await screen.findByTestId('recovery-decision')).toHaveTextContent('UNKNOWN');
  });

  it('cannot show an old A-project catalog after a project A → B → A navigation',async()=>{
    let resolve!:(value:TaskResponse[])=>void;
    let count=0;
    const {adapter,methods}=makeAdapter({
      getRun:vi.fn(async(id:string)=>({
        id,project_id:'project-A',name:'Run',status:'running',version:1,
      })),
      listRecoveryQuarantine:vi.fn(()=>{
        count++;
        return count===1 ? new Promise<TaskResponse[]>(done=>{resolve=done;})
          : Promise.resolve([]);
      }),
    });
    act(()=>useMvpStore.setState({projectId:'project-A',
      runId:task.workflow_run_id,taskId:task.id}));
    render(<RecoverySection adapter={adapter}/>);
    await waitFor(()=>expect(methods.listRecoveryQuarantine).toHaveBeenCalledTimes(1));
    act(()=>useMvpStore.getState().selectProject('project-B'));
    act(()=>useMvpStore.getState().selectProject('project-A'));
    act(()=>useMvpStore.getState().selectRun(task.workflow_run_id));
    await screen.findByText('В выбранном запуске карантинных задач нет.');
    await act(async()=>resolve([task]));
    expect(screen.queryByTestId('recovery-task-'+task.id)).not.toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

});
