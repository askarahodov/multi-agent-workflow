/**
 * Shared MVP v1 client-side state.
 *
 * Holds the single `ApiAdapter` instance the whole MVP UI consumes plus the
 * cross-section navigation and selection state (active project, focused run,
 * focused task). A tiny static mutable object keeps adapter injection simple
 * for tests without adding a context provider to every section boundary.
 */

import { create } from 'zustand';

import { createApiClient } from '../api/client';
import type { ApiAdapter } from '../api/client';

export type MvpSection =
  'project' | 'board' | 'conveyor' | 'runs' | 'task' | 'agent-log' | 'recovery' | 'editor';

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
  api: createApiClient(),
  activeSection: 'project',
  projectId: null,
  runId: null,
  taskId: null,
  setSection: (section) => set({ activeSection: section }),
  selectProject: (id) => set({ projectId: id }),
  selectRun: (id) => set({ runId: id }),
  selectTask: (id) => set({ taskId: id }),
}));
