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

  it('opens the editor instead of exposing an ad-hoc task creation form', () => {
    mountWithMock();
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-runs'));
    expect(screen.getByTestId('runs-open-editor')).toBeInTheDocument();
    expect(screen.queryByTestId('run-create-button')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('runs-open-editor'));
    expect(useMvpStore.getState().activeSection).toBe('editor');
  });

  it('launches only the selected published snapshot and shows its server tasks', async () => {
    const api = mountWithMock();
    await api.createContract({project_id:'proj_seed',name:'summary',schema:{type:'object'}});
    const graph = {
      schema_version: '1.0' as const,
      metadata: {name:'Published SDLC', version:1, created_at:'2026-11-05T00:00:00Z'},
      nodes: [
        {id:'s',type:'start' as const,label:'Start',position:{x:0,y:0},config:{}},
        {id:'a',type:'agent' as const,label:'Research',position:{x:100,y:0},config:{
          agent_definition_id:MockAdapter.seed.agentDefinitionId,
          model_profile_id:MockAdapter.seed.modelProfileId,
          tool_policy_id:MockAdapter.seed.toolPolicyId,
        }},
        {id:'g',type:'gate' as const,label:'Gate',position:{x:200,y:0},config:{
          gate_type:'automatic',contract_id:'00000000-0000-4000-8000-000000000001',
        }},
        {id:'e',type:'end' as const,label:'End',position:{x:300,y:0},config:{}},
      ],
      edges: [
        {id:'e1',source_node_id:'s',target_node_id:'a',on_error:'fail' as const,max_retries:0,output_mapping:{}},
        {id:'e2',source_node_id:'a',target_node_id:'g',on_error:'fail' as const,max_retries:0,output_mapping:{}},
        {id:'e3',source_node_id:'g',target_node_id:'e',on_error:'fail' as const,max_retries:0,output_mapping:{}},
      ],
    };
    const workflow = await api.createWorkflow({project_id:'proj_seed',name:'Published SDLC',definition:graph});
    const version = await api.saveVersion(workflow.id,{definition_snapshot:graph,expected_version:workflow.version});
    const launch = vi.spyOn(api,'launchPublishedRun');
    vi.stubGlobal('confirm',vi.fn(()=>true));
    try {
      render(<App />);
      fireEvent.click(screen.getByTestId('nav-runs'));
      await screen.findByRole('option',{name:'Published SDLC'});
      fireEvent.change(screen.getByTestId('runs-definition-select'),{target:{value:workflow.id}});
      await waitFor(()=>expect(screen.getByTestId('runs-version-select').querySelectorAll('option').length).toBe(2));
      fireEvent.change(screen.getByTestId('runs-version-select'),{target:{value:version.id}});
      fireEvent.click(screen.getByTestId('runs-check-preflight'));
      await waitFor(()=>expect(screen.getByTestId('runs-preflight')).toHaveTextContent('Серверные проверки допускают'));
      expect(screen.getByTestId('runs-preflight')).toHaveTextContent('не подтверждено');
      await act(async()=>fireEvent.click(screen.getByTestId('runs-launch-published')));
      await waitFor(()=>expect(launch).toHaveBeenCalledOnce());
      expect(launch.mock.calls[0].slice(0,2)).toEqual([workflow.id,version.id]);
      // MockAdapter reuses launchRun internally to simulate the real server's\n      // published-graph compiler; the UI must call launchPublishedRun.\n      await waitFor(()=>expect(screen.getByText('Research')).toBeInTheDocument());
      const run = await api.getRun(useMvpStore.getState().runId!);
      expect(run.input_data?._workflow_version_id).toBe(version.id);
      const task = (await api.listRunTasks(run.id)).items[0];
      expect(task.node_id).toBe('a');
      fireEvent.click(screen.getByTestId('runs-open-log'));
      expect(useMvpStore.getState().activeSection).toBe('agent-log');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('refreshes selected run and task statuses, including on reselect', async () => {
    const api = mountWithMock();
    const result = await api.launchRun({
      project_id:'proj_seed', name:'Reload evidence',
      tasks:[{title:'Research'}],
    });
    const getRun = vi.spyOn(api,'getRun');
    const getTasks = vi.spyOn(api,'listRunTasks');
    act(()=>useMvpStore.setState({activeSection:'runs',runId:result.id}));
    render(<App />);
    await screen.findByTestId('runs-refresh');
    await waitFor(()=>expect(getRun).toHaveBeenCalled());
    await waitFor(()=>expect(getTasks).toHaveBeenCalled());
    getRun.mockClear();
    getTasks.mockClear();
    fireEvent.click(screen.getByTestId('runs-refresh'));
    await waitFor(()=>expect(getRun).toHaveBeenCalled());
    await waitFor(()=>expect(getTasks).toHaveBeenCalled());
    getRun.mockClear();
    getTasks.mockClear();
    await screen.findByTestId('select-run-' + result.id);
    fireEvent.click(screen.getByTestId('select-run-' + result.id));
    await waitFor(()=>expect(getRun).toHaveBeenCalled());
    await waitFor(()=>expect(getTasks).toHaveBeenCalled());
  });

  it('blocks published launch if server preflight finds a missing Contract Gate', async () => {
    const api = mountWithMock();
    const graph = {
      schema_version:'1.0' as const,
      metadata:{name:'No live contract',version:1,created_at:'2026-11-05T00:00:00Z'},
      nodes:[
        {id:'s',type:'start' as const,label:'Start',position:{x:0,y:0},config:{}},
        {id:'a',type:'agent' as const,label:'Agent',position:{x:100,y:0},config:{
          agent_definition_id:MockAdapter.seed.agentDefinitionId,
          model_profile_id:MockAdapter.seed.modelProfileId,
          tool_policy_id:MockAdapter.seed.toolPolicyId,
        }},
        {id:'g',type:'gate' as const,label:'Gate',position:{x:200,y:0},config:{
          gate_type:'automatic',contract_id:'00000000-0000-4000-8000-999999999999',
        }},
        {id:'e',type:'end' as const,label:'End',position:{x:300,y:0},config:{}},
      ],
      edges:[
        {id:'e1',source_node_id:'s',target_node_id:'a',on_error:'fail' as const,max_retries:0,output_mapping:{}},
        {id:'e2',source_node_id:'a',target_node_id:'g',on_error:'fail' as const,max_retries:0,output_mapping:{}},
        {id:'e3',source_node_id:'g',target_node_id:'e',on_error:'fail' as const,max_retries:0,output_mapping:{}},
      ],
    };
    const workflow = await api.createWorkflow({project_id:'proj_seed',name:'No live contract',definition:graph});
    const version = await api.saveVersion(workflow.id,{definition_snapshot:graph,expected_version:workflow.version});
    const launch = vi.spyOn(api,'launchPublishedRun');
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-runs'));
    await screen.findByRole('option',{name:'No live contract'});
    fireEvent.change(screen.getByTestId('runs-definition-select'),{target:{value:workflow.id}});
    await waitFor(()=>expect(screen.getByTestId('runs-version-select').querySelectorAll('option').length).toBe(2));
    fireEvent.change(screen.getByTestId('runs-version-select'),{target:{value:version.id}});
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(()=>expect(screen.getByTestId('runs-preflight')).toHaveTextContent('заблокировано'));
    expect(screen.getByTestId('runs-preflight')).toHaveTextContent('contracts');
    expect(screen.getByTestId('runs-launch-published')).toBeDisabled();
    expect(launch).not.toHaveBeenCalled();
  });

  it('refuses launch when the workflow has no published version', async () => {
    const api = mountWithMock();
    const graph = {
      schema_version:'1.0' as const,
      metadata:{name:'Draft only',version:1,created_at:'2026-11-05T00:00:00Z'},
      nodes:[],edges:[],
    };
    const draft = await api.createWorkflow({project_id:'proj_seed',name:'Draft only',definition:graph});
    const launch = vi.spyOn(api,'launchPublishedRun');
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-runs'));
    await screen.findByRole('option',{name:'Draft only'});
    fireEvent.change(screen.getByTestId('runs-definition-select'),{target:{value:draft.id}});
    await waitFor(()=>expect(screen.getByText(/Нет опубликованных версий/)).toBeInTheDocument());
    expect(screen.getByTestId('runs-launch-published')).toBeDisabled();
    expect(launch).not.toHaveBeenCalled();
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



describe('Native task read-only lifecycle', () => {
  it('shows worker-owned attempts and removes manual lifecycle mutations from product UI', async () => {
    const api = mountWithMock();
    const run = await api.launchRun({
      project_id:'proj_seed', name:'Worker-owned run',
      tasks:[{title:'Research',contract_id:'00000000-0000-4000-8000-000000000001'}],
    });
    const task = (await api.listRunTasks(run.id)).items[0];
    const claim = vi.spyOn(api,'claimTask');
    const submit = vi.spyOn(api,'submitTask');
    const fail = vi.spyOn(api,'failTask');
    const block = vi.spyOn(api,'blockTask');
    act(()=>useMvpStore.setState({
      api,activeSection:'task',projectId:'proj_seed',taskId:task.id,runId:null,
    }));
    render(<App />);
    expect(await screen.findByTestId('task-readonly-status')).toHaveTextContent('только для просмотра');
    expect(screen.queryByTestId('task-agent-input')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-claim-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-submit-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-fail-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-block-button')).not.toBeInTheDocument();
    expect(claim).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
    expect(fail).not.toHaveBeenCalled();
    expect(block).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('task-open-log'));
    expect(useMvpStore.getState().runId).toBe(run.id);
    expect(useMvpStore.getState().activeSection).toBe('agent-log');
  });

  it('opens the owning run without mutating execution state', async () => {
    const api = mountWithMock();
    const run = await api.launchRun({
      project_id:'proj_seed',name:'Detail navigation',tasks:[{title:'Task A'}],
    });
    const task = (await api.listRunTasks(run.id)).items[0];
    act(()=>useMvpStore.setState({api,activeSection:'task',taskId:task.id,runId:null}));
    render(<App />);
    await screen.findByTestId('task-open-run');
    fireEvent.click(screen.getByTestId('task-open-run'));
    expect(useMvpStore.getState().activeSection).toBe('runs');
    expect(useMvpStore.getState().runId).toBe(run.id);
  });
});

describe('Run and project scope regressions', () => {
  it('hides the previous project run immediately on project switch', async () => {
    const api = mountWithMock();
    const old = await api.launchRun({
      project_id: 'proj_seed', name: 'Old project run',
      tasks: [{ title: 'Old project task' }],
    });
    const oldTask = (await api.listRunTasks(old.id)).items[0];
    act(() => useMvpStore.setState({
      api, projectId: 'proj_seed', activeSection: 'runs',
      runId: old.id, taskId: oldTask.id,
    }));
    render(<App />);
    await screen.findByTestId('select-run-' + old.id);
    await screen.findByTestId('run-task-' + oldTask.id);

    act(() => useMvpStore.getState().selectProject('different-project'));
    expect(useMvpStore.getState().runId).toBeNull();
    expect(useMvpStore.getState().taskId).toBeNull();
    expect(screen.queryByTestId('select-run-' + old.id)).not.toBeInTheDocument();
    expect(screen.queryByTestId('run-task-' + oldTask.id)).not.toBeInTheDocument();
    expect(screen.queryByTestId('runs-open-log')).not.toBeInTheDocument();
  });

  it('hides previous run tasks before new async detail loading finishes', async () => {
    const api = mountWithMock();
    const first = await api.launchRun({
      project_id: 'proj_seed', name: 'First selected run',
      tasks: [{ title: 'First task' }],
    });
    const second = await api.launchRun({
      project_id: 'proj_seed', name: 'Second selected run',
      tasks: [{ title: 'Second task' }],
    });
    const firstTask = (await api.listRunTasks(first.id)).items[0];
    const secondTask = (await api.listRunTasks(second.id)).items[0];
    act(() => useMvpStore.setState({
      api, projectId: 'proj_seed', activeSection: 'runs',
      runId: first.id, taskId: firstTask.id,
    }));
    render(<App />);
    await screen.findByTestId('run-task-' + firstTask.id);

    act(() => useMvpStore.getState().selectRun(second.id));
    expect(useMvpStore.getState().taskId).toBeNull();
    expect(screen.queryByTestId('run-task-' + firstTask.id)).not.toBeInTheDocument();
    await screen.findByTestId('run-task-' + secondTask.id);
  });
});

describe('Task evidence secret-safe rendering', () => {
  it('never displays raw credential fields, worker errors or URL query tokens in the task card', async () => {
    const api = mountWithMock();
    const run = await api.launchRun({
      project_id: 'proj_seed',
      name: 'Sanitized evidence',
      tasks: [{ title: 'Evidence task' }],
    });
    const task = (await api.listRunTasks(run.id)).items[0];
    vi.spyOn(api, 'getTask').mockResolvedValue({
      ...task,
      description: 'fetch https://worker.test/api?stream_ticket=description-secret',
      input_data: {
        workflow_node_id: 'safe-node',
        api_key: 'input-secret',
        nested: { headers: { Authorization: 'Bearer header-secret' } },
      },
      output_data: {
        result: 'verified',
        request_url: 'https://worker.test/run?api_key=query-secret',
        refreshToken: 'output-secret',
      },
    });
    vi.spyOn(api, 'listTaskAttempts').mockResolvedValue([{
      id: 'attempt-redacted', task_id: task.id, attempt_number: 1,
      agent_id: 'operator-agent', status: 'failed', version: 1,
      error: 'Authorization: Bearer attempt-secret',
      output_data: { nested: { client_secret: 'attempt-output-secret' }, tokens_used: 10 },
    }]);
    vi.spyOn(api, 'listTaskGitEvidence').mockResolvedValue([{
      attempt_id: 'attempt-redacted', task_id: task.id, commit_sha: 'a'.repeat(40),
      changed_paths: ['https://host.test/path?token=git-path-secret'],
      provenance: 'worker_reported',
    }]);
    act(() => useMvpStore.setState({
      api, activeSection: 'task', projectId: 'proj_seed',
      runId: run.id, taskId: task.id,
    }));
    render(<App />);
    await screen.findByTestId('task-output');
    await waitFor(() => expect(screen.getByText(/попытка #1/i)).toBeInTheDocument());
    await screen.findByTestId('task-git-artifact');

    const visible = document.body.textContent ?? '';
    for (const secret of [
      'description-secret', 'input-secret', 'header-secret',
      'query-secret', 'output-secret', 'attempt-secret',
      'attempt-output-secret', 'git-path-secret',
    ]) expect(visible).not.toContain(secret);
    expect(visible).toContain('[REDACTED]');
    expect(visible).toContain('safe-node');
    expect(visible).toContain('verified');
    expect(visible).toContain('tokens_used');
    expect(visible).toContain('operator-agent');
    expect(screen.getByTestId('task-readonly-status')).toHaveTextContent('только для просмотра');
  });
});
