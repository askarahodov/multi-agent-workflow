/**
 * Shared MVP v1 client-side state.
 *
 * Holds the single `ApiAdapter` instance the whole MVP UI consumes plus the
 * cross-section navigation and selection state (active project, focused run,
 * focused task). A tiny static mutable object keeps adapter injection simple
 * for tests without adding a context provider to every section boundary.
 */

import { create } from 'zustand';

import { createApiAdapter } from '../api/client';
import type { ApiAdapter } from '../api/client';

export type MvpSection =
  'project' | 'setup' | 'board' | 'profiles' | 'conveyor' | 'runs' | 'task' | 'agent-log' | 'recovery' | 'settings' | 'editor';

export interface MvpState {
  /** The single API adapter consumed by every MVP section. */
  api: ApiAdapter;
  activeSection: MvpSection;
  /** Currently selected project (drives board/runs filters). */
  projectId: string | null;
  /** Currently focused run (drives the runs detail + live agent log). */
  runId: string | null;
  /** Currently focused task (drives the task card). */
  taskId: string | null;
  setSection: (section: MvpSection) => void;
  selectProject: (id: string | null) => void;
  selectRun: (id: string | null) => void;
  selectTask: (id: string | null) => void;
}

export const useMvpStore = create<MvpState>()((set) => ({
  api: createApiAdapter(),
  activeSection: 'project',
  projectId: null,
  runId: null,
  taskId: null,
  setSection: (section) => set({ activeSection: section }),
  // A run belongs to one project, and a task belongs to one run.
  // Change the selection and clear its descendants atomically so no
  // observer can render an orphaned run/task in a new context.
  selectProject: (id) => set((state) =>
    state.projectId === id ? state : { projectId: id, runId: null, taskId: null }),
  selectRun: (id) => set((state) =>
    state.runId === id ? state : { runId: id, taskId: null }),
  selectTask: (id) => set({ taskId: id }),
}));
