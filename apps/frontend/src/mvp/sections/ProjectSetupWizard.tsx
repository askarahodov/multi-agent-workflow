/** Guided first-use setup. Every write is performed by the existing backend API.
 * No paid provider request, dispatcher activation or silent agent registration.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useMvpStore } from '../../mvp/mvpStore';
import { ProblemDetailsError } from '../../api/client';
import type { ProjectResponse, WorkspaceResponse, AgentDefinitionRef, ModelProfileRef, ToolPolicyRef } from '../../api/types';
import { Button, Card, Field, Input, Select, Textarea } from '../../components';
import { PageHeader } from '../../patterns';

const STEPS = ['Проект', 'Рабочее пространство', 'Агенты и модели', 'Проверка'] as const;
type Catalog = { agents: AgentDefinitionRef[]; models: ModelProfileRef[]; tools: ToolPolicyRef[] };

// Error documents can contain provider messages, request URLs or credentials.
// Use only the trusted HTTP status for user-facing diagnostics.
function mutationError(error: unknown, resource: 'проект' | 'рабочее пространство'): string {
  const operation = resource === 'проект' ? 'Создать проект' : 'Создать рабочее пространство';
  if (error instanceof ProblemDetailsError) {
    if (error.status === 409) return `${operation} не удалось: запись с таким именем уже существует.`;
    if (error.status === 401 || error.status === 403) return `${operation} не удалось: недостаточно прав. Проверьте авторизацию.`;
    if (error.status === 400 || error.status === 422) return `${operation} не удалось: некорректные данные. Проверьте обязательные поля.`;
    if (error.status >= 500) return `${operation} не удалось: orchestration-server вернул HTTP ${error.status}. Проверьте состояние сервиса и его журнал, затем повторите попытку.`;
    return `${operation} не удалось (HTTP ${error.status}).`;
  }
  return `${operation} не удалось. Проверьте соединение с orchestration-server.`;
}


export default function ProjectSetupWizard() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const selectProject = useMvpStore((s) => s.selectProject);
  const setSection = useMvpStore((s) => s.setSection);
  const [step, setStep] = useState(0);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [projectName, setProjectName] = useState('');
  const [description, setDescription] = useState('');
  const [workspaceName, setWorkspaceName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setCatalogError(null);
    // Project CRUD belongs to orchestration, while profiles belong to agent-management.
    // One unhealthy subsystem must not hide the other or prevent project creation.
    const [projectsResult, catalogResult] = await Promise.allSettled([
      api.listProjects(),
      Promise.all([
        api.listAgentDefinitions(),
        api.listModelProfiles(),
        api.listToolPolicies(),
      ]),
    ]);
    if (projectsResult.status === 'fulfilled') {
      setProjects(projectsResult.value);
    } else {
      setError('Не удалось загрузить список проектов. Проверьте orchestration-server и повторите загрузку. Создать новый проект всё ещё можно.');
    }
    if (catalogResult.status === 'fulfilled') {
      const [agents, models, tools] = catalogResult.value;
      setCatalog({ agents: agents.items, models: models.items, tools: tools.items });
    } else {
      setCatalog(null);
      setCatalogError('Не удалось загрузить модели, агентов или политики инструментов из agent-management. Создание проекта не зависит от этих справочников. Повторите загрузку после восстановления сервиса.');
    }
    setLoading(false);
  }, [api]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    let active = true;
    if (!projectId) { setWorkspaces([]); return; }
    api.listWorkspaces(projectId).then((items) => {
      if (active) setWorkspaces(items.filter((ws) => ws.project_id === projectId));
    }).catch((reason: unknown) => {
      if (active) setError('Не удалось загрузить рабочие пространства из orchestration-server. Проверьте сервис и повторите загрузку.');
    });
    return () => { active = false; };
  }, [api, projectId]);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!projectName.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({ name: projectName.trim(), description: description.trim() || undefined });
      selectProject(project.id);
      setProjects((items) => [...items, project]);
      setStep(1);
    } catch (reason) {
      setError(mutationError(reason, 'проект'));
    } finally { setBusy(false); }
  }

  async function createWorkspace(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !workspaceName.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const workspace = await api.createWorkspace({ project_id: projectId, name: workspaceName.trim() });
      setWorkspaces((items) => [...items, workspace]);
      setWorkspaceName('');
      setStep(2);
    } catch (reason) {
      setError(mutationError(reason, 'рабочее пространство'));
    } finally { setBusy(false); }
  }

  const project = projects.find((p) => p.id === projectId);
  const hasAgents = (catalog?.agents.length ?? 0) > 0;
  const hasModels = (catalog?.models.length ?? 0) > 0;
  const hasTools = (catalog?.tools.length ?? 0) > 0;
  const configured = !!project && workspaces.length > 0 && hasAgents && hasModels && hasTools;

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <PageHeader title="Настройка проекта" subtitle="Четыре шага от проекта до проверки готовности. Настройка не запускает платную модель." />
      <nav aria-label="Шаги настройки" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
        {STEPS.map((label, index) => (
          <Button key={label} variant={step === index ? 'primary' : 'secondary'}
            aria-current={step === index ? 'step' : undefined}
            onClick={() => { setError(null); setStep(index); }}>
            {index + 1}. {label}
          </Button>
        ))}
      </nav>
      {loading ? <p role="status">Загрузка сохранённых данных…</p> : null}
      {error ? <p role="alert" style={{ color: 'var(--color-error)' }}>{error}</p> : null}
      {step === 0 ? (
        <Card title="1. Выберите или создайте проект">
          <p>Проект объединяет рабочее пространство, задачи и запуски. Выбор сохранённого проекта не создаёт дубль.</p>
          <Field label="Существующий проект">
            {({ id, ...aria }) => <Select id={id} data-testid="setup-project-select" value={projectId ?? ''}
              onChange={(event) => selectProject(event.target.value || null)} {...aria}>
              <option value="">Выберите проект</option>
              {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </Select>}
          </Field>
          <form onSubmit={createProject}>
            <Field label="Название нового проекта" required>
              {({ id, ...aria }) => <Input id={id} data-testid="setup-project-name" value={projectName}
                onChange={(event) => setProjectName(event.target.value)} maxLength={255} required {...aria} />}
            </Field>
            <Field label="Что планируется разработать?">
              {({ id, ...aria }) => <Textarea id={id} value={description}
                onChange={(event) => setDescription(event.target.value)} {...aria} />}
            </Field>
            <Button type="submit" disabled={!projectName.trim() || busy}>Создать проект</Button>
          </form>
          <p><Button variant="secondary" disabled={!projectId} onClick={() => setStep(1)}>Продолжить с выбранным проектом</Button></p>
        </Card>
      ) : null}
      {step === 1 ? (
        <Card title="2. Рабочее пространство">
          {!project ? <p role="status">Сначала выберите проект в шаге 1.</p> : (
            <>
              <p>Рабочее пространство — отдельная запись сервера для выбранного проекта. Произвольный путь файловой системы здесь не запрашивается.</p>
              {workspaces.length ? <ul>{workspaces.map((ws) => <li key={ws.id}>{ws.name}</li>)}</ul>
                : <p>У проекта ещё нет рабочего пространства.</p>}
              <form onSubmit={createWorkspace}>
                <Field label="Название пространства" required>
                  {({ id, ...aria }) => <Input id={id} data-testid="setup-workspace-name" value={workspaceName}
                    onChange={(event) => setWorkspaceName(event.target.value)} maxLength={255} required {...aria} />}
                </Field>
                <Button disabled={busy || !workspaceName.trim()} type="submit">Создать пространство</Button>
              </form>
              <p><Button variant="secondary" disabled={!workspaces.length} onClick={() => setStep(2)}>Продолжить</Button></p>
            </>
          )}
        </Card>
      ) : null}
      {step === 2 ? (
        <Card title="3. Модели и агенты">
          <p>Здесь отображаются реальные серверные справочники. Профили, ключи OpenRouter и назначение моделей управляются в «Настройках»; сами по себе определения агентов не означают работающий worker.</p>
          {catalogError ? <p role="alert" data-testid="setup-catalog-error">{catalogError}</p> : null}
          <ul>
            <li>Определения агентов: {catalog?.agents.length ?? 0}</li>
            <li>Профили моделей: {catalog?.models.length ?? 0}</li>
            <li>Политики инструментов: {catalog?.tools.length ?? 0}</li>
          </ul>
          {!hasAgents || !hasModels || !hasTools ? <p role="status">Для конфигурации агента нужны определение, модель и политика инструментов.</p> : null}
          <Button variant="secondary" onClick={() => setSection('settings')}>Открыть настройки AI</Button>{' '}
          <Button variant="secondary" disabled={!hasAgents || !hasModels || !hasTools} onClick={() => setStep(3)}>Проверить готовность</Button>
          <p><Button variant="ghost" onClick={() => void refresh()}>Обновить справочники</Button></p>
        </Card>
      ) : null}
      {step === 3 ? (
        <Card title="4. Проверка перед запуском">
          <ul data-testid="setup-checklist">
            <li>{project ? '✓' : '✕'} Проект: {project?.name ?? 'не выбран'}</li>
            <li>{workspaces.length ? '✓' : '✕'} Рабочее пространство: {workspaces.length ? 'создано' : 'отсутствует'}</li>
            <li>{hasAgents ? '✓' : '✕'} Определения агентов</li>
            <li>{hasModels ? '✓' : '✕'} Профили моделей</li>
            <li>{hasTools ? '✓' : '✕'} Политики инструментов</li>
          </ul>
          <p>Это проверка сохранённых настроек, <strong>не</strong> проверка активности native worker, OpenRouter, независимого QA или Git-доступа. Базовый dev Compose не выполняет задачи автономно без отдельно разрешённого worker.</p>
          <Button disabled={!configured} onClick={() => setSection('runs')}>Перейти к настройке запуска</Button>{' '}
          <Button variant="secondary" onClick={() => setSection('editor')}>Открыть редактор графа</Button>
          {!configured ? <p role="status">Не все необходимые настройки сохранены. Вернитесь к соответствующему шагу.</p> : null}
        </Card>
      ) : null}
    </div>
  );
}
