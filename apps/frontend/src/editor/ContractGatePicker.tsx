/** Project-filtered contract selector for an executable automatic Gate. */
import { useCallback, useEffect, useState } from 'react';
import type { ApiAdapter, ContractResponse } from '../api/types';
import { useMvpStore } from '../mvp/mvpStore';
import { Button, Select } from '../components';

export default function ContractGatePicker({
  api, value, onChange,
}: {api:ApiAdapter;value:string;onChange:(id:string)=>void}) {
  const projectId = useMvpStore((s)=>s.projectId);
  const [items,setItems] = useState<ContractResponse[]>([]);
  const [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const reload = useCallback(async () => {
    setLoading(true);setError('');
    try {
      const contracts=await api.listContracts();
      setItems(contracts.filter((c)=>!c.project_id || c.project_id === projectId));
    } catch (cause) {
      setError(cause instanceof Error?cause.message:String(cause));
    } finally {setLoading(false);}
  },[api,projectId]);
  useEffect(()=>{void reload();},[reload]);

  async function createContract() {
    if (!projectId || busy) return;
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
      onChange(created.id);
      await reload();
    } catch (cause) {
      setError(cause instanceof Error?cause.message:String(cause));
    } finally {setBusy(false);}
  }
  return <div style={{marginTop:12,borderTop:'1px solid #cbd5e1',paddingTop:8}}>
    <label htmlFor="gate-contract-catalog">Выбрать сохранённый контракт</label>
    <Select id="gate-contract-catalog" data-testid="gate-contract-catalog"
      value={items.some((c)=>c.id===value)?value:''}
      disabled={loading||busy} onChange={(event)=>onChange(event.target.value)}>
      <option value="">Выберите контракт</option>
      {items.map((c)=><option key={c.id} value={c.id}>{c.name}</option>)}
    </Select>
    {!items.length&&!loading ? <p>Контрактов нет. Создайте типовой контракт или укажите действительный ID.</p>:null}
    <Button variant="secondary" disabled={busy||!projectId} onClick={()=>{void createContract();}}>
      Создать Contract Gate «summary»
    </Button>
    {!projectId?<p>Сначала выберите проект в разделе «Проект».</p>:null}
    {error?<p role="alert">{error}</p>:null}
  </div>;
}
