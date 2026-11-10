import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RunsSection from './RunsSection';
import { MockAdapter } from '../../api/mockAdapter';
import { useMvpStore } from '../mvpStore';
import type { PublishedRunPreflight, WorkflowDefinitionDTO, WorkflowVersionDTO } from '../../api/types';

const definition = {
  id: 'definition-1', name: 'Offline workflow', project_id: 'proj_seed', is_active: true,
} as WorkflowDefinitionDTO;
const version = (id: string, number: number) => ({
  id, version_number: number,
  definition_snapshot: { metadata: { name: 'Offline workflow' } },
} as WorkflowVersionDTO);
const report = (id: string): PublishedRunPreflight => ({
  workflow_definition_id: definition.id, workflow_version_id: id,
  can_create_run: true, execution_ready: false, task_count: 1,
  checks: [{ code: 'worker', status: 'unknown', detail: 'not verified' }],
});
const flush = async () => { await act(async () => { await Promise.resolve(); }); };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function prepare() {
  const api = new MockAdapter();
  vi.spyOn(api, 'listWorkflows').mockResolvedValue({ items: [definition], next_cursor: null });
  vi.spyOn(api, 'listVersions').mockResolvedValue({
    items: [version('v1', 1), version('v2', 2)], next_cursor: null,
  });
  act(() => useMvpStore.setState({ api, projectId: 'proj_seed', runId: null, taskId: null, pendingPublishedLaunches: {} }));
  return api;
}
async function selectVersion(id = 'v1') {
  await screen.findByRole('option', { name: 'Offline workflow' });
  fireEvent.change(screen.getByTestId('runs-definition-select'), { target: { value: definition.id } });
  await screen.findByRole('option', { name: /№1/ });
  fireEvent.change(screen.getByTestId('runs-version-select'), { target: { value: id } });
}
describe('published launch persistence boundary', () => {
  beforeEach(() => { vi.stubGlobal('confirm', vi.fn(() => true)); });

  it('reports confirmed POST success even when subsequent run/task GETs fail', async () => {
    const api = prepare();
    const post = vi.spyOn(api, 'launchPublishedRun').mockResolvedValue({
      id: 'persisted-run', project_id: 'proj_seed', name: 'Offline workflow',
      status: 'pending', version: 1,
    });
    vi.spyOn(api, 'preflightPublishedRun').mockImplementation(async (_d, id) => report(id));
    vi.spyOn(api, 'getRun').mockRejectedValue(new Error('GET run unavailable'));
    vi.spyOn(api, 'listRunTasks').mockRejectedValue(new Error('GET tasks unavailable'));
    render(<RunsSection />);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(() => expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Запуск №1 создан: persisted-run/)).toBeInTheDocument();
    await flush();
    expect(useMvpStore.getState().runId).toBe('persisted-run');
    expect(screen.queryByRole('alert', { name: /Запуск не удался/ })).not.toBeInTheDocument();
    expect(vi.mocked(window.confirm)).toHaveBeenCalledTimes(1);
  });

  it('discards preflight for a version that changed before the response', async () => {
    const api = prepare();
    let finish: ((r: PublishedRunPreflight) => void) | undefined;
    vi.spyOn(api, 'preflightPublishedRun').mockImplementation((_d, id) =>
      id === 'v1' ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(report(id)),
    );
    const post = vi.spyOn(api, 'launchPublishedRun');
    render(<RunsSection />);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    fireEvent.change(screen.getByTestId('runs-version-select'), { target: { value: 'v2' } });
    await act(async () => { finish?.(report('v1')); });
    expect(screen.queryByTestId('runs-preflight')).not.toBeInTheDocument();
    expect(screen.getByTestId('runs-launch-published')).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });
  it('retries an ambiguous POST with the identical key, then rotates after success', async () => {
    const api = prepare();
    const post = vi.spyOn(api, 'launchPublishedRun')
      .mockRejectedValueOnce(new Error('network response lost'))
      .mockResolvedValueOnce({
        id: 'confirmed-run', project_id: 'proj_seed', name: 'Offline workflow',
        status: 'running', version: 1,
      })
      .mockResolvedValueOnce({
        id: 'intentional-second-run', project_id: 'proj_seed',
        name: 'Offline workflow', status: 'running', version: 1,
      });
    vi.spyOn(api, 'preflightPublishedRun').mockImplementation(async (_d, id) => report(id));
    render(<RunsSection />);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(() => expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    await screen.findByText(/network response lost/);
    const first = post.mock.calls[0][2].idempotency_key;
    expect(first).toMatch(/^[a-f0-9]{32}$/);
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await screen.findByText(/Запуск №1 создан: confirmed-run/);
    expect(post.mock.calls[1][2].idempotency_key).toBe(first);
    await waitFor(() => expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await screen.findByText(/Запуск №1 создан: intentional-second-run/);
    expect(post.mock.calls[2][2].idempotency_key).not.toBe(first);
  });

  it('recovers ambiguous POST after section unmount with no fresh preflight', async () => {
    const api = prepare();
    const post = vi.spyOn(api, 'launchPublishedRun')
      .mockRejectedValueOnce(new Error('connection reset'))
      .mockResolvedValueOnce({
        id: 'already-created', project_id: 'proj_seed',
        name: 'Offline workflow', status: 'running', version: 1,
      });
    const preflight = vi.spyOn(api, 'preflightPublishedRun')
      .mockImplementationOnce(async (_d, id) => report(id))
      .mockImplementationOnce(async (_d, id) => report(id))
      .mockRejectedValue(new Error('preflight now fails'));
    const first = render(<RunsSection />);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(() => expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await screen.findByText(/connection reset/);
    const saved = post.mock.calls[0][2].idempotency_key;
    expect(Object.values(useMvpStore.getState().pendingPublishedLaunches)).toContain(saved);
    first.unmount();

    render(<RunsSection />);
    await selectVersion();
    // New component mounts without local preflight, but the store retained
    // the same key; this is a recovery, not a fresh authorized creation.
    await waitFor(() => expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await screen.findByText(/Запуск №1 создан: already-created/);
    expect(post.mock.calls[1][2].idempotency_key).toBe(saved);
    expect(preflight).toHaveBeenCalledTimes(2);
    expect(useMvpStore.getState().pendingPublishedLaunches).toEqual({});
  });

  it('never turns a delayed preflight from the previous project into launch permission', async () => {
    const api=prepare();
    let release!:(value:PublishedRunPreflight)=>void;
    const held=new Promise<PublishedRunPreflight>(resolve=>{release=resolve;});
    const preflight=vi.spyOn(api,'preflightPublishedRun').mockImplementation(()=>held);
    const post=vi.spyOn(api,'launchPublishedRun');
    render(<RunsSection/>);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(()=>expect(preflight).toHaveBeenCalledTimes(1));
    act(()=>useMvpStore.getState().selectProject('another-project'));
    await act(async()=>{release(report('v1'));});
    expect(screen.queryByTestId('runs-preflight')).not.toBeInTheDocument();
    expect(screen.getByTestId('runs-launch-published')).toBeDisabled();
    expect(screen.getByTestId('runs-check-preflight')).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it('does not select an old-project run after a successful delayed POST', async () => {
    const api=prepare();
    let release!:(result:Awaited<ReturnType<typeof api.launchPublishedRun>>)=>void;
    const held=new Promise<Awaited<ReturnType<typeof api.launchPublishedRun>>>(resolve=>{release=resolve;});
    const post=vi.spyOn(api,'launchPublishedRun').mockImplementation(()=>held);
    vi.spyOn(api,'preflightPublishedRun').mockImplementation(async(_d,id)=>report(id));
    render(<RunsSection/>);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(()=>expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await waitFor(()=>expect(post).toHaveBeenCalledTimes(1));
    const pending=post.mock.calls[0][2].idempotency_key;
    expect(Object.values(useMvpStore.getState().pendingPublishedLaunches)).toContain(pending);
    act(()=>useMvpStore.getState().selectProject('another-project'));
    await act(async()=>{release({
      id:'confirmed-other-context',project_id:'proj_seed',name:'Offline workflow',
      status:'running',version:1,
    });});
    await waitFor(()=>expect(Object.values(useMvpStore.getState().pendingPublishedLaunches))
      .not.toContain(pending));
    expect(useMvpStore.getState().projectId).toBe('another-project');
    expect(useMvpStore.getState().runId).toBeNull();
    expect(screen.queryByText(/Запуск №1 создан: confirmed-other-context/)).not.toBeInTheDocument();
  });

  it('does not activate a run after unmount while preserving confirmed POST settlement', async () => {
    const api=prepare();
    let release!:(result:Awaited<ReturnType<typeof api.launchPublishedRun>>)=>void;
    const held=new Promise<Awaited<ReturnType<typeof api.launchPublishedRun>>>(resolve=>{release=resolve;});
    const post=vi.spyOn(api,'launchPublishedRun').mockImplementation(()=>held);
    vi.spyOn(api,'preflightPublishedRun').mockImplementation(async(_d,id)=>report(id));
    const component=render(<RunsSection/>);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await waitFor(()=>expect(screen.getByTestId('runs-launch-published')).toBeEnabled());
    fireEvent.click(screen.getByTestId('runs-launch-published'));
    await waitFor(()=>expect(post).toHaveBeenCalledOnce());
    component.unmount();
    act(()=>useMvpStore.getState().selectProject('another-project'));
    await act(async()=>{release({
      id:'completed-while-away',project_id:'proj_seed',name:'Offline workflow',
      status:'running',version:1,
    });});
    await waitFor(()=>expect(useMvpStore.getState().pendingPublishedLaunches).toEqual({}));
    expect(useMvpStore.getState().runId).toBeNull();
    expect(useMvpStore.getState().projectId).toBe('another-project');
  });

  it('rejects a mismatched server preflight payload instead of enabling launch',async()=>{
    const api=prepare();
    vi.spyOn(api,'preflightPublishedRun').mockResolvedValue({
      ...report('v1'),workflow_version_id:'another-version',
    });
    const post=vi.spyOn(api,'launchPublishedRun');
    render(<RunsSection/>);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    await screen.findByText(/preflight другой версии workflow/);
    expect(screen.queryByTestId('runs-preflight')).not.toBeInTheDocument();
    expect(screen.getByTestId('runs-launch-published')).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it('does not reuse an earlier preflight after changing adapters at the same selection',async()=>{
    const first=prepare();
    let release!:(report:PublishedRunPreflight)=>void;
    const held=new Promise<PublishedRunPreflight>(resolve=>{release=resolve;});
    vi.spyOn(first,'preflightPublishedRun').mockImplementation(()=>held);
    const second=new MockAdapter();
    vi.spyOn(second,'listWorkflows').mockResolvedValue({items:[definition],next_cursor:null});
    vi.spyOn(second,'listVersions').mockResolvedValue({items:[version('v1',1)],next_cursor:null});
    const launch=vi.spyOn(second,'launchPublishedRun');
    render(<RunsSection/>);
    await selectVersion();
    fireEvent.click(screen.getByTestId('runs-check-preflight'));
    act(()=>useMvpStore.setState({api:second}));
    await act(async()=>{release(report('v1'));});
    expect(screen.queryByTestId('runs-preflight')).not.toBeInTheDocument();
    expect(screen.getByTestId('runs-launch-published')).toBeDisabled();
    expect(launch).not.toHaveBeenCalled();
  });

});
