import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockAdapter } from '../api/mockAdapter';
import { useMvpStore } from '../mvp/mvpStore';
import ContractGatePicker from './ContractGatePicker';
import PropertyPanel from './PropertyPanel';
import { useEditorStore } from './store';

let api: MockAdapter;
beforeEach(()=>{
  api=new MockAdapter();
  act(()=>useMvpStore.setState({api,projectId:'proj_seed',runId:null,taskId:null}));
});
afterEach(()=>{cleanup();vi.restoreAllMocks();act(()=>useEditorStore.getState().reset());});

describe('project contract catalog',()=>{
  it('creates a server-backed Contract Gate and fills selected node config',async ()=>{
    const onChange=vi.fn();
    const create=vi.spyOn(api,'createContract');
    render(<ContractGatePicker api={api} value="" onChange={onChange}/>);
    await screen.findByRole('button',{name:/Создать Contract Gate/});
    fireEvent.click(screen.getByRole('button',{name:/Создать Contract Gate/}));
    await waitFor(()=>expect(onChange).toHaveBeenCalledOnce());
    expect(create).toHaveBeenCalledWith(expect.objectContaining({project_id:'proj_seed'}));
    expect(create.mock.calls[0][0].schema).toMatchObject({
      type:'object',required:['summary'],additionalProperties:false,
    });
    expect(screen.getByRole('option',{name:/Workflow summary/})).toBeInTheDocument();
  });

  it('does not create a contract without project selection',async ()=>{
    act(()=>useMvpStore.getState().selectProject(null));
    const create=vi.spyOn(api,'createContract');
    render(<ContractGatePicker api={api} value="" onChange={vi.fn()}/>);
    expect(screen.getByRole('button',{name:/Создать Contract Gate/})).toBeDisabled();
    expect(create).not.toHaveBeenCalled();
  });
});


describe('contract gate race and ownership boundaries',()=>{
  it('discards the old project catalog after a delayed GET completes',async()=>{
    const second=await api.createProject({name:'Other'});
    const old=await api.createContract({project_id:'proj_seed',name:'Old only',schema:{type:'object'}});
    const newer=await api.createContract({project_id:second.id,name:'New only',schema:{type:'object'}});
    const original=api.listContracts.bind(api);
    type Catalog=Awaited<ReturnType<typeof api.listContracts>>;
    let release!:(items:Catalog)=>void;
    const first=new Promise<Catalog>(resolve=>{release=resolve;});
    let calls=0;
    vi.spyOn(api,'listContracts').mockImplementation(()=>++calls===1?first:original());
    const onChange=vi.fn();
    render(<ContractGatePicker api={api} value="" onChange={onChange}/>);
    await waitFor(()=>expect(calls).toBe(1));
    act(()=>useMvpStore.getState().selectProject(second.id));
    await screen.findByRole('option',{name:'New only'});
    await act(async()=>{release(await original());});
    expect(screen.getByRole('option',{name:'New only'})).toHaveValue(newer.id);
    expect(screen.queryByRole('option',{name:'Old only'})).not.toBeInTheDocument();
    expect(screen.getByTestId('gate-contract-catalog')).not.toHaveValue(old.id);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('never selects a contract returned after switching project',async()=>{
    const second=await api.createProject({name:'Other'});
    const original=api.createContract.bind(api);
    let resume!:()=>void;
    const pending=new Promise<void>(resolve=>{resume=resolve;});
    const create=vi.spyOn(api,'createContract').mockImplementation(async request=>{
      await pending;return original(request);
    });
    const onChange=vi.fn();
    render(<ContractGatePicker api={api} value="" onChange={onChange}/>);
    fireEvent.click(screen.getByRole('button',{name:/Создать Contract Gate/}));
    await waitFor(()=>expect(create).toHaveBeenCalledOnce());
    act(()=>useMvpStore.getState().selectProject(second.id));
    await waitFor(()=>expect(screen.getByRole('button',{name:/Создать Contract Gate/})).toBeEnabled());
    await act(async()=>{resume();await pending;});
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('option',{name:/Workflow summary/})).not.toBeInTheDocument();
  });

  it('rejects an unexpected cross-project POST response rather than patching the node',async()=>{
    const original=api.createContract.bind(api);
    vi.spyOn(api,'createContract').mockImplementation(async request=>({
      ...await original(request),project_id:'another-project',
    }));
    const onChange=vi.fn();
    render(<ContractGatePicker api={api} value="" onChange={onChange}/>);
    fireEvent.click(screen.getByRole('button',{name:/Создать Contract Gate/}));
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent('другого проекта');
    expect(onChange).not.toHaveBeenCalled();
  });
});


describe('contract Gate node-selection isolation',()=>{
  it('does not write a late contract POST into a different selected Gate',async()=>{
    act(()=>useEditorStore.getState().reset());
    act(()=>{
      useEditorStore.getState().addNode('gate',{x:0,y:0});
      useEditorStore.getState().addNode('gate',{x:220,y:0});
    });
    const nodes=useEditorStore.getState().definition.nodes;
    act(()=>useEditorStore.getState().selectNode(nodes[0].id));
    const original=api.createContract.bind(api);
    let resume!:()=>void;
    const pending=new Promise<void>(resolve=>{resume=resolve;});
    const create=vi.spyOn(api,'createContract').mockImplementation(async input=>{
      await pending;return original(input);
    });
    render(<PropertyPanel api={api}/>);
    fireEvent.click(screen.getByRole('button',{name:/Создать Contract Gate/}));
    await waitFor(()=>expect(create).toHaveBeenCalledOnce());
    act(()=>useEditorStore.getState().selectNode(nodes[1].id));
    await act(async()=>{resume();await pending;});
    expect(useEditorStore.getState().definition.nodes[0].config.contract_id).toBeUndefined();
    expect(useEditorStore.getState().definition.nodes[1].config.contract_id).toBeUndefined();
  });
});
