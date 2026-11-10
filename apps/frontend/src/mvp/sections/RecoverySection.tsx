/** Operator-only recovery: read-only until an evidence-backed ADMIN POST.
 * Never retries, reclaims, requeues or auto-resumes interrupted tool calls. */
import {type FormEvent,useEffect,useRef,useState} from 'react';
import {ProblemDetailsError} from '../../api/client';
import {sanitizeTaskDisplayText} from '../../api/taskDisplayRedaction';
import type {ApiAdapter,ReconciliationDecision,ReconciliationRequest,ReconciliationResponse,
  RecoveryLedgerReport,TaskResponse} from '../../api/types';
import {useMvpStore} from '../mvpStore';
import {Card,PageHeader,StatusBadge} from '../ui';

const DECISIONS:Array<{value:ReconciliationDecision;label:string}>=[
  {value:'UNKNOWN',label:'Исход неизвестен — оставить карантин'},
  {value:'CONFIRMED_SIDE_EFFECT',label:'Побочное действие подтверждено'},
  {value:'CONFIRMED_NO_SIDE_EFFECT',label:'Отсутствие побочного действия подтверждено'},
];
const PART=/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const PROTECTED=new Set(['.git','.ssh','.hermes','.aws','.gnupg','.kube']);
function validEvidenceRef(ref:string):boolean{
  return !!ref && ref.length<=160 && ref.split('/').every(part=>
    PART.test(part) && part!=='.' && part!=='..' &&
    !PROTECTED.has(part.toLowerCase()) && !part.toLowerCase().startsWith('.env'));
}
type PostState='posting'|'uncertain'|'settled';
type PostLock=ReconciliationRequest & {state:PostState};
const LOCK_STORAGE='maw:recovery-uncertain-posts:v1';
const locksByAdapter=new WeakMap<ApiAdapter,Map<string,PostLock>>();
const DIGEST=/^[0-9a-f]{64}$/;
const DECISION_SET=new Set(DECISIONS.map(item=>item.value));
function validPostLock(value:unknown):value is PostLock{
  if(!value || typeof value!=='object')return false;
  const v=value as Partial<PostLock>;
  return (v.state==='posting'||v.state==='uncertain'||v.state==='settled') &&
    !!v.decision && DECISION_SET.has(v.decision) &&
    typeof v.evidence_ref==='string' && validEvidenceRef(v.evidence_ref) &&
    typeof v.evidence_sha256==='string' && DIGEST.test(v.evidence_sha256);
}
function recoveryLocks(api:ApiAdapter):Map<string,PostLock>{
  const existing=locksByAdapter.get(api);
  if(existing)return existing;
  const result=new Map<string,PostLock>();
  try{
    const value:unknown=JSON.parse(sessionStorage.getItem(LOCK_STORAGE)??'{}');
    if(value && typeof value==='object' && !Array.isArray(value)){
      for(const [id,record] of Object.entries(value)){
        if(/^[A-Za-z0-9._-]{1,128}$/.test(id) && validPostLock(record)){
          result.set(id,{...record,state:'uncertain'});
        }
      }
    }
  }catch{ /* Browser storage is never the server's source of truth. */ }
  locksByAdapter.set(api,result);
  return result;
}
function persistRecoveryLocks(locks:Map<string,PostLock>){
  try{
    const data:Record<string,PostLock>={};
    for(const [id,record] of locks){
      if(/^[A-Za-z0-9._-]{1,128}$/.test(id))data[id]=record;
    }
    sessionStorage.setItem(LOCK_STORAGE,JSON.stringify(data));
  }catch{ /* Server reconciliation remains authoritative. */ }
}
function detail(error:unknown):string{
  if(error instanceof ProblemDetailsError){
    if(error.status===401||error.status===403)return 'Требуется доступ администратора.';
    if(error.status===503)return 'Сервис проверки недоступен или не настроен.';
    if(error.status===404)return 'Запись не найдена.';
    return error.message;
  }
  return 'Запрос не выполнен. Проверьте соединение с Orchestration API.';
}
function validDecision(value:ReconciliationResponse,taskId:string):boolean{
  return !!value && value.task_id===taskId && DECISION_SET.has(value.decision) &&
    typeof value.evidence_ref==='string' && validEvidenceRef(value.evidence_ref) &&
    typeof value.evidence_sha256==='string' && DIGEST.test(value.evidence_sha256) &&
    typeof value.operator_subject==='string' && !!value.operator_subject.trim() &&
    typeof value.decided_at==='string' && Number.isFinite(Date.parse(value.decided_at));
}
function validLedger(value:RecoveryLedgerReport,taskId:string):boolean{
  return !!value && value.task_id===taskId && value.ledger_status==='AVAILABLE' &&
    Array.isArray(value.attempts) && value.attempts.every(a=>
      a && typeof a.attempt_id==='string' && !!a.attempt_id &&
      (a.record_status==='RECORDS'||a.record_status==='NO_RECORDS') &&
      Array.isArray(a.entries) &&
      (a.record_status!=='NO_RECORDS'||a.entries.length===0) &&
      a.entries.every(e=>
        e && typeof e.call_ref==='string' && !!e.call_ref &&
        typeof e.tool==='string' && !!e.tool &&
        ['CLAIMED','SUCCEEDED','DENIED'].includes(e.state)));
}
/** A selected project may not inherit other projects' quarantine titles.
 * Check parent-run ownership from the backend, in bounded 5-run batches. */
