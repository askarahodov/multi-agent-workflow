/** Assemble real, publishable linear SDLC graphs from server-owned references.
 * The wizard creates an in-memory draft only; the operator must separately
 * save, publish, and explicitly consent to a potentially paid run.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ApiAdapter, AgentDefinitionRef, ModelProfileRef, ToolPolicyRef, ContractResponse } from '../api/types';
import type { WorkflowDefinition, WorkflowEdge, WorkflowNode } from '../workflow/types';
import { SCHEMA_VERSION } from '../workflow/types';
import { DRAFT_TEMPLATES, type TemplateId } from './nodeGuides';
import { allPages } from './paginateCatalog';
import { Button, Select } from '../components';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Catalog = { agents: AgentDefinitionRef[]; models: ModelProfileRef[]; policies: ToolPolicyRef[]; contracts: ContractResponse[] };
type StageChoice = { agent: string; model: string; policy: string };
const EMPTY_CHOICE: StageChoice = {agent:'',model:'',policy:''};

/** The subset accepted by both browser preview and server compiler. */
export function buildConfiguredPreset(
  preset:TemplateId, choices:StageChoice[], contractId:string,
):WorkflowDefinition {
  const template=DRAFT_TEMPLATES.find((item)=>item.id===preset);
  if(!template || choices.length!==template.stages.length || !UUID.test(contractId)) {
    throw new Error('Укажите действительный контракт и профили для всех стадий');
  }
  if(choices.some(choice=>!UUID.test(choice.agent)||!UUID.test(choice.model)||!UUID.test(choice.policy))) {
    throw new Error('Каждая стадия требует серверные UUID агента, модели и tool-policy');
  }
  const nodes:WorkflowNode[]=[{
    id:'start',type:'start',label:'Начало',position:{x:0,y:100},config:{},
  }];
  for(let i=0;i<template.stages.length;i++){
    const choice=choices[i];
    const x=(i*2+1)*220;
    nodes.push({
      id:`agent-${i+1}`,type:'agent',label:template.stages[i],
      position:{x,y:100},config:{
        agent_definition_id:choice.agent,
        model_profile_id:choice.model,
        tool_policy_id:choice.policy,
      },
    });
    nodes.push({
      id:`gate-${i+1}`,type:'gate',label:`Contract Gate: ${template.stages[i]}`,
      position:{x:x+220,y:100},config:{gate_type:'automatic',contract_id:contractId},
    });
  }
  nodes.push({
    id:'end',type:'end',label:'Завершение',
    position:{x:(template.stages.length*2+1)*220,y:100},config:{},
  });
  const edges:WorkflowEdge[]=nodes.slice(0,-1).map((node,i)=>({
    id:`link-${i+1}`,source_node_id:node.id,target_node_id:nodes[i+1].id,
    output_mapping:{},on_error:'fail',max_retries:0,
  }));
  return {
    schema_version:SCHEMA_VERSION,
    metadata:{
      name:template.title,description:template.description,version:1,
      created_at:new Date().toISOString(),
    },
    nodes,edges,
  };
}

