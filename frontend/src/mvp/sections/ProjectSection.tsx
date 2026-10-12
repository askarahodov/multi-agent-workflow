/**
 * MVP v1 — Project section.
 *
 * Lists projects and workspaces from the orchestration server (project domain),
 * lets the user create a project (a run requires `project_id`, so this is the
 * natural entry point), and selects the currently active project for the
 * board / runs filters. Two-column: projects on the left, that project's
 * workspaces on the right.
 */

import { type FormEvent, useEffect, useState } from 'react';

import type { WorkspaceResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

export default function ProjectSection() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const selectProject = useMvpStore((s) => s.selectProject);

  const projects = useAsync(() => api.listProjects());
  const { reload: reloadProjects } = projects;
  const workspaces = useAsync<WorkspaceResponse[]>(() =>
    api.listWorkspaces(useMvpStore.getState().projectId ?? undefined),
  );
  const reloadWorkspaces = workspaces.reload;

  // Refetch workspaces when the active project changes.
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
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Проект"
        subtitle="Проекты и рабочие пространства платформы (domain: orchestration-server /projects, /workspaces)."
      />

      <div
        style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}
      >
        {/* Left column: projects */}
        <div>
          <Card title="Список проектов">
            {projects.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
            {projects.error ? (
              <p style={{ color: '#a3271c' }}>Ошибка: {projects.error.message}</p>
            ) : null}
            {!projects.loading && !projects.error ? (
              projects.data!.length === 0 ? (
                <p style={{ color: '#5b6472' }}>Нет проектов.</p>
              ) : (
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {projects.data!.map((project) => (
                    <li
                      key={project.id}
                      style={{
                        padding: '10px 12px',
                        border: '1px solid #e2e6ea',
                        borderRadius: 8,
                        marginBottom: 8,
                        cursor: 'pointer',
                        background: project.id === projectId ? '#f2f6fc' : '#fff',
                        outline: project.id === projectId ? '1px solid #1c5fa8' : undefined,
                      }}
                      onClick={() => selectProject(project.id)}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <strong>{project.name}</strong>
                        {project.id === projectId ? (
                          <StatusBadge status="выбран" tone="accent" label="Активен" />
                        ) : null}
                      </div>
                      {project.description ? (
                        <p style={{ margin: '4px 0', color: '#5b6472', fontSize: 13 }}>
                          {project.description}
                        </p>
                      ) : null}
                      <p style={{ margin: '2px 0 0', color: '#9aa2af', fontSize: 12 }}>
                        обновлён {formatDate(project.updated_at)} · ревизия {project.version}
                      </p>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </Card>

          <div style={{ marginTop: 16 }}>
            <Card title="Создать проект">
              <form onSubmit={onCreate}>
                <label style={{ display: 'block', marginBottom: 8 }}>
                  <span
                    style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}
                  >
                    Название *
                  </span>
                  <input
                    data-testid="project-name-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Например: Маркетинг-агентство"
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '1px solid #c8ced6',
                    }}
                  />
                </label>
                <label style={{ display: 'block', marginBottom: 8 }}>
                  <span
                    style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}
                  >
                    Описание
                  </span>
                  <textarea
                    data-testid="project-description-input"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '1px solid #c8ced6',
                    }}
                  />
                </label>
                {createError ? (
                  <p style={{ color: '#a3271c', fontSize: 13 }}>{createError}</p>
                ) : null}
                <button
                  type="submit"
                  data-testid="project-create-button"
                  disabled={creating || !name.trim()}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 6,
                    border: 'none',
                    background: '#1c5fa8',
                    color: '#fff',
                    fontWeight: 600,
                    cursor: creating || !name.trim() ? 'not-allowed' : 'pointer',
                    opacity: creating || !name.trim() ? 0.6 : 1,
                  }}
                >
                  {creating ? 'Создание…' : 'Создать проект'}
                </button>
              </form>
            </Card>
          </div>
        </div>

        {/* Right column: workspaces */}
        <div>
          <Card title="Рабочие пространства текущего проекта">
            {!projectId ? (
              <p style={{ color: '#5b6472' }}>
                Выберите проект слева, чтобы увидеть его рабочие пространства.
              </p>
            ) : null}
            {workspaces.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
            {workspaces.error ? (
              <p style={{ color: '#a3271c' }}>Ошибка: {workspaces.error.message}</p>
            ) : null}
            {projectId && !workspaces.loading && !workspaces.error ? (
              workspaces.data!.length === 0 ? (
                <p style={{ color: '#5b6472' }}>Рабочие пространства не найдены.</p>
              ) : (
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {workspaces.data!.map((ws) => (
                    <li
                      key={ws.id}
                      style={{
                        padding: '10px 12px',
                        border: '1px solid #e2e6ea',
                        borderRadius: 8,
                        marginBottom: 8,
                      }}
                    >
                      <strong>{ws.name}</strong>
                      <p style={{ margin: '4px 0 0', color: '#9aa2af', fontSize: 12 }}>
                        project_id {ws.project_id}
                        {ws.path ? ` · path ${ws.path}` : ''}
                      </p>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </Card>
        </div>
      </div>
    </div>
  );
}
