import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,afterEach,describe,expect,it,vi} from 'vitest';
import GuidedTemplateBuilder,{buildConfiguredPreset} from './GuidedTemplateBuilder';
import {compilePreview} from './publishedPreview';
import {MockAdapter} from '../api/mockAdapter';
import {useMvpStore} from '../mvp/mvpStore';

const refs={
  agent:MockAdapter.seed.agentDefinitionId,
  model:MockAdapter.seed.modelProfileId,
  policy:MockAdapter.seed.toolPolicyId,
};
const contract='00000000-0000-4000-8000-000000000001';
beforeEach(()=>{cleanup();act(()=>useMvpStore.setState({projectId:'proj_seed'}));});
afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe('real server-backed SDLC preset wizard',()=>{
  it('creates executable simple and seven-stage graphs using no invented references',()=>{
    const one=buildConfiguredPreset('simple',[refs],contract);
    expect(one.nodes.map(n=>n.type)).toEqual(['start','agent','gate','end']);
    expect(one.nodes[1].config).toEqual({
      agent_definition_id:refs.agent,model_profile_id:refs.model,tool_policy_id:refs.policy,
    });
    expect(compilePreview(one).errors).toEqual([]);
    expect(compilePreview(one).tasks).toHaveLength(1);
    const full=buildConfiguredPreset('sdlc',Array.from({length:7},()=>({...refs})),contract);
    expect(full.nodes).toHaveLength(16);
    expect(full.edges).toHaveLength(15);
    expect(compilePreview(full).errors).toEqual([]);
    expect(compilePreview(full).tasks).toHaveLength(7);
    expect(compilePreview(full).tasks[6].depends_on).toEqual([5]);
    expect(full.nodes.filter(n=>n.type==='gate')).toHaveLength(7);
  });

  it('refuses missing model, invalid server references and inconsistent stages',()=>{
    expect(()=>buildConfiguredPreset('simple',[{...refs,model:''}],contract)).toThrow();
    expect(()=>buildConfiguredPreset('sdlc',[refs],contract)).toThrow();
    expect(()=>buildConfiguredPreset('simple',[refs],'not-a-contract')).toThrow();
  });

  it('retrieves real catalogs and creates a project-scoped contract before building',async()=>{
    const api=new MockAdapter();
    const onBuild=vi.fn();
    render(<GuidedTemplateBuilder api={api} projectId="proj_seed" onBuild={onBuild}/>);
    fireEvent.click(screen.getByText('Собрать готовый процесс из реальных агентов и контрактов'));
    await screen.findByRole('option',{name:'Research Agent'});
    expect(screen.getByTestId('preset-build')).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'Создать типовой контракт «summary»'}));
    await waitFor(()=>expect(screen.getByTestId('preset-contract')).toHaveValue(contract));
    fireEvent.change(screen.getByTestId('preset-agent-0'),{target:{value:refs.agent}});
    fireEvent.change(screen.getByTestId('preset-model-0'),{target:{value:refs.model}});
    fireEvent.change(screen.getByTestId('preset-policy-0'),{target:{value:refs.policy}});
    expect(screen.getByTestId('preset-build')).toBeEnabled();
    fireEvent.click(screen.getByTestId('preset-build'));
    expect(onBuild).toHaveBeenCalledOnce();
    const document=onBuild.mock.calls[0][0];
    expect(compilePreview(document).errors).toEqual([]);
    const contracts=await api.listContracts();
    expect(contracts).toHaveLength(1);
    expect(contracts[0].project_id).toBe('proj_seed');
  });

  it('does not submit without project; does not trigger inference or launch',async()=>{
    const api=new MockAdapter();
    const launch=vi.spyOn(api,'launchRun');
    const onBuild=vi.fn();
    render(<GuidedTemplateBuilder api={api} projectId={null} onBuild={onBuild}/>);
    fireEvent.click(screen.getByText('Собрать готовый процесс из реальных агентов и контрактов'));
    await screen.findByRole('option',{name:'Research Agent'});
    expect(screen.getByTestId('preset-build')).toBeDisabled();
    expect(screen.getByRole('button',{name:'Создать типовой контракт «summary»'})).toBeDisabled();
    expect(onBuild).not.toHaveBeenCalled();
    expect(launch).not.toHaveBeenCalled();
  });
  it('honors saved agent model/tool-policy bindings rather than arbitrary editor choices',async()=>{
    const api=new MockAdapter();
    const original=api.listAgentDefinitions.bind(api);
    vi.spyOn(api,'listAgentDefinitions').mockImplementation(async params=>{
      const page=await original(params);
      return {...page,items:page.items.map(agent=>({...agent,
        default_model_profile_id:refs.model,
        default_tool_policy_id:refs.policy,
      }))};
    });
    const onBuild=vi.fn();
    render(<GuidedTemplateBuilder api={api} projectId="proj_seed" onBuild={onBuild}/>);
    fireEvent.click(screen.getByText('Собрать готовый процесс из реальных агентов и контрактов'));
    await screen.findByRole('option',{name:'Research Agent'});
    fireEvent.click(screen.getByRole('button',{name:'Создать типовой контракт «summary»'}));
    await waitFor(()=>expect(screen.getByTestId('preset-contract')).toHaveValue(contract));
    fireEvent.change(screen.getByTestId('preset-agent-0'),{target:{value:refs.agent}});
    expect(screen.getByTestId('preset-model-0')).toHaveValue(refs.model);
    expect(screen.getByTestId('preset-policy-0')).toHaveValue(refs.policy);
    expect(screen.getByTestId('preset-build')).toBeEnabled();
    fireEvent.click(screen.getByTestId('preset-build'));
    expect(onBuild).toHaveBeenCalledOnce();
    expect(onBuild.mock.calls[0][0].nodes[1].config).toMatchObject({
      agent_definition_id:refs.agent,
      model_profile_id:refs.model,
      tool_policy_id:refs.policy,
    });
  });

  it('refuses an orphaned profile binding instead of substituting an unrelated model',async()=>{
    const api=new MockAdapter();
    const original=api.listAgentDefinitions.bind(api);
    vi.spyOn(api,'listAgentDefinitions').mockImplementation(async params=>{
      const page=await original(params);
      return {...page,items:page.items.map(agent=>({...agent,
        default_model_profile_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        default_tool_policy_id:refs.policy,
      }))};
    });
    const onBuild=vi.fn();
    render(<GuidedTemplateBuilder api={api} projectId="proj_seed" onBuild={onBuild}/>);
    fireEvent.click(screen.getByText('Собрать готовый процесс из реальных агентов и контрактов'));
    await screen.findByRole('option',{name:'Research Agent'});
    fireEvent.click(screen.getByRole('button',{name:'Создать типовой контракт «summary»'}));
    await waitFor(()=>expect(screen.getByTestId('preset-contract')).toHaveValue(contract));
    fireEvent.change(screen.getByTestId('preset-agent-0'),{target:{value:refs.agent}});
    expect(screen.getByTestId('preset-build')).toBeDisabled();
    expect(screen.getByTestId('preset-model-0').querySelectorAll('option')).toHaveLength(1);
    expect(onBuild).not.toHaveBeenCalled();
  });

});