export default function GuidedTemplateBuilder({
  api,projectId,disabled,onBuild,
}:{
  api:ApiAdapter;projectId:string|null;disabled?:boolean;
  onBuild:(definition:WorkflowDefinition)=>void;
}){
  const [preset,setPreset]=useState<TemplateId>('simple');
  const [catalog,setCatalog]=useState<Catalog|null>(null);
  // Discard late responses from a previous project, adapter, or catalog refresh.
  const currentScope=useRef({api,projectId});
  currentScope.current={api,projectId};
  const catalogGeneration=useRef(0);
  const contractGeneration=useRef(0);
  const [loadedScope,setLoadedScope]=useState<{api:ApiAdapter;projectId:string|null}|null>(null);
  const [contractId,setContractId]=useState('');
  const [choices,setChoices]=useState<StageChoice[]>([{...EMPTY_CHOICE}]);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const template=useMemo(()=>DRAFT_TEMPLATES.find((item)=>item.id===preset)!,[preset]);

  const load=useCallback(async()=>{
    const generation=++catalogGeneration.current;
    const isCurrent=()=>generation===catalogGeneration.current &&
      currentScope.current.api===api && currentScope.current.projectId===projectId;
    setLoading(true);setCatalog(null);setLoadedScope(null);setError('');
    try{
      const [agents,models,policies,contracts]=await Promise.all([
        allPages((after)=>api.listAgentDefinitions({after,limit:100})),
        allPages((after)=>api.listModelProfiles({after,limit:100})),
        allPages((after)=>api.listToolPolicies({after,limit:100})),
        api.listContracts(),
      ]);
      if(!isCurrent())return;
      setCatalog({agents,models,policies,
        contracts:contracts.filter((item)=>!item.project_id||item.project_id===projectId)});
      setLoadedScope({api,projectId});
    }catch(cause){
      if(!isCurrent())return;
      setCatalog(null);
      setError(cause instanceof Error?cause.message:String(cause));
    }finally{if(isCurrent())setLoading(false);}
  },[api,projectId]);
  useEffect(()=>{
    void load();
    return()=>{catalogGeneration.current++;};
  },[load]);
  useEffect(()=>{
    // The old project/adapter may still be processing a contract POST.
    // Neither its selected contract nor its stage selections belong to the new scope.
    contractGeneration.current++;
    setContractId('');
    setChoices(DRAFT_TEMPLATES.find(t=>t.id===preset)!.stages.map(()=>({...EMPTY_CHOICE})));
    setBusy(false);
  },[api,projectId]);

  function changePreset(next:TemplateId){
    setPreset(next);setChoices(DRAFT_TEMPLATES.find(t=>t.id===next)!.stages.map(()=>({...EMPTY_CHOICE})));
  }
  function update(index:number,field:keyof StageChoice,value:string){
    setChoices(items => items.map((choice,i) => {
      if(i!==index)return choice;
      if(field!=='agent') return {...choice,[field]:value};
      const definition=catalog?.agents.find(item=>item.id===value);
      return {
        agent:value,
        // Bound profile references outrank stale manual choices. An orphaned
        // reference disables draft creation until the operator repairs it.
        model:definition?.default_model_profile_id??'',
        policy:definition?.default_tool_policy_id??'',
      };
    }));
  }
  async function createContract(){
    if(!projectId||busy||disabled)return;
    const generation=++contractGeneration.current;
    const isCurrent=()=>generation===contractGeneration.current &&
      currentScope.current.api===api && currentScope.current.projectId===projectId;
    setBusy(true);setError('');
    try{
      const created=await api.createContract({
        project_id:projectId,
        name:'Workflow summary '+new Date().toISOString(),
        schema:{
          type:'object',required:['summary'],
          properties:{summary:{type:'string',minLength:1}},additionalProperties:false,
        },
      });
      if(!isCurrent())return;
      setContractId(created.id);
      await load();
    }catch(cause){
      if(isCurrent())setError(cause instanceof Error?cause.message:String(cause));
    }finally{if(isCurrent())setBusy(false);}
  }
  const ready=Boolean(projectId&&loadedScope?.api===api&&loadedScope?.projectId===projectId&&
    catalog&&catalog.contracts.some(c=>c.id===contractId)&&
    choices.length===template.stages.length&&
    choices.every(choice=>{
      const agent=catalog.agents.find(a=>a.id===choice.agent);
      return Boolean(agent &&
        (!agent.default_model_profile_id||agent.default_model_profile_id===choice.model) &&
        (!agent.default_tool_policy_id||agent.default_tool_policy_id===choice.policy) &&
        catalog.models.some(m=>m.id===choice.model) &&
        catalog.policies.some(p=>p.id===choice.policy));
    }));
  function createDraft(){
    if(!ready||disabled||busy)return;
    try{
      const definition=buildConfiguredPreset(preset,choices,contractId);
      onBuild(definition);
    }catch(cause){setError(cause instanceof Error?cause.message:String(cause));}
  }

  return <details data-testid="configured-template-builder" style={{padding:'8px 12px',borderBottom:'1px solid var(--color-border)'}}>
    <summary style={{cursor:'pointer',fontWeight:600}}>Собрать готовый процесс из реальных агентов и контрактов</summary>
    <p>Выберите шаблон и заполните каждую стадию серверными профилями. Будет создан линейный граф с automatic Contract Gate после каждого агента. Само создание черновика ничего не запускает.</p>
    {loading?<p role="status">Загрузка справочников…</p>:null}
    {error?<p role="alert">{error}</p>:null}
    {!projectId?<p role="status">Сначала выберите проект в разделе «Проект».</p>:null}
    <label htmlFor="preset-type">Сценарий</label>
    <Select id="preset-type" data-testid="preset-type" value={preset}
      disabled={busy||disabled} onChange={event=>changePreset(event.target.value as TemplateId)}
      style={{maxWidth:300,marginBlockEnd:8}}>
      {DRAFT_TEMPLATES.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}
    </Select>
    <div style={{display:'flex',gap:8,flexWrap:'wrap',alignItems:'center',marginBottom:12}}>
      <label htmlFor="preset-contract">Единый контракт выхода для каждой стадии</label>
      <Select id="preset-contract" data-testid="preset-contract" value={contractId}
        disabled={busy||loading||disabled} onChange={event=>setContractId(event.target.value)}
        style={{maxWidth:340,marginBlockEnd:0}}>
        <option value="">Выберите сохранённый контракт</option>
        {catalog?.contracts.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
      </Select>
      <Button variant="secondary" disabled={busy||loading||disabled||!projectId}
        onClick={()=>{void createContract();}}>Создать типовой контракт «summary»</Button>
    </div>
    <p style={{fontSize:12}}>Контракт «summary» требует JSON-объект с непустым строковым полем summary. Все агенты в этом шаблоне должны возвращать совместимый результат.</p>
    {template.stages.map((stage,i)=><fieldset key={i} style={{display:'flex',flexWrap:'wrap',gap:8,marginBottom:8,padding:8}}>
      <legend>{i+1}. {stage}</legend>
      <label htmlFor={`preset-agent-${i}`}>Агент</label>
      <Select id={`preset-agent-${i}`} data-testid={`preset-agent-${i}`} value={choices[i]?.agent??''}
        disabled={busy||loading||disabled} onChange={e=>update(i,'agent',e.target.value)}
        style={{maxWidth:210,marginBottom:0}}>
        <option value="">Выберите агента</option>
        {catalog?.agents.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}
      </Select>
      <label htmlFor={`preset-model-${i}`}>Модель</label>
      <Select id={`preset-model-${i}`} data-testid={`preset-model-${i}`} value={choices[i]?.model??''}
        disabled={busy||loading||disabled} onChange={e=>update(i,'model',e.target.value)}
        style={{maxWidth:210,marginBottom:0}}>
        <option value="">Выберите модель</option>
        {catalog?.models.filter(m=>{
          const bound=catalog.agents.find(a=>a.id===choices[i]?.agent)?.default_model_profile_id;
          return !bound||m.id===bound;
        }).map(m=><option key={m.id} value={m.id}>{m.name}</option>)}
      </Select>
      <label htmlFor={`preset-policy-${i}`}>Политика инструментов</label>
      <Select id={`preset-policy-${i}`} data-testid={`preset-policy-${i}`} value={choices[i]?.policy??''}
        disabled={busy||loading||disabled} onChange={e=>update(i,'policy',e.target.value)}
        style={{maxWidth:210,marginBottom:0}}>
        <option value="">Выберите политику</option>
        {catalog?.policies.filter(p=>{
          const bound=catalog.agents.find(a=>a.id===choices[i]?.agent)?.default_tool_policy_id;
          return !bound||p.id===bound;
        }).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
      </Select>
    </fieldset>)}
    <p style={{fontSize:12}}>Если сохранённый Agent Profile закрепляет model/tool-policy,
      выбор подставляется из профиля и не может быть заменён в шаблоне.
      Удалённые ссылки блокируют создание черновика до исправления профиля.</p>
    <p style={{fontSize:12}}>Роли «Ревьюер», «Тестировщик» и «Security» в схеме — логические исполнители. Независимые QA-вердикты и human release approval по-прежнему подтверждаются отдельными backend-участниками; подписи узлов их не заменяют.</p>
    <Button data-testid="preset-build" disabled={!ready||busy||loading||disabled} onClick={createDraft}>
      Создать проверяемый черновик
    </Button>
    <Button variant="secondary" disabled={busy||loading} onClick={()=>{void load();}}>Обновить справочники</Button>
  </details>;
}
