/** Project-filtered, race-safe contract selector for an executable automatic Gate. */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiAdapter, ContractResponse } from '../api/types';
import { useMvpStore } from '../mvp/mvpStore';
import { Button, Select } from '../components';

export default function ContractGatePicker({
  api, value, onChange,
}: {api:ApiAdapter;value:string;onChange:(id:string)=>void}) {
  const projectId = useMvpStore((s)=>s.projectId);
  const [items,setItems] = useState<ContractResponse[]>([]);
  const [loadedScope,setLoadedScope] = useState<{api:ApiAdapter;projectId:string|null}|null>(null);
  // Old GET/POST results must not repopulate a different project or a
  // different selected Gate (the parent keys this component by node ID).
  const currentScope=useRef({api,projectId});
  currentScope.current={api,projectId};
  const catalogGeneration=useRef(0);
  const createGeneration=useRef(0);
  const [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const visibleItems=loadedScope?.api===api && loadedScope.projectId===projectId ? items : [];

  const reload = useCallback(async () => {
    const generation=++catalogGeneration.current;
    const isCurrent=()=>generation===catalogGeneration.current &&
      currentScope.current.api===api && currentScope.current.projectId===projectId;
    setLoading(true);setItems([]);setLoadedScope(null);setError('');
    try {
      const contracts=await api.listContracts();
      if(!isCurrent())return;
      setItems(contracts.filter((c)=>!c.project_id || c.project_id === projectId));
      setLoadedScope({api,projectId});
    } catch (cause) {
      if(isCurrent())setError(cause instanceof Error?cause.message:String(cause));
    } finally {if(isCurrent())setLoading(false);}
  },[api,projectId]);
  useEffect(()=>{
    void reload();
    return ()=>{catalogGeneration.current++;createGeneration.current++;};
  },[reload]);
  useEffect(()=>{
    createGeneration.current++;
    setBusy(false);
  },[api,projectId]);

  async function createContract() {
    if (!projectId || busy) return;
    const generation=++createGeneration.current;
    const isCurrent=()=>generation===createGeneration.current &&
      currentScope.current.api===api && currentScope.current.projectId===projectId;
    setBusy(true);setError('');
    try {
      const created=await api.createContract({
        project_id:projectId,
        name:'Workflow summary ' + new Date().toISOString(),
        schema:{
          type:'object',required:['summary'],
          properties:{summary:{type:'string',minLength:1}},
          additionalProperties:false,
        },
      });
      if(!isCurrent())return;
      if(created.project_id!==projectId)
        throw new Error('Сервер вернул контракт другого проекта');
      onChange(created.id);
      await reload();
    } catch (cause) {
      if(isCurrent())setError(cause instanceof Error?cause.message:String(cause));
    } finally {if(isCurrent())setBusy(false);}
  }
  const scopedReady=loadedScope?.api===api && loadedScope.projectId===projectId;
  return <div style={{marginTop:12,borderTop:'1px solid #cbd5e1',paddingTop:8}}>
    <label htmlFor="gate-contract-catalog">Выбрать сохранённый контракт</label>
    <Select id="gate-contract-catalog" data-testid="gate-contract-catalog"
      value={visibleItems.some((c)=>c.id===value)?value:''}
      disabled={!scopedReady||loading||busy} onChange={(event)=>{
        const id=event.target.value;
        if(!id||visibleItems.some(c=>c.id===id))onChange(id);
      }}>
      <option value="">Выберите контракт</option>
      {visibleItems.map((c)=><option key={c.id} value={c.id}>{c.name}</option>)}
    </Select>
    {!visibleItems.length&&!loading&&scopedReady ? <p>Контрактов нет. Создайте типовой контракт или укажите действительный ID.</p>:null}
    <Button variant="secondary" disabled={busy||!projectId} onClick={()=>{void createContract();}}>
      Создать Contract Gate «summary»
    </Button>
    {!projectId?<p>Сначала выберите проект в разделе «Проект».</p>:null}
    {error?<p role="alert">{error}</p>:null}
  </div>;
}
