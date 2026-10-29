import { render, screen, cleanup } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import ProjectDashboard from './ProjectDashboard';
import TaskBoard from './TaskBoard';
import AgentMonitor from './AgentMonitor';
import SettingsPage from './SettingsPage';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../components';
import { useMvpStore } from '../mvp/mvpStore';
import { MockAdapter } from '../api/mockAdapter';

function Providers({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <ToastProvider>{children}</ToastProvider>
    </I18nProvider>
  );
}

beforeEach(() => {
  act(() => {
    useMvpStore.setState({ api: new MockAdapter(), projectId: null, runId: null, taskId: null });
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('core layouts (design system)', () => {
  it('ProjectDashboard renders its heading, breadcrumbs and create form', () => {
    render(
      <Providers>
        <ProjectDashboard />
      </Providers>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Проект' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Хлебные крошки' })).toBeInTheDocument();
    expect(screen.getByTestId('project-name-input')).toBeInTheDocument();
    expect(screen.getByTestId('project-create-button')).toBeDisabled();
  });

  it('TaskBoard renders the kanban columns with an empty-state ready', async () => {
    render(
      <Providers>
        <TaskBoard />
      </Providers>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Kanban-доска' })).toBeInTheDocument();
    expect(screen.getByTestId('board-run-filter')).toBeInTheDocument();
  });

  it('AgentMonitor renders the live feed as a polite log region', () => {
    render(
      <Providers>
        <AgentMonitor />
      </Providers>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Живой журнал агента' })).toBeInTheDocument();
    // No run selected → an accessible empty prompt is shown.
    expect(screen.getByText('Запуск не выбран')).toBeInTheDocument();
  });

  it('SettingsPage renders tabs and an empty connections state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string) => ({
        ok: true,
        status: 200,
        json: async () => (input.includes('/providers') || input.includes('/model-profiles') || input.includes('/agents/definitions') ? { items: [] } : {}),
      })),
    );
    render(
      <Providers>
        <SettingsPage />
      </Providers>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Настройки проекта' })).toBeInTheDocument();
    expect(screen.getByRole('tablist', { name: 'Настройки' })).toBeInTheDocument();
    expect(await screen.findByText('Подключений пока нет.')).toBeInTheDocument();
    expect(screen.getByLabelText('API key')).toBeInTheDocument();
  });
});
