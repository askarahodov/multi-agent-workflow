import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import ProjectSetupWizard from './ProjectSetupWizard';
import { useMvpStore } from '../../mvp/mvpStore';
import { MockAdapter } from '../../api/mockAdapter';

beforeEach(() => {
  act(() => useMvpStore.setState({
    api: new MockAdapter(), projectId: null, runId: null, taskId: null, activeSection: 'setup',
  }));
});
afterEach(() => { cleanup(); });

describe('guided setup, server-backed', () => {
  it('creates a project and workspace using the API and navigates to readiness', async () => {
    const api = useMvpStore.getState().api;
    const project = vi.spyOn(api, 'createProject');
    const workspace = vi.spyOn(api, 'createWorkspace');
    render(<ProjectSetupWizard />);
    await screen.findByTestId('setup-project-select');
    fireEvent.change(screen.getByTestId('setup-project-name'), { target: { value: 'Example application' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать проект' }));
    await waitFor(() => expect(project).toHaveBeenCalledOnce());
    await screen.findByTestId('setup-workspace-name');
    fireEvent.change(screen.getByTestId('setup-workspace-name'), { target: { value: 'Development' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать пространство' }));
    await waitFor(() => expect(workspace).toHaveBeenCalledOnce());
    expect(workspace.mock.calls[0][0].project_id).toBe(useMvpStore.getState().projectId);
    expect(screen.getByText(/реальные серверные справочники/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Проверить готовность' }));
    expect(screen.getByTestId('setup-checklist')).toHaveTextContent('Example application');
    fireEvent.click(screen.getByRole('button', { name: 'Перейти к настройке запуска' }));
    expect(useMvpStore.getState().activeSection).toBe('runs');
  });

  it('cannot proceed without a project or workspace; never launches a paid request', async () => {
    const api = useMvpStore.getState().api;
    const launch = vi.spyOn(api, 'launchRun');
    render(<ProjectSetupWizard />);
    await screen.findByTestId('setup-project-select');
    expect(screen.getByRole('button', { name: 'Продолжить с выбранным проектом' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /4\. Проверка/ }));
    expect(screen.getByRole('button', { name: 'Перейти к настройке запуска' })).toBeDisabled();
    expect(launch).not.toHaveBeenCalled();
  });

  it('resumes setup for an existing project without recreating it', async () => {
    const api = useMvpStore.getState().api;
    const project = vi.spyOn(api, 'createProject');
    render(<ProjectSetupWizard />);
    await waitFor(() => expect(screen.getByRole('option', { name: 'Default Project' })).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('setup-project-select'), { target: { value: 'proj_seed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Продолжить с выбранным проектом' }));
    expect(await screen.findByText('Default Workspace')).toBeInTheDocument();
    expect(project).not.toHaveBeenCalled();
  });
});
