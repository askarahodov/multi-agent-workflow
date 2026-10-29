/**
 * Project dashboard layout (ADR-110 §3.6).
 *
 * Design-system implementation of the "Проект" section: projects + workspaces
 * with the shared token-driven components, an accessible two-column split and
 * consistent loading/error/empty handling. Data comes from the orchestration
 * server project domain via the shared `ApiAdapter`.
 */

import { type FormEvent, useEffect, useState } from 'react';

import type { WorkspaceResponse } from '../api/types';
import { useMvpStore } from '../mvp/mvpStore';
import { useAsync } from '../mvp/useAsync';
import { formatDate } from '../mvp/ui';
import { Button, Card, Field, Input, StatusBadge, Textarea, useToast } from '../components';
import { AsyncBoundary, PageHeader } from '../patterns';
import { Split } from '../components/Stack';

export default function ProjectDashboard() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const selectProject = useMvpStore((s) => s.selectProject);
  const { notify } = useToast();

  const projects = useAsync(() => api.listProjects());
  const { reload: reloadProjects } = projects;
  const workspaces = useAsync<WorkspaceResponse[]>(() =>
    api.listWorkspaces(useMvpStore.getState().projectId ?? undefined),
  );
  const reloadWorkspaces = workspaces.reload;

  useEffect(() => {
    reloadWorkspaces();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const refreshAll = () => {
    reloadProjects();
    reloadWorkspaces();
  };

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      selectProject(created.id);
      setName('');
      setDescription('');
      refreshAll();
      notify({ title: 'Проект создан', message: created.name, tone: 'success' });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setCreateError(message);
      notify({ title: 'Не удалось создать проект', message, tone: 'error' });
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Проект"
        subtitle="Проекты и рабочие пространства платформы."
        breadcrumbs={[{ label: 'Платформа' }, { label: 'Проект' }]}
      />

      <Split>
        <div>
          <Card title="Список проектов">
            <AsyncBoundary
              loading={projects.loading}
              error={projects.error}
              isEmpty={projects.data?.length === 0}
              onRetry={reloadProjects}
              emptyTitle="Нет проектов"
              emptyBody="Создайте первый проект в форме ниже."
              skeletonLines={4}
            >
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 'var(--space-2)' }}>
                {projects.data?.map((project) => {
                  const active = project.id === projectId;
                  return (
                    <li key={project.id}>
                      <button
                        type="button"
                        data-testid={`project-item-${project.id}`}
                        aria-current={active ? 'true' : undefined}
                        onClick={() => selectProject(project.id)}
                        style={{
                          display: 'block',
                          width: '100%',
                          textAlign: 'start',
                          padding: 'var(--space-3)',
                          border: `1px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
                          borderRadius: 'var(--radius-lg)',
                          background: active ? 'var(--color-primary-weak)' : 'var(--color-surface)',
                          cursor: 'pointer',
                        }}
                      >
                        <span
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            gap: 'var(--space-2)',
                          }}
                        >
                          <strong>{project.name}</strong>
                          {active ? <StatusBadge status="selected" tone="accent" label="Активен" /> : null}
                        </span>
                        {project.description ? (
                          <span
                            style={{
                              display: 'block',
                              margin: '4px 0',
                              color: 'var(--color-text-muted)',
                              fontSize: 'var(--font-size-md)',
                            }}
                          >
                            {project.description}
                          </span>
                        ) : null}
                        <span
                          style={{
                            display: 'block',
                            marginBlockStart: '2px',
                            color: 'var(--color-text-subtle)',
                            fontSize: 'var(--font-size-sm)',
                          }}
                        >
                          обновлён {formatDate(project.updated_at)} · ревизия {project.version}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </AsyncBoundary>
          </Card>

          <div style={{ marginBlockStart: 'var(--space-4)' }}>
            <Card title="Создать проект">
              <form onSubmit={onCreate} noValidate>
                <Field label="Название" required>
                  {({ id, ...aria }) => (
                    <Input
                      id={id}
                      data-testid="project-name-input"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Например: Маркетинг-агентство"
                      {...aria}
                    />
                  )}
                </Field>
                <Field label="Описание">
                  {({ id, ...aria }) => (
                    <Textarea
                      id={id}
                      data-testid="project-description-input"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={2}
                      {...aria}
                    />
                  )}
                </Field>
                {createError ? (
                  <p role="alert" style={{ color: 'var(--color-error)', fontSize: 'var(--font-size-md)' }}>
                    {createError}
                  </p>
                ) : null}
                <Button
                  type="submit"
                  data-testid="project-create-button"
                  disabled={creating || !name.trim()}
                >
                  {creating ? 'Создание…' : 'Создать проект'}
                </Button>
              </form>
            </Card>
          </div>
        </div>

        <div>
          <Card title="Рабочие пространства текущего проекта">
            {!projectId ? (
              <AsyncBoundary loading={false} isEmpty emptyTitle="Проект не выбран" emptyBody="Выберите проект слева.">
                <span />
              </AsyncBoundary>
            ) : (
              <AsyncBoundary
                loading={workspaces.loading}
                error={workspaces.error}
                isEmpty={workspaces.data?.length === 0}
                onRetry={reloadWorkspaces}
                emptyTitle="Рабочие пространства не найдены"
                skeletonLines={3}
              >
                <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 'var(--space-2)' }}>
                  {workspaces.data?.map((ws) => (
                    <li
                      key={ws.id}
                      style={{
                        padding: 'var(--space-3)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 'var(--radius-lg)',
                      }}
                    >
                      <strong>{ws.name}</strong>
                      <p style={{ margin: '4px 0 0', color: 'var(--color-text-subtle)', fontSize: 'var(--font-size-sm)' }}>
                        project_id {ws.project_id}
                        {ws.path ? ` · path ${ws.path}` : ''}
                      </p>
                    </li>
                  ))}
                </ul>
              </AsyncBoundary>
            )}
          </Card>
        </div>
      </Split>
    </div>
  );
}