async function scopedQuarantine(
  api:ApiAdapter,runId:string|null,projectId:string|null,
):Promise<{tasks:TaskResponse[];truncated:boolean}>{
  if(runId && projectId){
    const run=await api.getRun(runId);
    if(!run || run.id!==runId || run.project_id!==projectId)
      throw new Error('Selected recovery run belongs to another project');
  }
  const items=await api.listRecoveryQuarantine(runId??undefined);
  if(!Array.isArray(items)||items.length>200||items.some(t=>
    !t || typeof t.id!=='string' || !t.id ||
    typeof t.workflow_run_id!=='string' || !t.workflow_run_id ||
    t.status!=='blocked'))
    throw new Error('Invalid server recovery catalog');
  const candidates=items.filter(t=>!runId || t.workflow_run_id===runId);
  // An admin endpoint without a cursor cannot prove completeness when its
  // maximum 200-row result is saturated, even after client project filtering.
  const truncated=items.length===200;
  if(!projectId||runId)return {tasks:candidates,truncated};
  const parents=[...new Set(candidates.map(t=>t.workflow_run_id))];
  const allowed=new Set<string>();
  for(let i=0;i<parents.length;i+=5){
    const ids=parents.slice(i,i+5);
    const runs=await Promise.all(ids.map(id=>api.getRun(id)));
    runs.forEach((run,index)=>{
      if(!run || run.id!==ids[index] || typeof run.project_id!=='string')
        throw new Error('Invalid parent run in recovery catalog');
      if(run.project_id===projectId)allowed.add(run.id);
    });
  }
  return {tasks:candidates.filter(t=>allowed.has(t.workflow_run_id)),truncated};
}

/** React remount invalidates even A -> B -> A and equal-ID API adapter swaps. */
export default function RecoverySection({adapter}:{adapter?:ApiAdapter}){
  const sharedAdapter=useMvpStore(s=>s.api);
  const api=adapter??sharedAdapter;
  const projectId=useMvpStore(s=>s.projectId);
  const runId=useMvpStore(s=>s.runId);
  const identity=useRef({api,revision:0});
  if(identity.current.api!==api){
    identity.current={api,revision:identity.current.revision+1};
  }
  return <RecoveryConsole
    key={JSON.stringify([identity.current.revision,projectId,runId])}
    api={api} runId={runId} projectId={projectId}/>;
}

