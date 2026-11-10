import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import EditorWorkspace from './EditorWorkspace';
import { compilePreview } from './publishedPreview';
import { useMvpStore } from '../mvp/mvpStore';
import { useEditorStore } from './store';
import { MockAdapter } from '../api/mockAdapter';
import type { WorkflowDefinition } from '../workflow/types';

vi.mock('./WorkflowCanvas', () => ({default: () => <div>Graph canvas</div>}));
vi.mock('./NodePalette', () => ({default: () => <div>Node palette</div>}));
vi.mock('./PropertyPanel', () => ({default: () => <div>Property inspector</div>}));
const refs = {
  agent_definition_id:'11111111-1111-4111-8111-111111111111',
  model_profile_id:'22222222-2222-4222-8222-222222222222',
  tool_policy_id:'33333333-3333-4333-8333-333333333333',
};
const contract='00000000-0000-4000-8000-000000000001';
function sample(): WorkflowDefinition {
  const nodes = [
    {id:'s',type:'start',label:'Start',config:{}},
    {id:'a',type:'agent',label:'Developer',config:{...refs}},
    {id:'g',type:'gate',label:'Contract',config:{gate_type:'automatic',contract_id:contract}},
    {id:'e',type:'end',label:'End',config:{}},
  ] as const;
  return {
    schema_version:'1.0',metadata:{name:'Runtime flow',created_at:'2026-11-05T00:00:00Z',version:1},
    nodes:nodes.map((n,i)=>({...n,position:{x:i*220,y:0}})),
    edges:nodes.slice(0,-1).map((n,i)=>({
      id:'link-'+i,source_node_id:n.id,target_node_id:nodes[i+1].id,
      output_mapping:{},on_error:'fail' as const,max_retries:0,
    })),
  };
}
let api: MockAdapter;
beforeEach(()=>{
  api=new MockAdapter();
  act(()=>{
    useMvpStore.setState({api,projectId:'proj_seed',runId:null,taskId:null,activeSection:'editor'});
    useEditorStore.getState().reset();
  });
  vi.stubGlobal('confirm',vi.fn(()=>true));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});


