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

// Idempotency keys are not credentials. Keeping only unresolved launch keys in
// per-tab sessionStorage lets navigation/reload recover an uncertain POST.
// Never store API keys, bearer tokens or provider credentials here.
const PENDING_KEY = 'maw:pending-published-launches:v1';
function readPending(): Record<string, string> {
  try {
    const stored = sessionStorage.getItem(PENDING_KEY);
    if (!stored) return {};
    const data: unknown = JSON.parse(stored);
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
    return Object.fromEntries(Object.entries(data).filter(([selection, key]) =>
      selection.length > 0 && selection.length <= 512 &&
      typeof key === 'string' && /^[a-f0-9]{32}$/.test(key)
    ));
  } catch { return {}; }
}

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
  /** Unconfirmed POST keys survive SPA navigation and same-tab reload. */
  pendingPublishedLaunches: Record<string, string>;
  setPendingPublishedLaunch: (selection: string, key: string | null) => void;
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
  pendingPublishedLaunches: readPending(),
  setPendingPublishedLaunch: (selection, key) => set((state) => {
    const next = {...state.pendingPublishedLaunches};
    if (key === null) delete next[selection];
    else next[selection] = key;
    try { sessionStorage.setItem(PENDING_KEY, JSON.stringify(next)); }
    catch { /* private-storage restrictions must not break the in-memory guard */ }
    return {pendingPublishedLaunches: next};
  }),
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
