/* eslint-disable @typescript-eslint/no-unused-vars */
import { render, screen, cleanup } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import ProjectDashboard from './ProjectDashboard';
import TaskBoard from './TaskBoard';
import AgentMonitor from './AgentMonitor';
import SettingsPage from './SettingsPage';
import { I18nProvider } from '../../i18n';
import { ToastProvider } from '../../components';
import { useMvpStore } from '../../mvp/mvpStore';
import { MockAdapter } from '../../api/mockAdapter';

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
});