async function readyPublishedEditor(){
  await api.createContract({project_id:'proj_seed',name:'summary',schema:{type:'object'}});
  const view=render(<EditorWorkspace/>);
  act(()=>useEditorStore.getState().load(sample()));
  fireEvent.click(screen.getByTestId('editor-save'));
  await screen.findByText(/Черновик сохранён на сервере/);
  fireEvent.click(screen.getByTestId('editor-publish'));
  await screen.findByText(/Опубликована неизменяемая версия/);
  const record=(await api.listWorkflows()).items[0];
  const versions=(await api.listVersions(record.id)).items;
  expect(versions).toHaveLength(1);
  return {view,record,version:versions[0]};
}
describe('published workflow editor journey',()=>{

  it('blocks schema-incompatible published preview instead of creating phantom tasks', () => {
    const malformed = [
      { label: 'unknown root field', modify: (doc: WorkflowDefinition) => { Object.assign(doc, { hidden_run: true }); } },
      { label: 'missing metadata', modify: (doc: WorkflowDefinition) => { delete (doc as Partial<WorkflowDefinition>).metadata; } },
      { label: 'invalid canvas position', modify: (doc: WorkflowDefinition) => { doc.nodes[1].position.x = Number.NaN; } },
      { label: 'unknown node field', modify: (doc: WorkflowDefinition) => { Object.assign(doc.nodes[1], { runtime_override: 'tool' }); } },
      { label: 'unknown edge field', modify: (doc: WorkflowDefinition) => { Object.assign(doc.edges[0], { ignored_retry: 3 }); } },
      { label: 'invalid retry type', modify: (doc: WorkflowDefinition) => { Object.assign(doc.edges[0], { max_retries: false }); } },
      { label: 'empty condition ignored by legacy preview', modify: (doc: WorkflowDefinition) => { doc.edges[0].condition = ''; } },
      { label: 'invalid metadata version', modify: (doc: WorkflowDefinition) => { Object.assign(doc.metadata, { version: true }); } },
    ];
    for (const entry of malformed) {
      const candidate = sample();
      entry.modify(candidate);
      const result = compilePreview(candidate);
      expect(result.errors.length, entry.label).toBeGreaterThan(0);
      expect(result.tasks, entry.label).toEqual([]);
    }
  });

  it('saves a real draft, publishes immutable graph and creates a compiled run from saved version',async ()=>{
    await api.createContract({project_id:'proj_seed',name:'summary',schema:{type:'object'}});
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    fireEvent.click(screen.getByTestId('editor-save'));
    await waitFor(()=>expect(screen.getByText(/Черновик сохранён на сервере/)).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('editor-publish'));
    await waitFor(()=>expect(screen.getByText(/Опубликована неизменяемая версия/)).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(useMvpStore.getState().activeSection).toBe('runs'));
    const id=useMvpStore.getState().runId!;
    const run=await api.getRun(id);
    expect(run.input_data?._workflow_version_id).toBeTruthy();
    const tasks=await api.listRunTasks(id);
    expect(tasks.items.map(x=>x.node_id)).toEqual(['a']);
    expect(tasks.items[0].contract_id).toBe(contract);
    expect(vi.mocked(window.confirm)).toHaveBeenCalled();
    const catalog=await api.listWorkflows();
    const versions=await api.listVersions(catalog.items[0].id);
    expect(versions.items).toHaveLength(1);
    expect(versions.items[0].definition_snapshot.nodes[1].label).toBe('Developer');
  });

  it('stale draft conflict is visible, and later changes cannot silently mutate published snapshot',async ()=>{
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const saved=(await api.listWorkflows()).items[0];
    await api.updateWorkflow(saved.id,{expected_version:saved.version,name:'changed remotely'});
    act(()=>useEditorStore.getState().updateMetadata({name:'Changed locally'}));
    fireEvent.click(screen.getByTestId('editor-save'));
    await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent(/Workflow has changed/));
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
  });

  it('refuses unsupported nodes and missing Gate contract before backend run',async ()=>{
    const invalid=sample();
    invalid.nodes[2].type='condition';
    expect(compilePreview(invalid).errors.join(' ')).toMatch(/не поддерживается runtime|automatic Gate/);
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(invalid));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    fireEvent.click(screen.getByTestId('editor-validate'));
    expect(screen.getByTestId('editor-errors')).toBeInTheDocument();
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    const missing=sample();
    missing.nodes[2].config.contract_id='bad';
    expect(compilePreview(missing).errors.join(' ')).toContain('UUID контракта');
  });

  it('runs a selected immutable version even when a newer draft is being edited',async ()=>{
    await api.createContract({project_id:'proj_seed',name:'summary',schema:{type:'object'}});
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    fireEvent.click(screen.getByTestId('editor-publish'));
    await screen.findByText(/Опубликована неизменяемая версия/);
    act(()=>useEditorStore.getState().updateMetadata({name:'Unpublished risky changes'}));
    expect(screen.getByTestId('editor-run')).toBeEnabled();
    expect(screen.getByText(/запуск использует выбранную опубликованную версию/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(useMvpStore.getState().activeSection).toBe('runs'));
    const run=await api.getRun(useMvpStore.getState().runId!);
    expect(run.name).toBe('Runtime flow');
  });

  it('resumes saved draft from backend without creating another workflow',async ()=>{
    const existing=await api.createWorkflow({name:'Runtime flow',definition:sample()});
    render(<EditorWorkspace/>);
    await screen.findByRole('option',{name:'Runtime flow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:existing.id}});
    await waitFor(()=>expect(screen.getByText(/Открыта серверная версия черновика/)).toBeInTheDocument());
    expect(screen.getByTestId('editor-workflow-name')).toHaveValue('Runtime flow');
    expect(screen.getByTestId('editor-save')).toBeEnabled();
  });
  it('reopens the authoritative published pointer even when versions are listed oldest-first', async () => {
    const saved = await api.createWorkflow({name:'Publication pointer',definition:sample()});
    const first = await api.saveVersion(saved.id,{
      expected_version:saved.version,definition_snapshot:sample(),
    });
    const current = await api.getWorkflow(saved.id);
    const secondGraph = sample();
    secondGraph.nodes[1].label = 'Second version';
    const edited = await api.updateWorkflow(saved.id,{
      expected_version:current.version,definition:secondGraph,
    });
    const second = await api.saveVersion(saved.id,{
      expected_version:edited.version,definition_snapshot:secondGraph,
    });
    expect((await api.getWorkflow(saved.id)).current_version_id).toBe(second.id);
    expect(first.id).not.toBe(second.id);
    render(<EditorWorkspace/>);
    await screen.findByRole('option',{name:'Publication pointer'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:saved.id}});
    await waitFor(()=>expect(screen.getByTestId('editor-version-select')).toHaveValue(second.id));
    expect(screen.getByTestId('editor-version-select')).not.toHaveValue(first.id);
    expect(screen.getByText(/Выбрана неизменяемая версия №2/)).toBeInTheDocument();
  });

  it('supports accessible edge creation and whole-document undo/redo without publishing the change', async () => {
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    const first=useEditorStore.getState().definition.nodes[0].id;
    const last=useEditorStore.getState().definition.nodes.at(-1)!.id;
    fireEvent.change(screen.getByTestId('editor-link-from'),{target:{value:first}});
    fireEvent.change(screen.getByTestId('editor-link-to'),{target:{value:last}});
    fireEvent.click(screen.getByTestId('editor-add-connection'));
    expect(useEditorStore.getState().definition.edges).toHaveLength(4);
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    fireEvent.click(screen.getByTestId('editor-undo'));
    expect(useEditorStore.getState().definition.edges).toHaveLength(3);
    fireEvent.click(screen.getByTestId('editor-redo'));
    expect(useEditorStore.getState().definition.edges).toHaveLength(4);
    fireEvent.click(screen.getByTestId('editor-undo'));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    fireEvent.click(screen.getByTestId('editor-publish'));
    await screen.findByText(/Опубликована неизменяемая версия/);
  });

  it('does not hijack native typing undo in a text field', () => {
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().addNode('start',{x:0,y:0}));
    const count=useEditorStore.getState().definition.nodes.length;
    const name=screen.getByTestId('editor-workflow-name');
    fireEvent.keyDown(name,{key:'z',ctrlKey:true});
    expect(useEditorStore.getState().definition.nodes).toHaveLength(count);
    fireEvent.keyDown(screen.getByRole('region',{name:'Редактор workflow'}),{key:'z',ctrlKey:true});
    expect(useEditorStore.getState().definition.nodes).toHaveLength(0);
  });

  it('creates an executable template from server data, then saves, publishes and launches it',async()=>{
    render(<EditorWorkspace/>);
    fireEvent.click(screen.getByText('Собрать готовый процесс из реальных агентов и контрактов'));
    await screen.findByRole('option',{name:'Research Agent'});
    fireEvent.click(screen.getByRole('button',{name:'Создать типовой контракт «summary»'}));
    await waitFor(()=>expect(screen.getByTestId('preset-contract')).toHaveValue('00000000-0000-4000-8000-000000000001'));
    fireEvent.change(screen.getByTestId('preset-agent-0'),{
      target:{value:MockAdapter.seed.agentDefinitionId},
    });
    fireEvent.change(screen.getByTestId('preset-model-0'),{
      target:{value:MockAdapter.seed.modelProfileId},
    });
    fireEvent.change(screen.getByTestId('preset-policy-0'),{
      target:{value:MockAdapter.seed.toolPolicyId},
    });
    expect(screen.getByTestId('preset-build')).toBeEnabled();
    fireEvent.click(screen.getByTestId('preset-build'));
    expect(compilePreview(useEditorStore.getState().definition).errors).toEqual([]);
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    fireEvent.click(screen.getByTestId('editor-publish'));
    await screen.findByText(/Опубликована неизменяемая версия/);
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(useMvpStore.getState().activeSection).toBe('runs'));
    const run=await api.getRun(useMvpStore.getState().runId!);
    const tasks=await api.listRunTasks(run.id);
    expect(tasks.items).toHaveLength(1);
    expect(tasks.items[0].title).toBe('Разработчик');
    expect(tasks.items[0].contract_id).toBe('00000000-0000-4000-8000-000000000001');
  });

  it('preserves an unsaved workflow when a new configured template is declined',async()=>{
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    const before=useEditorStore.getState().definition;
    vi.mocked(window.confirm).mockReturnValue(false);
    fireEvent.click(screen.getByText('Собрать готовый процесс из реальных агентов и контрактов'));
    await screen.findByRole('option',{name:'Research Agent'});
    fireEvent.click(screen.getByRole('button',{name:'Создать типовой контракт «summary»'}));
    await waitFor(()=>expect(screen.getByTestId('preset-contract')).toHaveValue('00000000-0000-4000-8000-000000000001'));
    fireEvent.change(screen.getByTestId('preset-agent-0'),{target:{value:MockAdapter.seed.agentDefinitionId}});
    fireEvent.change(screen.getByTestId('preset-model-0'),{target:{value:MockAdapter.seed.modelProfileId}});
    fireEvent.change(screen.getByTestId('preset-policy-0'),{target:{value:MockAdapter.seed.toolPolicyId}});
    fireEvent.click(screen.getByTestId('preset-build'));
    expect(useEditorStore.getState().definition).toBe(before);
    expect(window.confirm).toHaveBeenCalled();
  });

  it('keeps the old unsaved document but blocks cross-project save/publish/run until deliberate rebind',async()=>{
    const second=await api.createProject({name:'Another project'});
    await api.createContract({project_id:'proj_seed',name:'summary',schema:{type:'object'}});
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    fireEvent.click(screen.getByTestId('editor-publish'));
    await screen.findByText(/Опубликована неизменяемая версия/);
    const previous=(await api.listWorkflows()).items[0];
    act(()=>useEditorStore.getState().updateMetadata({name:'Unsaved notes'}));
    act(()=>useMvpStore.getState().selectProject(second.id));
    expect(screen.getByTestId('editor-project-mismatch')).toHaveTextContent(/черновик/i);
    expect(screen.getByTestId('editor-workflow-name')).toHaveValue('Unsaved notes');
    expect(screen.getByTestId('editor-save')).toBeDisabled();
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect((await api.getWorkflow(previous.id)).name).toBe('Runtime flow');
    fireEvent.click(screen.getByRole('button',{name:'Новый'}));
    expect(screen.queryByTestId('editor-project-mismatch')).not.toBeInTheDocument();
    act(()=>useEditorStore.getState().updateMetadata({name:'New project workflow'}));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const all=(await api.listWorkflows()).items;
    expect(all.find(item=>item.name==='New project workflow')?.project_id).toBe(second.id);
    expect((await api.getWorkflow(previous.id)).name).toBe('Runtime flow');
  });

  it('drops stale workflow catalog replies when the active project changes',async()=>{
    const second=await api.createProject({name:'Second'});
    await api.createWorkflow({project_id:'proj_seed',name:'Old workflow',definition:sample()});
    await api.createWorkflow({project_id:second.id,name:'Current workflow',definition:sample()});
    const original=api.listWorkflows.bind(api);
    type Page=Awaited<ReturnType<typeof api.listWorkflows>>;
    let release!:(page:Page)=>void;
    const pending=new Promise<Page>(resolve=>{release=resolve;});
    let requests=0;
    vi.spyOn(api,'listWorkflows').mockImplementation(params=>
      ++requests===1?pending:original(params));
    render(<EditorWorkspace/>);
    await waitFor(()=>expect(requests).toBe(1));
    act(()=>useMvpStore.getState().selectProject(second.id));
    await screen.findByRole('option',{name:'Current workflow'});
    await act(async()=>{release(await original({limit:100}));});
    expect(screen.queryByRole('option',{name:'Old workflow'})).not.toBeInTheDocument();
    expect(screen.getByRole('option',{name:'Current workflow'})).toBeInTheDocument();
    expect(screen.getByTestId('editor-project-mismatch')).toBeInTheDocument();
  });

  it('ignores late workflow opens and keeps the new project state unchanged',async()=>{
    const second=await api.createProject({name:'Second'});
    const old=await api.createWorkflow({project_id:'proj_seed',name:'Old workflow',definition:sample()});
    const actualGet=api.getWorkflow.bind(api);
    let release!:()=>void;
    const pending=new Promise<void>(resolve=>{release=resolve;});
    const get=vi.spyOn(api,'getWorkflow').mockImplementation(async id=>{
      await pending;return actualGet(id);
    });
    render(<EditorWorkspace/>);
    await screen.findByRole('option',{name:'Old workflow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:old.id}});
    await waitFor(()=>expect(get).toHaveBeenCalledWith(old.id));
    act(()=>useMvpStore.getState().selectProject(second.id));
    await act(async()=>{release();await pending;});
    expect(screen.queryByText(/Открыта серверная версия черновика/)).not.toBeInTheDocument();
    expect(screen.getByTestId('editor-workflow-name')).toHaveValue('Untitled workflow');
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect(screen.getByTestId('editor-project-mismatch')).toBeInTheDocument();
  });

  it('does not mark edits made during an in-flight save as persisted',async()=>{
    const original=api.createWorkflow.bind(api);
    let release!:()=>void;
    const pending=new Promise<void>(resolve=>{release=resolve;});
    vi.spyOn(api,'createWorkflow').mockImplementation(async input=>{
      await pending;return original(input);
    });
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    act(()=>useEditorStore.getState().updateMetadata({name:'Changed during save'}));
    await act(async()=>{release();await pending;});
    await screen.findByText(/Черновик сохранён на сервере/);
    expect(screen.getByTestId('editor-workflow-name')).toHaveValue('Changed during save');
    expect(screen.getByText(/Есть несохранённые изменения/)).toBeInTheDocument();
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    expect((await api.listWorkflows()).items[0].name).toBe('Runtime flow');
  });

  it('never launches an old project run after a delayed server preflight',async()=>{
    const second=await api.createProject({name:'Second'});
    await api.createContract({project_id:'proj_seed',name:'summary',schema:{type:'object'}});
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    fireEvent.click(screen.getByTestId('editor-publish'));
    await screen.findByText(/Опубликована неизменяемая версия/);
    const original=api.preflightPublishedRun.bind(api);
    let release!:()=>void;
    const pending=new Promise<void>(resolve=>{release=resolve;});
    const preflight=vi.spyOn(api,'preflightPublishedRun').mockImplementation(async (...args)=>{
      await pending;return original(...args);
    });
    const launch=vi.spyOn(api,'launchPublishedRun');
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(preflight).toHaveBeenCalledOnce());
    act(()=>useMvpStore.getState().selectProject(second.id));
    await act(async()=>{release();await pending;});
    expect(launch).not.toHaveBeenCalled();
    expect(useMvpStore.getState().runId).toBeNull();
    expect(useMvpStore.getState().activeSection).toBe('editor');
    expect(screen.getByTestId('editor-run')).toBeDisabled();
  });

  it('preserves project ownership across unmount/remount instead of saving an old graph in another project',async()=>{
    const second=await api.createProject({name:'Different project'});
    const {unmount}=render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const first=(await api.listWorkflows()).items[0];
    unmount();
    act(()=>useMvpStore.getState().selectProject(second.id));
    render(<EditorWorkspace/>);
    expect(screen.getByTestId('editor-workflow-name')).toHaveValue('Runtime flow');
    expect(screen.getByTestId('editor-project-mismatch')).toBeInTheDocument();
    expect(screen.getByTestId('editor-save')).toBeDisabled();
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect((await api.listWorkflows()).items).toHaveLength(1);
    fireEvent.click(screen.getByRole('button',{name:'Новый'}));
    act(()=>useEditorStore.getState().updateMetadata({name:'Scoped second'}));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const all=(await api.listWorkflows()).items;
    expect(all.find(item=>item.id===first.id)?.project_id).toBe('proj_seed');
    expect(all.find(item=>item.name==='Scoped second')?.project_id).toBe(second.id);
  });

  it('requires reopening a saved workflow after navigation in the same project to avoid duplicate POST',async()=>{
    const {unmount}=render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const saved=(await api.listWorkflows()).items[0];
    unmount();
    const create=vi.spyOn(api,'createWorkflow');
    render(<EditorWorkspace/>);
    expect(screen.getByTestId('editor-reopen-required')).toHaveTextContent('дубликат');
    expect(screen.getByTestId('editor-save')).toBeDisabled();
    await screen.findByRole('option',{name:'Runtime flow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:saved.id}});
    await screen.findByText(/Открыта серверная версия черновика/);
    expect(screen.queryByTestId('editor-reopen-required')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    expect(create).not.toHaveBeenCalled();
    expect((await api.listWorkflows()).items).toHaveLength(1);
  });

  it('rejects a forged successful preflight for another immutable version before POST',async()=>{
    const {record,version}=await readyPublishedEditor();
    const preflight=vi.spyOn(api,'preflightPublishedRun').mockResolvedValue({
      workflow_definition_id:record.id,workflow_version_id:version.id+'-other',
      can_create_run:true,execution_ready:true,task_count:1,checks:[],
    });
    const launch=vi.spyOn(api,'launchPublishedRun');
    fireEvent.click(screen.getByTestId('editor-run'));
    expect(await screen.findByRole('alert')).toHaveTextContent('preflight другой версии');
    expect(preflight).toHaveBeenCalledOnce();
    expect(launch).not.toHaveBeenCalled();
    expect(useMvpStore.getState().runId).toBeNull();
  });

  it('does not select mismatched project/version on 2xx and preserves its pending receipt',async()=>{
    const {record,version}=await readyPublishedEditor();
    const original=api.launchPublishedRun.bind(api);
    vi.spyOn(api,'launchPublishedRun').mockImplementation(async(...args)=>({
      ...(await original(...args)),project_id:'foreign-project',
    }));
    fireEvent.click(screen.getByTestId('editor-run'));
    expect(await screen.findByRole('alert')).toHaveTextContent('неподтверждённым проектом');
    expect(useMvpStore.getState().runId).toBeNull();
    expect(useMvpStore.getState().activeSection).toBe('editor');
    const selection=['proj_seed',record.id,version.id].join('/');
    const key=useMvpStore.getState().pendingPublishedLaunches[selection];
    expect(key).toMatch(/^[a-f0-9]{32}$/);
    const post=vi.mocked(api.launchPublishedRun);
    expect(post.mock.calls[0][2].idempotency_key).toBe(key);
    // A second malformed identity must also be treated as ambiguous.
    post.mockResolvedValueOnce({
      id:'forged-version',project_id:'proj_seed',name:'forged',
      status:'pending',version:1,
      input_data:{_workflow_definition_id:record.id,_workflow_version_id:'wrong'},
    });
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(post).toHaveBeenCalledTimes(2));
    expect(useMvpStore.getState().pendingPublishedLaunches[selection]).toBe(key);
    expect(useMvpStore.getState().runId).toBeNull();
  });

  it('settles a delayed valid POST after project switch without selecting the old run',async()=>{
    const {record,version}=await readyPublishedEditor();
    const second=await api.createProject({name:'Other project'});
    let release!:()=>void;
    const held=new Promise<void>(resolve=>{release=resolve;});
    const original=api.launchPublishedRun.bind(api);
    let committed='';
    const post=vi.spyOn(api,'launchPublishedRun').mockImplementation(async(...args)=>{
      const result=await original(...args);
      committed=result.id;
      await held;
      return result;
    });
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(committed).not.toBe(''));
    const selection=['proj_seed',record.id,version.id].join('/');
    const key=useMvpStore.getState().pendingPublishedLaunches[selection];
    expect(key).toMatch(/^[a-f0-9]{32}$/);
    act(()=>useMvpStore.getState().selectProject(second.id));
    await act(async()=>{release();await held;});
    await waitFor(()=>expect(useMvpStore.getState().pendingPublishedLaunches[selection]).toBeUndefined());
    expect(post).toHaveBeenCalledOnce();
    expect((await api.getRun(committed)).project_id).toBe('proj_seed');
    expect(useMvpStore.getState().projectId).toBe(second.id);
    expect(useMvpStore.getState().runId).toBeNull();
    expect(useMvpStore.getState().activeSection).toBe('editor');
  });

  it('replays the same key after committed-but-lost POST, remount and reopen',async()=>{
    const {view,record,version}=await readyPublishedEditor();
    const original=api.launchPublishedRun.bind(api);
    let committed:Awaited<ReturnType<typeof original>>|null=null;
    const post=vi.spyOn(api,'launchPublishedRun').mockImplementation(async(...args)=>{
      if(committed)return committed;
      committed=await original(...args);
      throw new Error('connection reset after commit');
    });
    const preflight=vi.spyOn(api,'preflightPublishedRun');
    fireEvent.click(screen.getByTestId('editor-run'));
    expect(await screen.findByRole('alert')).toHaveTextContent('connection reset');
    const selection=['proj_seed',record.id,version.id].join('/');
    const key=useMvpStore.getState().pendingPublishedLaunches[selection];
    expect(key).toMatch(/^[a-f0-9]{32}$/);
    expect(useMvpStore.getState().runId).toBeNull();
    const before=preflight.mock.calls.length;
    view.unmount();
    render(<EditorWorkspace/>);
    await screen.findByRole('option',{name:'Runtime flow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:record.id}});
    await screen.findByText(/Открыта серверная версия черновика/);
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1][2].idempotency_key).toBe(key);
    expect(preflight.mock.calls.length).toBe(before);
    expect(useMvpStore.getState().pendingPublishedLaunches[selection]).toBeUndefined();
    expect(useMvpStore.getState().runId).toBe(committed!.id);
    expect(useMvpStore.getState().activeSection).toBe('runs');
    expect((await api.listRunTasks(committed!.id)).items).toHaveLength(1);
  });

  it('ignores a stale old preflight after project A → B → A',async()=>{
    const {view}=await readyPublishedEditor();
    let release!:(value:Awaited<ReturnType<typeof api.preflightPublishedRun>>)=>void;
    const pending=new Promise<Awaited<ReturnType<typeof api.preflightPublishedRun>>>(r=>{release=r;});
    const actual=api.preflightPublishedRun.bind(api);
    const second=await api.createProject({name:'Other'});
    const preflight=vi.spyOn(api,'preflightPublishedRun').mockImplementation(()=>pending);
    const post=vi.spyOn(api,'launchPublishedRun');
    fireEvent.click(screen.getByTestId('editor-run'));
    await waitFor(()=>expect(preflight).toHaveBeenCalledOnce());
    act(()=>useMvpStore.getState().selectProject(second.id));
    act(()=>useMvpStore.getState().selectProject('proj_seed'));
    // The editor preserved its document, but its in-flight request was from
    // an abandoned scope and must not launch even after returning to A.
    const data=await actual((await api.listWorkflows()).items[0].id,
      (await api.listVersions((await api.listWorkflows()).items[0].id)).items[0].id,'proj_seed');
    await act(async()=>{release(data);await pending;});
    expect(post).not.toHaveBeenCalled();
    expect(useMvpStore.getState().runId).toBeNull();
    view.unmount();
  });

  it('fails closed on a successful-looking foreign CREATE receipt and cannot silently duplicate',async()=>{
    const original=api.createWorkflow.bind(api);
    const create=vi.spyOn(api,'createWorkflow').mockImplementation(async request=>({
      ...(await original(request)),project_id:'foreign-project',
    }));
    const view=render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервер не подтвердил ID проекта');
    expect(screen.getByTestId('editor-save')).toBeDisabled();
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    expect(screen.getByTestId('editor-reopen-required')).toBeInTheDocument();
    expect(create).toHaveBeenCalledOnce();
    view.unmount();
    render(<EditorWorkspace/>);
    expect(screen.getByTestId('editor-save')).toBeDisabled();
    expect(create).toHaveBeenCalledOnce();
    expect((await api.listWorkflows()).items).toHaveLength(1);
  });

  it('fences a lost CREATE response until the operator reopens the committed workflow',async()=>{
    const original=api.createWorkflow.bind(api);
    const create=vi.spyOn(api,'createWorkflow').mockImplementation(async request=>{
      await original(request);
      throw new Error('connection reset after CREATE');
    });
    render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    expect(await screen.findByRole('alert')).toHaveTextContent('connection reset');
    expect(screen.getByTestId('editor-save')).toBeDisabled();
    expect(create).toHaveBeenCalledOnce();
    await screen.findByRole('option',{name:'Runtime flow'});
    const record=(await api.listWorkflows()).items[0];
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:record.id}});
    await screen.findByText(/Открыта серверная версия черновика/);
    expect(screen.getByTestId('editor-save')).toBeEnabled();
    expect(create).toHaveBeenCalledOnce();
  });

  it('rejects a foreign or duplicate publication version before treating it as published',async()=>{
    const {record}=await readyPublishedEditor();
    const original=api.listVersions.bind(api);
    const list=vi.spyOn(api,'listVersions').mockImplementation(async(...args)=>{
      const reply=await original(...args);
      return {...reply,items:[{...reply.items[0],workflow_definition_id:'foreign-definition'}]};
    });
    const view=render(<EditorWorkspace/>);
    await screen.findByRole('option',{name:'Runtime flow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:record.id}});
    expect(await screen.findByRole('alert')).toHaveTextContent('immutable snapshot');
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect(screen.queryByText(/Открыта серверная версия черновика/)).not.toBeInTheDocument();
    list.mockRestore();view.unmount();
  });

  it('does not infer a published version from history when the server pointer is null',async()=>{
    const {view,record}=await readyPublishedEditor();
    const original=api.getWorkflow.bind(api);
    const mocked=vi.spyOn(api,'getWorkflow').mockImplementation(async id=>({
      ...(await original(id)),current_version_id:null,
    }));
    view.unmount();
    render(<EditorWorkspace/>);
    await screen.findByRole('option',{name:'Runtime flow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:record.id}});
    await screen.findByText(/Открыта серверная версия черновика/);
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect(screen.getByTestId('editor-version-select')).toHaveValue('');
    mocked.mockRestore();
  });

  it('requires a confirmed published pointer even after a successful-looking version POST',async()=>{
    const view=render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const record=(await api.listWorkflows()).items[0];
    const original=api.getWorkflow.bind(api);
    const get=vi.spyOn(api,'getWorkflow').mockImplementation(async id=>({
      ...(await original(id)),current_version_id:'another-version',
    }));
    fireEvent.click(screen.getByTestId('editor-publish'));
    expect(await screen.findByRole('alert')).toHaveTextContent('текущий опубликованный указатель');
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    get.mockRestore();
    await screen.findByRole('option',{name:'Runtime flow'});
    fireEvent.change(screen.getByTestId('editor-workflow-list'),{target:{value:record.id}});
    await screen.findByText(/Открыта серверная версия черновика/);
    expect(screen.getByTestId('editor-run')).toBeEnabled();
    view.unmount();
  });

  it('rejects a mismatched immutable snapshot 2xx and prevents a second publish',async()=>{
    const view=render(<EditorWorkspace/>);
    act(()=>useEditorStore.getState().load(sample()));
    fireEvent.click(screen.getByTestId('editor-save'));
    await screen.findByText(/Черновик сохранён на сервере/);
    const real=api.saveVersion.bind(api);
    const save=vi.spyOn(api,'saveVersion').mockImplementation(async(...args)=>{
      const version=await real(...args);
      return {...version,definition_snapshot:{...version.definition_snapshot,
        metadata:{...version.definition_snapshot.metadata,name:'forged'} }};
    });
    fireEvent.click(screen.getByTestId('editor-publish'));
    expect(await screen.findByRole('alert')).toHaveTextContent('immutable snapshot');
    expect(screen.getByTestId('editor-run')).toBeDisabled();
    expect(screen.getByTestId('editor-publish')).toBeDisabled();
    fireEvent.click(screen.getByTestId('editor-publish'));
    expect(save).toHaveBeenCalledOnce();
    view.unmount();
  });


});
