import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockAdapter } from '../api/mockAdapter';
import { useMvpStore } from '../mvp/mvpStore';
import ContractGatePicker from './ContractGatePicker';

let api: MockAdapter;
beforeEach(()=>{
  api=new MockAdapter();
  act(()=>useMvpStore.setState({api,projectId:'proj_seed',runId:null,taskId:null}));
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});

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
