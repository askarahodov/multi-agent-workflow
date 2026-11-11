import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import AgentProfilesPage from './AgentProfilesPage';
const json=(data:unknown,status=200)=>({ok:status<400,status,json:async()=>data});
const deny={id:'pol-deny',name:'deny-all',version:1,
  permissions:{fs_read:[],fs_write:[],git:[],shell:[],network:[]}};
const write={id:'pol-write',name:'developer-only',version:1,
  permissions:{fs_read:[],fs_write:['/srv/maw/workspace/project/out/**'],
    git:[],shell:[],network:[]}};
const model={id:'model-1',name:'offline',model_id:'offline/dry-run',provider_id:'provider-1'};
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
describe('canonical server-backed profiles route',()=>{
  it('loads a later-page model and uses the shared restricted editor for creating a reviewer',async()=>{
    const writes:Array<{url:string;method:string;body:Record<string,unknown>}>=[];
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      if(init?.method==='POST'){
        const body=JSON.parse(init.body as string) as Record<string,unknown>;
        writes.push({url,method:init.method,body});
        return json({...body,id:'review-created',version:1},201);
      }
      if(url.startsWith('/api/v1/agents/definitions?'))return json({items:[],next_cursor:null});
      if(url==='/api/v1/model-profiles?limit=100')return json({
        items:[{...model,id:'older',name:'older'}],next_cursor:'next-model'});
      if(url==='/api/v1/model-profiles?limit=100&after=next-model')return json({
        items:[model],next_cursor:null});
      if(url==='/api/v1/tool-policies')return json({items:[deny,write],next_cursor:null});
      return json({},404);
    }));
    render(<AgentProfilesPage/>);
    await screen.findByRole('option',{name:'offline — offline/dry-run'});
    fireEvent.change(screen.getByLabelText('Роль агента'),{target:{value:'reviewer'}});
    // The model catalogue and tool-policy catalogue are independent async reads.
    // Wait for the exact eligible policy before selecting it and submitting.
    await screen.findByRole('option',{name:'deny-all'});
    expect(screen.queryByRole('option',{name:'developer-only'})).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Имя профиля'),{target:{value:'Independent reviewer'}});
    fireEvent.change(screen.getByLabelText('System instructions'),{
      target:{value:'Independently inspect artifacts'},
    });
    fireEvent.change(screen.getByLabelText('Модель профиля'),{target:{value:model.id}});
    fireEvent.change(screen.getByLabelText('Tool policy'),{target:{value:deny.id}});
    fireEvent.click(screen.getByRole('button',{name:'Создать профиль'}));
    await waitFor(()=>expect(writes).toHaveLength(1));
    expect(writes[0]).toMatchObject({url:'/api/v1/agents/definitions',
      body:{role:'reviewer',default_tool_policy_id:deny.id,
        default_model_profile_id:model.id,supported_stages:['reviewer']}});
    expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('completions'))).toBe(false);
  });

  it('rejects cyclic model catalog before showing choices or allowing profile POST',async()=>{
    const post=vi.fn();
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      if(init?.method==='POST')return post();
      if(url.startsWith('/api/v1/model-profiles?'))return json({
        items:[model],next_cursor:'cycle'});
      if(url.startsWith('/api/v1/agents/definitions?'))return json({
        items:[],next_cursor:null});
      if(url==='/api/v1/tool-policies')return json({items:[deny],next_cursor:null});
      return json({},404);
    }));
    render(<AgentProfilesPage/>);
    expect(await screen.findByTestId('profiles-catalog-error')).toHaveTextContent(
      'Каталог профилей или моделей недоступен');
    expect(screen.queryByRole('option',{name:'offline — offline/dry-run'})).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('ignores stale catalog reload after a confirmed save, preserving saved profile',async()=>{
    let release!:(value:ReturnType<typeof json>)=>void;
    const held=new Promise<ReturnType<typeof json>>(resolve=>{release=resolve;});
    let reads=0;
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      if(url.startsWith('/api/v1/agents/definitions?')){
        reads++;
        if(reads===2)return held;
        return json({items:[],next_cursor:null});
      }
      if(url.startsWith('/api/v1/model-profiles?'))return json({items:[model],next_cursor:null});
      if(url==='/api/v1/tool-policies')return json({items:[deny],next_cursor:null});
      if(url==='/api/v1/agents/definitions' && init?.method==='POST'){
        return json({...(JSON.parse(init.body as string) as object),id:'saved-on-server',
          version:1},201);
      }
      return json({},404);
    }));
    render(<AgentProfilesPage/>);
    await screen.findByRole('option',{name:'offline — offline/dry-run'});
    fireEvent.change(screen.getByLabelText('Имя профиля'),{target:{value:'Verified author'}});
    fireEvent.change(screen.getByLabelText('System instructions'),{
      target:{value:'Implement scoped changes'}});
    fireEvent.change(screen.getByLabelText('Модель профиля'),{target:{value:model.id}});
    fireEvent.change(screen.getByLabelText('Tool policy'),{target:{value:deny.id}});
    fireEvent.click(screen.getByRole('button',{name:'Создать профиль'}));
    await screen.findByText(/Verified author/);
    expect(reads).toBe(2);
    await act(async()=>{release(json({items:[],next_cursor:null}));await held;});
    // A successful GET is allowed to reflect an authoritative server view;
    // no stale initial GET can be applied after a newer epoch.
    expect(reads).toBe(2);
  });
});
