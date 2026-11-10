import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ApiAdapter } from '../../api/types';
import { MockAdapter } from '../../api/mockAdapter';
import { useAgentDefinitions, useModelProfiles, useToolPolicies } from './referenceSelectors';

function CatalogView({api}:{api:ApiAdapter}) {
  const agents=useAgentDefinitions(api),models=useModelProfiles(api),policies=useToolPolicies(api);
  return <div>
    <span data-testid="agent-list">{agents.items.map(x=>x.name).join('|')}</span>
    <span data-testid="model-list">{models.items.map(x=>x.name).join('|')}</span>
    <span data-testid="policy-list">{policies.items.map(x=>x.name).join('|')}</span>
    <span data-testid="agent-loading">{String(agents.loading)}</span>
    {agents.error?<span role="alert">{agents.error}</span>:null}
  </div>;
}
afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe('editor inspector reference catalogs',()=>{
  it('loads all pages of agent, model and policy references',async()=>{
    const api=new MockAdapter();
    const originalAgents=await api.listAgentDefinitions();
    const originalModels=await api.listModelProfiles();
    const originalPolicies=await api.listToolPolicies();
    const ids=['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','cccccccc-cccc-4ccc-8ccc-cccccccccccc'];
    vi.spyOn(api,'listAgentDefinitions').mockImplementation(async params=>
      params?.after?{items:[{...originalAgents.items[0],id:ids[0],name:'Second agent'}],next_cursor:null}:
        {items:originalAgents.items,next_cursor:'agent-tail'});
    vi.spyOn(api,'listModelProfiles').mockImplementation(async params=>
      params?.after?{items:[{...originalModels.items[0],id:ids[1],name:'Second model'}],next_cursor:null}:
        {items:originalModels.items,next_cursor:'model-tail'});
    vi.spyOn(api,'listToolPolicies').mockImplementation(async params=>
      params?.after?{items:[{...originalPolicies.items[0],id:ids[2],name:'Second policy'}],next_cursor:null}:
        {items:originalPolicies.items,next_cursor:'policy-tail'});
    render(<CatalogView api={api}/>);
    await screen.findByText('Research Agent|Second agent');
    expect(screen.getByTestId('model-list')).toHaveTextContent('Second model');
    expect(screen.getByTestId('policy-list')).toHaveTextContent('Second policy');
  });

  it('fails closed on a repeating cursor and never offers partial catalog references',async()=>{
    const api=new MockAdapter();
    const seed=(await api.listAgentDefinitions()).items[0];
    vi.spyOn(api,'listAgentDefinitions').mockImplementation(async()=>({
      items:[seed],next_cursor:'same-cursor',
    }));
    render(<CatalogView api={api}/>);
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent('Повторный курсор');
    expect(screen.getByTestId('agent-list')).toBeEmptyDOMElement();
    expect(screen.getByTestId('agent-loading')).toHaveTextContent('false');
  });

  it('rejects a former adapter response after switching to a new server context',async()=>{
    const former=new MockAdapter(),current=new MockAdapter();
    type Page=Awaited<ReturnType<typeof former.listAgentDefinitions>>;
    let complete!:(page:Page)=>void;
    const held=new Promise<Page>(resolve=>{complete=resolve;});
    const original=former.listAgentDefinitions.bind(former);
    vi.spyOn(former,'listAgentDefinitions').mockImplementation(()=>held);
    const {rerender}=render(<CatalogView api={former}/>);
    rerender(<CatalogView api={current}/>);
    await screen.findByText('Research Agent');
    await act(async()=>{complete(await original());});
    expect(screen.getByTestId('agent-list')).toHaveTextContent('Research Agent');
    expect(screen.getByTestId('agent-loading')).toHaveTextContent('false');
  });
});
