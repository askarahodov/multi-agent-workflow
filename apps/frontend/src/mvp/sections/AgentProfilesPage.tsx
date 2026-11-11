/** The Profiles navigation and Settings now share one canonical restricted
 * AgentProfilesManager. Run/worker registration remains separate. */
import {useCallback,useEffect,useRef,useState} from 'react';
import {PageHeader} from '../../patterns';
import AgentProfilesManager, {
  type AgentProfile,type AgentModel,
} from './AgentProfilesManager';

type CatalogPage<T>={items:T[];next_cursor?:string|null};
async function read<T>(url:string):Promise<T>{
  const response=await fetch(url,{credentials:'same-origin',
    headers:{'Content-Type':'application/json'}});
  if(!response.ok)throw new Error('Каталог профилей недоступен: HTTP '+response.status);
  return response.json() as Promise<T>;
}
async function allPages<T extends {id:string}>(path:string):Promise<T[]>{
  const result:T[]=[];
  const seen=new Set<string>();
  let cursor:string|undefined;
  for(let index=0;index<100;index++){
    const url=path+'?limit=100'+(cursor?'&after='+encodeURIComponent(cursor):'');
    const page=await read<CatalogPage<T>>(url);
    if(!Array.isArray(page.items)||page.items.length>100 ||
       page.items.some(value=>!value || typeof value.id!=='string' || !value.id))
      throw new Error('Некорректная страница каталога профилей');
    result.push(...page.items);
    if(page.next_cursor==null)return result;
    if(typeof page.next_cursor!=='string' || !page.next_cursor ||
       page.next_cursor.length>512 || !page.items.length ||seen.has(page.next_cursor))
      throw new Error('Некорректный курсор каталога профилей');
    seen.add(page.next_cursor);
    cursor=page.next_cursor;
  }
  throw new Error('Превышен лимит страниц каталога профилей');
}

export default function AgentProfilesPage(){
  const [agents,setAgents]=useState<AgentProfile[]>([]);
  const [models,setModels]=useState<AgentModel[]>([]);
  const [loaded,setLoaded]=useState(false);
  const [error,setError]=useState('');
  const epoch=useRef(0);
  const reload=useCallback(async()=>{
    const generation=++epoch.current;
    try{
      const [profiles,modelCatalog]=await Promise.all([
        allPages<AgentProfile>('/api/v1/agents/definitions'),
        allPages<AgentModel>('/api/v1/model-profiles'),
      ]);
      if(epoch.current!==generation)return;
      setAgents(profiles);
      setModels(modelCatalog);
      setError('');
      setLoaded(true);
    }catch{
      if(epoch.current!==generation)return;
      // The server, not an older client snapshot, must authorize references.
      // A failed reload after a successful mutation keeps the confirmed
      // profile visible, but blanks the model selector until recovery.
      setModels([]);
      setError('Каталог профилей или моделей недоступен; сохранение отключено до обновления.');
      setLoaded(true);
    }
  },[]);
  useEffect(()=>{
    void reload();
    return ()=>{epoch.current++;};
  },[reload]);
  const onSaved=useCallback((profile:AgentProfile)=>{
    // POST/PATCH-confirmed profile is visible immediately. Obsolete GET
    // completions cannot replace it while the post-mutation reload runs.
    epoch.current++;
    setAgents(current=>[profile,...current.filter(x=>x.id!==profile.id)]);
    void reload();
  },[reload]);

  return <div>
    <PageHeader title="Профили агентов"
      subtitle="Одна проверяемая форма для создания профилей в разделе «Профили» и в «Настройках»."/>
    <p>Профиль AI-агента не является leased native worker. Запуск и доступ к инструментам
      требуют server preflight, привязки профиля и доверенного gateway; здесь не выполняются платные запросы.</p>
    {error?<p role="alert" data-testid="profiles-catalog-error">{error}</p>:null}
    {!loaded?<p role="status">Загрузка каталога профилей и моделей…</p>:
      <AgentProfilesManager agents={agents} models={models} onSaved={onSaved}/>}
  </div>;
}
