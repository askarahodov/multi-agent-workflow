/** Full design-time workflow path: open, save, validate, publish and run immutable snapshot. */
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { Button, Input, Select } from '../components';
import type { ApiAdapter, WorkflowDefinitionDTO, WorkflowVersionDTO } from '../api/types';
import { useMvpStore } from '../mvp/mvpStore';
import { validateWorkflowDocument, downloadWorkflow, importWorkflow } from './importExport';
import { compilePreview } from './publishedPreview';
import { useEditorStore } from './store';
import NodePalette from './NodePalette';
import GuidedTemplateBuilder from './GuidedTemplateBuilder';
import WorkflowCanvas from './WorkflowCanvas';
import PropertyPanel from './PropertyPanel';

export default function EditorWorkspace() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const selectRun = useMvpStore((s) => s.selectRun);
  const pendingPublishedLaunches = useMvpStore((s) => s.pendingPublishedLaunches);
  const setPendingPublishedLaunch = useMvpStore((s) => s.setPendingPublishedLaunch);
  const setSection = useMvpStore((s) => s.setSection);
  const definition = useEditorStore((s) => s.definition);
  const load = useEditorStore((s) => s.load);
  const reset = useEditorStore((s) => s.reset);
  const pastCount = useEditorStore((s) => s.past.length);
  const futureCount = useEditorStore((s) => s.future.length);
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const addEdge = useEditorStore((s) => s.addEdge);
  const updateMetadata = useEditorStore((s) => s.updateMetadata);
  const [catalog, setCatalog] = useState<WorkflowDefinitionDTO[]>([]);
  // The active project is a security and data-integrity boundary, not just a
  // catalog filter. Retain an unsaved document on context switches, but do not
  // silently rebind it or allow it to save/publish/launch under another project.
  const activeContext = useRef({api, projectId});
  activeContext.current = {api, projectId};
  const [documentContext, setDocumentContext] = useState<{api:ApiAdapter;projectId:string|null}>(
    () => ({api, projectId}));
  const [catalogContext, setCatalogContext] = useState<{api:ApiAdapter;projectId:string|null}|null>(null);
  const catalogGeneration = useRef(0);
  const operationGeneration = useRef(0);
  const sameContext = (context:{api:ApiAdapter;projectId:string|null}) =>
    activeContext.current.api===context.api && activeContext.current.projectId===context.projectId;
  const documentIsCurrent = documentContext.api===api && documentContext.projectId===projectId;
  const visibleCatalog = catalogContext?.api===api && catalogContext?.projectId===projectId ? catalog : [];
  const [record, setRecord] = useState<WorkflowDefinitionDTO | null>(null);
  const [published, setPublished] = useState<WorkflowVersionDTO | null>(null);
  const [versions, setVersions] = useState<WorkflowVersionDTO[]>([]);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [showErrors, setShowErrors] = useState(false);
  const [linkFrom, setLinkFrom] = useState('');
  const [linkTo, setLinkTo] = useState('');
  const uploadRef = useRef<HTMLInputElement>(null);
  const snapshot = useMemo(() => JSON.stringify(definition), [definition]);
  const dirty = saved === null ? (definition.nodes.length > 0 || definition.edges.length > 0 ||
    definition.metadata.name !== 'Untitled workflow') : snapshot !== saved;
  const structural = useMemo(() => validateWorkflowDocument(definition), [definition]);
  const preview = useMemo(() => compilePreview(definition), [definition]);
  const ready = structural.isValid && preview.errors.length === 0;
  const hasPublishedVersion = Boolean(published) && documentIsCurrent &&
    (!record?.project_id || record.project_id===projectId);
  // Invalidates in-flight operations on switch or unmount. They may have
  // committed remotely, but cannot overwrite the newly selected editor state.
  useEffect(() => {
    operationGeneration.current++;
    setBusy(false);
    setError('');
    return () => {operationGeneration.current++;};
  }, [api,projectId]);

  const refresh = useCallback(async () => {
    const scope={api,projectId};
    const generation=++catalogGeneration.current;
    const isCurrent=()=>generation===catalogGeneration.current &&
      activeContext.current.api===scope.api && activeContext.current.projectId===scope.projectId;
    const result: WorkflowDefinitionDTO[] = [];
    const cursors = new Set<string>();
    let after: string | undefined;
    for (let page = 0; page < 100; page++) {
      const batch = await api.listWorkflows({after,limit:100});
      if (!isCurrent()) return;
      result.push(...batch.items);
      if (!batch.next_cursor) {
        setCatalog(result.filter((item)=>!projectId || !item.project_id || item.project_id === projectId));
        setCatalogContext(scope);
        return;
      }
      if (cursors.has(batch.next_cursor)) throw new Error('Сервер повторяет курсор workflow');
      cursors.add(batch.next_cursor);
      after = batch.next_cursor;
    }
    throw new Error('Превышен предел страниц workflow');
  }, [api,projectId]);
  useEffect(() => {
    let active = true;
    void refresh().catch((cause:unknown) => {
      if (active && activeContext.current.api===api && activeContext.current.projectId===projectId)
        setError(cause instanceof Error ? cause.message : 'Не удалось получить workflow');
    });
    return () => { active = false; catalogGeneration.current++; };
  }, [refresh]);

  function confirmReplace(): boolean {
    return !dirty || window.confirm('Текущий несохранённый граф будет заменён. Продолжить?');
  }

  async function open(id: string) {
    if (busy || !id || !visibleCatalog.some(item=>item.id===id) || !confirmReplace()) return;
    const scope={api,projectId};
    const generation=++operationGeneration.current;
    const isCurrent=()=>generation===operationGeneration.current && sameContext(scope);
    setBusy(true); setError(''); setStatus('');
    try {
      const versionItems: WorkflowVersionDTO[] = [];
      const seen = new Set<string>();
      let after: string | undefined;
      for (let page = 0; page < 100; page++) {
        const batch = await api.listVersions(id,{after,limit:100});
        if (!isCurrent()) return;
        versionItems.push(...batch.items);
        if (!batch.next_cursor) break;
        if (seen.has(batch.next_cursor) || page === 99) throw new Error('Некорректная пагинация версий');
        seen.add(batch.next_cursor);
        after=batch.next_cursor;
      }
      const dto = await api.getWorkflow(id);
      if (!isCurrent()) return;
      if (dto.project_id && dto.project_id!==projectId)
        throw new Error('Workflow принадлежит другому проекту. Обновите список.');
      load(dto.definition);
      setDocumentContext(scope);
      setRecord(dto);
      setSaved(JSON.stringify(dto.definition));
      setVersions(versionItems);
      // Prefer the authoritative publication pointer, not a timestamp sort.
      setPublished(versionItems.find((v)=>v.id===dto.current_version_id) ??
        versionItems.sort((a,b)=>b.version_number-a.version_number)[0] ?? null);
      setStatus('Открыта серверная версия черновика. Изменения не затрагивают опубликованные версии.');
      setShowErrors(false);
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {if (isCurrent())setBusy(false);}
  }

  function newDraft() {
    if (busy || !confirmReplace()) return;
    operationGeneration.current++;
    reset();setDocumentContext({api,projectId});
    setSaved(null);setRecord(null);setPublished(null);setVersions([]);
    setStatus('Новый черновик — добавьте Start, Agent, automatic Gate и End.');
    setError('');setShowErrors(false);
  }

  async function saveDraft() {
    if (busy || !documentIsCurrent || !projectId) return;
    const scope={api,projectId};
    const generation=++operationGeneration.current;
    const isCurrent=()=>generation===operationGeneration.current && sameContext(scope);
    const submittedSnapshot=snapshot;
    setBusy(true);setError('');setStatus('');
    try {
      if (!definition.metadata.name.trim()) throw new Error('Укажите имя workflow');
      if (record?.project_id && record.project_id!==projectId)
        throw new Error('Нельзя изменить workflow другого проекта.');
      const dto = record
        ? await api.updateWorkflow(record.id, {
            expected_version:record.version,name:definition.metadata.name.trim(),
            description:definition.metadata.description,
            definition,
          })
        : await api.createWorkflow({
            project_id:projectId,
            name:definition.metadata.name.trim(),
            description:definition.metadata.description,
            definition,
          });
      if (!isCurrent()) return;
      setRecord(dto);
      // Local edits made during the HTTP request remain dirty and are not
      // claimed to have been included in this server revision.
      setSaved(submittedSnapshot);
      await refresh();
      if (isCurrent()) setStatus('Черновик сохранён на сервере. Для исполнения требуется публикация.');
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {if (isCurrent())setBusy(false);}
  }

  async function publish() {
    if (busy || !documentIsCurrent || !record || !projectId || dirty || !ready ||
        (record.project_id && record.project_id!==projectId)) {
      setShowErrors(true);
      setError('Перед публикацией выберите правильный проект, сохраните и исправьте граф.');
      return;
    }
    const scope={api,projectId};
    const generation=++operationGeneration.current;
    const isCurrent=()=>generation===operationGeneration.current && sameContext(scope);
    setBusy(true);setError('');setStatus('');
    try {
      const version = await api.saveVersion(record.id, {
        expected_version:record.version,
        definition_snapshot:definition,
        changelog:'Проверенный снимок редактора',
      });
      if (!isCurrent()) return;
      const dto = await api.getWorkflow(record.id);
      if (!isCurrent()) return;
      setRecord(dto);
      setSaved(JSON.stringify(dto.definition));
      setPublished(version);
      setVersions((items)=>[version,...items]);
      setStatus('Опубликована неизменяемая версия №' + version.version_number);
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {if (isCurrent())setBusy(false);}
  }

  async function run() {
    if (busy || !documentIsCurrent || !record || !published || !projectId ||
        (record.project_id && record.project_id!==projectId)) {
      setError('Для запуска нужен выбранный проект и актуальная опубликованная версия.');
      return;
    }
    const scope={api,projectId};
    const generation=++operationGeneration.current;
    const isCurrent=()=>generation===operationGeneration.current && sameContext(scope);
    const selection = [projectId, record.id, published.id].join('/');
    setBusy(true);setError('');
    try {
      // Ambiguous prior POST: retry its key to retrieve the committed result.
      // The backend still recomputes preflight if no receipt exists.
      if (!pendingPublishedLaunches[selection]) {
        const report = await api.preflightPublishedRun(record.id, published.id, projectId);
        if (!isCurrent()) return;
        if (!report.can_create_run) {
          setError('Серверный preflight заблокировал запуск: ' + report.checks
            .filter(item=>item.status==='block').map(item=>item.detail).join('; '));
          return;
        }
      }
      if (!isCurrent()) return;
      if (!window.confirm('Создать запуск опубликованной версии №' + published.version_number +
        '? Предварительная проверка НЕ подтверждает готовность live worker, модели, бюджет или QA. ' +
        'Включённый worker может выполнить платные AI-запросы. Текущий черновик в запуск не входит.')) return;
      if (!isCurrent()) return;
      let key = pendingPublishedLaunches[selection];
      if (!key) {
        const bytes = new Uint8Array(16);
        globalThis.crypto.getRandomValues(bytes);
        key = Array.from(bytes, byte=>byte.toString(16).padStart(2,'0')).join('');
        setPendingPublishedLaunch(selection, key);
      }
      const result = await api.launchPublishedRun(record.id,published.id,{
        project_id:projectId,name:published.definition_snapshot.metadata.name,
        idempotency_key:key,
      });
      // Confirmed success settles the idempotency key even if the UI switched.
      setPendingPublishedLaunch(selection, null);
      if (!isCurrent()) return;
      selectRun(result.id);
      setSection('runs');
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {if (isCurrent())setBusy(false);}
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file || !confirmReplace()) {if (uploadRef.current) uploadRef.current.value='';return;}
    setError('');
    try {
      const outcome = await importWorkflow(file);
      if (!outcome.ok || !outcome.workflow) {
        setShowErrors(true);
        setError(outcome.errors.map((e)=>e.path+': '+e.message).join('; '));
        return;
      }
      // Imported JSON is always a new draft, never an accidental overwrite.
      load(outcome.workflow);setDocumentContext({api,projectId});
      setRecord(null);setSaved(null);setPublished(null);setVersions([]);
      setStatus('JSON импортирован в новый несохранённый черновик.');
      setShowErrors(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {if (uploadRef.current) uploadRef.current.value='';}
  }

  function addConnection() {
    if (!linkFrom || !linkTo || linkFrom === linkTo ||
        !definition.nodes.some(n=>n.id===linkFrom) || !definition.nodes.some(n=>n.id===linkTo)) {
      setError('Выберите две разные существующие ноды для соединения.');
      return;
    }
    if (definition.edges.some(e=>e.source_node_id===linkFrom && e.target_node_id===linkTo)) {
      setError('Эта связь уже существует.');
      return;
    }
    addEdge(linkFrom, linkTo);
    setError(''); setStatus('Связь добавлена. Проверьте граф перед публикацией.');
  }

  function handleEditorKeyboard(event: KeyboardEvent<HTMLElement>) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const target=event.target;
    if (target instanceof HTMLElement &&
      (['INPUT','TEXTAREA','SELECT'].includes(target.tagName) || target.isContentEditable)) return;
    if (event.key.toLowerCase()==='z') {
      event.preventDefault();
      if (event.shiftKey) redo(); else undo();
    } else if (event.key.toLowerCase()==='y') {
      event.preventDefault(); redo();
    }
  }

  const validationErrors = [...structural.errors.map((e)=>e.path+': '+e.message), ...preview.errors];
  return <section style={{height:'100%',display:'flex',flexDirection:'column',minHeight:500}} aria-label="Редактор workflow" onKeyDown={handleEditorKeyboard}>
    <div style={{padding:12,display:'flex',gap:8,flexWrap:'wrap',alignItems:'center',borderBottom:'1px solid var(--color-border)'}}>
      <label htmlFor="editor-workflow-list">Открыть:</label>
      <Select id="editor-workflow-list" data-testid="editor-workflow-list" value={documentIsCurrent ? record?.id ?? '' : ''}
        disabled={busy} onChange={(e)=>{void open(e.target.value);}} style={{width:190,marginBottom:0}}>
        <option value="">Новый черновик</option>
        {visibleCatalog.map((dto)=><option key={dto.id} value={dto.id}>{dto.name}</option>)}
      </Select>
      <label htmlFor="editor-workflow-name">Название:</label>
      <Input id="editor-workflow-name" data-testid="editor-workflow-name"
        value={definition.metadata.name}
        onChange={(e)=>updateMetadata({name:e.target.value})} style={{width:180,marginBottom:0}}/>
      <Button variant="secondary" onClick={newDraft} disabled={busy}>Новый</Button>
      <Button variant="secondary" data-testid="editor-undo" disabled={busy||!pastCount} onClick={undo}
        title="Отменить действие (Ctrl/Cmd+Z)">Отменить</Button>
      <Button variant="secondary" data-testid="editor-redo" disabled={busy||!futureCount} onClick={redo}
        title="Повторить действие (Ctrl/Cmd+Shift+Z)">Повторить</Button>
      <Button variant="secondary" disabled={busy} onClick={()=>downloadWorkflow(definition)}>Экспорт JSON</Button>
      <Button variant="secondary" disabled={busy} onClick={()=>uploadRef.current?.click()}>Импорт JSON</Button>
      <input ref={uploadRef} type="file" accept=".json,application/json"
        aria-label="Выбрать JSON workflow" style={{display:'none'}} onChange={(e)=>{void upload(e);}}/>
      <Button data-testid="editor-validate" variant="secondary" onClick={()=>{
        setShowErrors(true);setStatus(ready?'Граф подходит для запуска (проверка браузера).':'Исправьте ошибки перед публикацией.');
      }}>Проверить</Button>
      <Button data-testid="editor-save" disabled={busy||!documentIsCurrent||!projectId} onClick={()=>{void saveDraft();}}>Сохранить черновик</Button>
      <Button data-testid="editor-publish" disabled={busy||!documentIsCurrent||!projectId||!record||dirty||!ready||
        Boolean(record?.project_id&&record.project_id!==projectId)}
        onClick={()=>{void publish();}}>Опубликовать версию</Button>
      <label htmlFor="editor-version-select">Версия:</label>
      <Select id="editor-version-select" data-testid="editor-version-select" value={published?.id ?? ''}
        disabled={busy||!versions.length} onChange={(event)=>{
          setPublished(versions.find((item)=>item.id===event.target.value) ?? null);
        }} style={{maxWidth:145,marginBottom:0}}>
        <option value="">Нет</option>
        {versions.map((item)=><option key={item.id} value={item.id}>№{item.version_number}</option>)}
      </Select>
      <Button data-testid="editor-run" disabled={busy||!projectId||!hasPublishedVersion}
        onClick={()=>{void run();}}>Запустить версию</Button>
    </div>
    <div aria-label="Создать связь без перетаскивания"
      style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap',padding:'8px 12px',borderBottom:'1px solid var(--color-border)'}}>
      <label htmlFor="editor-link-from">Связь от:</label>
      <Select id="editor-link-from" data-testid="editor-link-from" value={linkFrom}
        onChange={e=>setLinkFrom(e.target.value)} style={{maxWidth:190,marginBottom:0}}>
        <option value="">Нода-источник</option>
        {definition.nodes.map(n=><option key={n.id} value={n.id}>{n.label} ({n.type})</option>)}
      </Select>
      <label htmlFor="editor-link-to">к:</label>
      <Select id="editor-link-to" data-testid="editor-link-to" value={linkTo}
        onChange={e=>setLinkTo(e.target.value)} style={{maxWidth:190,marginBottom:0}}>
        <option value="">Нода-цель</option>
        {definition.nodes.map(n=><option key={n.id} value={n.id}>{n.label} ({n.type})</option>)}
      </Select>
      <Button variant="secondary" data-testid="editor-add-connection" disabled={busy||!linkFrom||!linkTo}
        onClick={addConnection}>Создать связь</Button>
      <span style={{fontSize:12}}>Ноды также можно соединять мышью. Ошибочные циклы и разрывы блокируют публикацию.</span>
    </div>
    <GuidedTemplateBuilder api={api} projectId={projectId} disabled={busy}
      onBuild={(document)=>{
        if(!confirmReplace())return;
        load(document);setDocumentContext({api,projectId});
        setRecord(null);setSaved(null);setPublished(null);setVersions([]);
        setError('');setShowErrors(false);
        setStatus('Граф собран из сохранённых серверных ссылок. Проверьте, затем сохраните и опубликуйте версию.');
      }}/>
    <div style={{padding:'6px 12px',fontSize:12}}>
      <strong>{dirty?'Есть несохранённые изменения':'Изменения сохранены'}</strong>
      {' · '}{record?'Версия черновика '+record.version:'Новый документ'}
      {' · '}{published?'Выбрана неизменяемая версия №'+published.version_number:'Не опубликовано'}
      {' · '}{projectId?'Проект выбран':'Выберите проект в разделе «Проект»'}
      {published && snapshot !== JSON.stringify(published.definition_snapshot) ?
        <p style={{margin:'4px 0',color:'#92400e'}} role="status">Внимание: запуск использует выбранную опубликованную версию №{published.version_number}, а не текущий черновик.</p>:null}
      <p style={{margin:'4px 0'}}>
        Выполняются только линейные Start → (Agent → automatic Contract Gate)+ → End.
        Настройки профиля агента сейчас записываются в provenance задач, но ещё не
        применяются native worker как права/лимиты модели (#254). Контроль контрактов,
        независимая QA и approval остаются за backend; никакого обхода проверок.
      </p>
      {!documentIsCurrent ? <p role="alert" data-testid="editor-project-mismatch">
        Проект переключён. Ранее открытый черновик сохранён в редакторе, но его нельзя
        сохранять, публиковать или запускать в другом проекте. Выберите «Новый»,
        импортируйте JSON или откройте workflow нового проекта. Несохранённые изменения
        сначала можно экспортировать в JSON.
      </p> : null}
      {error ? <p role="alert" style={{color:'#b91c1c'}}>{error}</p> : null}
      {status ? <p role="status">{status}</p> : null}
      {showErrors && validationErrors.length ? <div role="alert" data-testid="editor-errors">
        <strong>Ошибки графа ({validationErrors.length}):</strong>
        <ul>{validationErrors.slice(0,30).map((message,index)=><li key={index}>{message}</li>)}</ul>
      </div> : null}
    </div>
    <div style={{display:'flex',flex:1,minHeight:320,overflow:'hidden'}}>
      <NodePalette />
      <div style={{flex:1,position:'relative',minWidth:300}}><WorkflowCanvas /></div>
      <PropertyPanel api={api}/>
    </div>
  </section>;
}