type DetailProof={
  revision:number;
  saved:ReconciliationResponse|null;
  ledger:RecoveryLedgerReport|null;
  error:string|null;
  ledgerWarning:string|null;
  readable:boolean;
};
function RecoveryConsole({api,runId,projectId}:{
  api:ApiAdapter;runId:string|null;projectId:string|null;
}){
  const taskId=useMvpStore(s=>s.taskId);
  const selectTask=useMvpStore(s=>s.selectTask);
  const setSection=useMvpStore(s=>s.setSection);
  const [catalog,setCatalog]=useState<{
    refresh:number;tasks:TaskResponse[];truncated:boolean;
  }|null>(null);
  const [loading,setLoading]=useState(true);
  const [listError,setListError]=useState<string|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [read,setRead]=useState<DetailProof|null>(null);
  const [decision,setDecision]=useState<ReconciliationDecision>('UNKNOWN');
  const [evidenceRef,setEvidenceRef]=useState('');
  const [digest,setDigest]=useState('');
  const [reviewed,setReviewed]=useState(false);
  const [submitting,setSubmitting]=useState(false);
  const [submitError,setSubmitError]=useState<string|null>(null);
  const [mutationWarning,setMutationWarning]=useState<string|null>(null);
  const [lockRevision,updateLocks]=useState(0);
  const locks=useRef(recoveryLocks(api));
  const alive=useRef(true);
  useEffect(()=>{
    alive.current=true;
    return ()=>{alive.current=false;};
  },[]);
  const selectionRef=useRef({selectedId,taskId,refresh,revision:0});
  const previous=selectionRef.current;
  if(previous.selectedId!==selectedId||previous.taskId!==taskId||
     previous.refresh!==refresh){
    selectionRef.current={selectedId,taskId,refresh,revision:previous.revision+1};
  }
  const selection=selectionRef.current;
  const isCurrent=(scope:typeof selection)=>alive.current &&
    selectionRef.current.revision===scope.revision &&
    selectionRef.current.selectedId===scope.selectedId &&
    selectionRef.current.taskId===scope.taskId &&
    selectionRef.current.refresh===scope.refresh;

  useEffect(()=>{
    let active=true;
    setLoading(true);
    setCatalog(null);
    setListError(null);
    setSelectedId(null);
    void scopedQuarantine(api,runId,projectId).then(result=>{
      if(active){setCatalog({refresh,...result});setListError(null);}
    },(err:unknown)=>{
      if(active){setCatalog(null);setListError(detail(err));}
    }).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[api,runId,projectId,refresh]);

  const visibleTasks=catalog?.refresh===refresh?catalog.tasks:[];
  const selected=visibleTasks.find(t=>t.id===selectedId &&
    (!taskId||taskId===t.id));
  useEffect(()=>{
    if(taskId && visibleTasks.some(t=>t.id===taskId))setSelectedId(taskId);
  },[taskId,catalog]); // eslint-disable-line react-hooks/exhaustive-deps

  // Only evidence for this exact selection generation can enter the form.
  const detailRead=selected && read?.revision===selection.revision?read:null;
  const safeSaved=detailRead && detailRead.saved?.task_id===selected?.id?
    detailRead.saved:null;
  const safeLedger=detailRead && detailRead.ledger?.task_id===selected?.id?
    detailRead.ledger:null;
  const loadingDetail=!!selected && !detailRead;
  const detailError=detailRead?.error??null;
  const ledgerWarning=detailRead?.ledgerWarning??null;

  useEffect(()=>{
    if(!selected)return;
    let active=true;
    const proof={...selectionRef.current};
    setRead(null);
    setDecision('UNKNOWN');
    setEvidenceRef('');
    setDigest('');
    setReviewed(false);
    setSubmitError(null);
    setMutationWarning(null);
    setSubmitting(false);
    void Promise.allSettled([
      api.getRecoveryReconciliation(selected.id),
      api.getRecoveryLedger(selected.id),
    ]).then(([decisionResult,ledgerResult])=>{
      if(!active||!isCurrent(proof))return;
      let saved:ReconciliationResponse|null=null;
      let readable=false;
      let error:string|null=null;
      let ledger:RecoveryLedgerReport|null=null;
      let ledgerIssue:string|null=null;
      if(decisionResult.status==='fulfilled'){
        if(validDecision(decisionResult.value,selected.id)){
          saved=decisionResult.value;
          readable=true;
          // A locked uncertain POST can only be resolved by a verified,
          // persisted server read; a 404 cannot prove it wasn't committed.
          const pending=locks.current.get(selected.id);
          if(pending && decisionResult.value.decision===pending.decision &&
             decisionResult.value.evidence_ref===pending.evidence_ref &&
             decisionResult.value.evidence_sha256===pending.evidence_sha256){
            locks.current.delete(selected.id);
            persistRecoveryLocks(locks.current);
            updateLocks(n=>n+1);
          }
        }else error='Сервер вернул неподтверждённое решение другой задачи.';
      }else if(decisionResult.reason instanceof ProblemDetailsError &&
          decisionResult.reason.status===404){
        readable=true;
      }else error=detail(decisionResult.reason);
      if(ledgerResult.status==='fulfilled'){
        if(validLedger(ledgerResult.value,selected.id))ledger=ledgerResult.value;
        else ledgerIssue='Tool Ledger содержит неверифицированные записи.';
      }else ledgerIssue=detail(ledgerResult.reason);
      setRead({revision:proof.revision,saved,ledger,error,
        ledgerWarning:ledgerIssue,readable});
    });
    return ()=>{active=false;};
  },[api,selected?.id,selection.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const confirmed=safeSaved?.decision==='CONFIRMED_SIDE_EFFECT' ||
    safeSaved?.decision==='CONFIRMED_NO_SIDE_EFFECT';
  const hasAmbiguousCalls=safeLedger?.attempts.some(attempt=>
    attempt.entries.some(entry=>entry.state==='CLAIMED'))??false;
  // lockRevision triggers a re-render after an abandoned POST, including
  // when it settled under another selected task.
  void lockRevision;
  const locked=!!selected && locks.current.has(selected.id);
  const canSubmit=!!selected && !!detailRead?.readable && !detailError &&
    !submitting && !locked && !confirmed && reviewed &&
    validEvidenceRef(evidenceRef.trim()) && DIGEST.test(digest.trim()) &&
    (decision==='UNKNOWN'||!!safeLedger);

  async function attest(event:FormEvent){
    event.preventDefault();
    if(!selected||!canSubmit||locks.current.has(selected.id))return;
    const capture={...selectionRef.current};
    const id=selected.id;
    const request={
      decision,evidence_ref:evidenceRef.trim(),evidence_sha256:digest.trim(),
    };
    locks.current.set(id,{...request,state:'posting'});
    persistRecoveryLocks(locks.current);
    updateLocks(n=>n+1);
    setSubmitting(true);
    setSubmitError(null);
    setMutationWarning(null);
    try{
      const result=await api.attestRecovery(id,request);
      if(!validDecision(result,id) || result.decision!==request.decision ||
         result.evidence_ref!==request.evidence_ref ||
         result.evidence_sha256!==request.evidence_sha256){
        locks.current.set(id,{...request,state:'uncertain'});
        persistRecoveryLocks(locks.current);
        if(isCurrent(capture))setMutationWarning(
          'Сервер вернул другое решение. Не отправляйте POST повторно: проверьте серверную запись.');
        return;
      }
      if(!isCurrent(capture)){
        locks.current.set(id,{...request,state:'settled'});
        persistRecoveryLocks(locks.current);
        return;
      }
      locks.current.delete(id);
      persistRecoveryLocks(locks.current);
      setRead(current=>current?.revision===capture.revision?
        {...current,saved:result,readable:true}:current);
      setReviewed(false);
    }catch(err){
      locks.current.set(id,{...request,state:'uncertain'});
      persistRecoveryLocks(locks.current);
      if(isCurrent(capture)){
        setSubmitError(detail(err));
        setMutationWarning('Исход POST неизвестен. Автоматический повтор запрещён; '+
          'проверьте серверную запись и доказательства.');
      }
    }finally{
      if(alive.current)updateLocks(n=>n+1);
      if(isCurrent(capture))setSubmitting(false);
    }
  }
  return (
    <div>
      <PageHeader
        title="Аварийное восстановление"
        subtitle="Административная проверка прерванных задач. Ни одно решение не запускает агента повторно."
        actions={
          <button type="button" disabled={submitting}
            onClick={() => setRefresh((n) => n + 1)}
            data-testid="recovery-refresh" style={buttonStyle}>Обновить</button>
        }
      />
      <p role="note" style={{ color: '#8b4a12', background: '#fff5e9',
        border: '1px solid #e3c5a1', borderRadius: 8, padding: 12, fontSize: 13 }}>
        <strong>Карантин безопасен по умолчанию.</strong> Даже решение «побочное действие
        отсутствует» не снимает блокировку. Создание новой задачи допускается
        только после отдельной проверки оператором.
      </p>
      {runId ? (
        <p data-testid="recovery-run-scope" role="status" style={{ fontSize: 13 }}>
          Только карантинные задачи запуска <code>{runId}</code>.
          {' '}<button type="button" onClick={() => setSection('runs')}>Назад к запуску</button>
        </p>
      ) : (
        <p data-testid="recovery-global-scope" role="status" style={{ fontSize: 13 }}>
          {projectId ?
            'Карантин только проекта '+projectId+'. Принадлежность каждого запуска проверена сервером.' :
            'Общий административный карантин. Выберите запуск в разделе «Запуски», чтобы ограничить список.'}
        </p>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(320px, 2fr)',
        gap: 16, alignItems: 'start' }}>
        <Card title="Задачи в карантине">
          {loading && <p role="status">Проверка карантина и принадлежности запуска…</p>}
          {listError && <p role="alert">{sanitizeTaskDisplayText(listError)}</p>}
          {!loading && !listError && catalog?.truncated &&
            <p role="alert" data-testid="recovery-catalog-truncated">
              Сервер вернул первые 200 карантинных записей. Это неполный срез:
              отсутствие нужной задачи не означает, что её нет.
              Откройте конкретный запуск для серверной фильтрации.
            </p>}
          {!loading && catalog?.refresh===refresh && !catalog.truncated &&
            !listError && visibleTasks.length === 0 &&
            <p>{runId ? 'В выбранном запуске карантинных задач нет.' : 'Карантинных задач нет.'}</p>}
          {visibleTasks.map((task) => (
            <button key={task.id} type="button" disabled={submitting}
              onClick={() => {
              selectTask(task.id);
              setSelectedId(task.id);
            }}
              data-testid={`recovery-task-${task.id}`}
              aria-pressed={selectedId === task.id}
              style={{ ...buttonStyle, width: '100%', textAlign: 'left', marginBottom: 8,
                background: selectedId === task.id ? '#edf4ff' : '#fff' }}>
              <strong>{sanitizeTaskDisplayText(task.title)}</strong>
              <span style={{ display: 'block', margin: '5px 0' }}>
                <StatusBadge status={task.status} />
              </span>
              <span style={{ overflowWrap: 'anywhere', fontSize: 11 }}>{task.id}</span>
            </button>
          ))}
        </Card>
        <Card title="Проверка задачи">
          {!selected && <p>Выберите карантинную задачу слева.</p>}
          {selected && <>
            <h3 style={{ fontSize: 15, marginTop: 0 }}>{sanitizeTaskDisplayText(selected.title)}</h3>
            <p style={{ fontSize: 12, overflowWrap: 'anywhere' }}>ID: {selected.id}</p>
            {loadingDetail && <p role="status">Проверка серверного решения и Tool Ledger…</p>}
            {detailError && <p role="alert">{sanitizeTaskDisplayText(detailError)}</p>}
            {mutationWarning && <p role="alert" data-testid="recovery-uncertain">
              {sanitizeTaskDisplayText(mutationWarning)}
            </p>}
            {locked && <p role="alert" data-testid="recovery-post-locked">
              POST уже отправлялся. Повтор запрещён до проверки сохранённого серверного решения.
            </p>}
            {!!detailRead && safeSaved && (
              <p data-testid="recovery-decision">
                Последнее решение: <strong>{safeSaved.decision}</strong>
                {' · '}оператор {sanitizeTaskDisplayText(safeSaved.operator_subject)}
              </p>
            )}
            {!!detailRead && (
              <>
                <h4 style={{ marginBottom: 6 }}>Tool Ledger (только чтение)</h4>
                {ledgerWarning && <p role="alert">
                  Журнал недоступен: {sanitizeTaskDisplayText(ledgerWarning)}. Отсутствие данных не
                  доказывает безопасность повторного исполнения.
                </p>}
                {safeLedger && safeLedger.attempts.map((attempt) => (
                  <div key={attempt.attempt_id} style={{ fontSize: 12, marginBottom: 10 }}>
                    <strong>Попытка {sanitizeTaskDisplayText(attempt.attempt_id)}</strong>
                    {attempt.record_status === 'NO_RECORDS' ?
                      <p>Нет записей. Исход побочных действий неизвестен.</p> :
                      <ul>
                        {attempt.entries.map((entry) => (
                          <li key={entry.call_ref}>
                            {sanitizeTaskDisplayText(entry.tool)} — <StatusBadge status={entry.state}
                              tone={entry.state === 'CLAIMED' ? 'warn' : undefined} />
                            {' '}({sanitizeTaskDisplayText(entry.call_ref)})
                          </li>
                        ))}
                      </ul>}
                  </div>
                ))}
                {hasAmbiguousCalls && <p role="alert" style={{ color: '#a3271c' }}>
                  Есть вызовы CLAIMED с неизвестным исходом. Сопоставьте
                  внешние артефакты и доказательства перед подтверждением.
                </p>}
                {confirmed ? (
                  <p role="status">Решение подтверждено и неизменяемо. Задача остаётся blocked.</p>
                ) : (
                  <form onSubmit={attest}>
                    <h4>Зафиксировать результат сверки</h4>
                    <label style={fieldStyle}>Решение
                      <select aria-label="Решение" value={decision}
                        onChange={(e) => { setDecision(e.target.value as ReconciliationDecision); setReviewed(false); }}
                        style={inputStyle}>
                        {DECISIONS.map((item) => <option key={item.value} value={item.value}>
                          {item.label}
                        </option>)}
                      </select>
                    </label>
                    <label style={fieldStyle}>Идентификатор доказательства
                      <input aria-label="Идентификатор доказательства" required
                        value={evidenceRef} onChange={(e) => setEvidenceRef(e.target.value)}
                        placeholder="qa/incident-123" style={inputStyle} />
                    </label>
                    <label style={fieldStyle}>SHA-256 доказательства (64 символа)
                      <input aria-label="SHA-256 доказательства" required
                        value={digest} onChange={(e) => setDigest(e.target.value)}
                        maxLength={64} spellCheck={false} style={inputStyle} />
                    </label>
                    {decision !== 'UNKNOWN' && !safeLedger &&
                      <p role="alert">Для подтверждения необходимо просмотреть доступный Tool Ledger.
                        Пока можно сохранить только UNKNOWN.</p>}
                    <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                      margin: '12px 0', fontSize: 12 }}>
                      <input type="checkbox" checked={reviewed}
                        onChange={(e) => setReviewed(e.target.checked)} />
                      Я проверил доказательства и понимаю, что это действие
                      не перезапускает задачу.
                    </label>
                    {submitError && <p role="alert">{sanitizeTaskDisplayText(submitError)}</p>}
                    <button type="submit" disabled={!canSubmit}
                      data-testid="recovery-attest" style={buttonStyle}>
                      {submitting ? 'Сохранение…' : 'Зафиксировать решение'}
                    </button>
                  </form>
                )}
              </>
            )}
          </>}
        </Card>
      </div>
    </div>
  );
}

const buttonStyle={
  padding:'8px 12px',borderRadius:6,cursor:'pointer',
  border:'1px solid #b6c5d5',color:'#173858',
};
const fieldStyle={display:'block',marginBottom:12,fontSize:12};
const inputStyle={
  display:'block',padding:'8px 10px',width:'100%',
  boxSizing:'border-box' as const,marginTop:4,
  borderRadius:6,border:'1px solid #c8ced6',
};
