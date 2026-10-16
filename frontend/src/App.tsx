import { type CSSProperties } from 'react';

import ProjectSection from './mvp/sections/ProjectSection';
import BoardSection from './mvp/sections/BoardSection';
import ConveyorSection from './mvp/sections/ConveyorSection';
import RunsSection from './mvp/sections/RunsSection';
import TaskSection from './mvp/sections/TaskSection';
import AgentLogSection from './mvp/sections/AgentLogSection';
import RecoverySection from './mvp/sections/RecoverySection';
import SettingsSection from './mvp/sections/SettingsSection';
import { useMvpStore, type MvpSection } from './mvp/mvpStore';
import { StatusBadge } from './mvp/ui';
import NodePalette from './editor/NodePalette';
import WorkflowCanvas from './editor/WorkflowCanvas';
import PropertyPanel from './editor/PropertyPanel';

const NAV: Array<{ id: MvpSection; label: string }> = [
  { id: 'project', label: '1. Проект' },
  { id: 'board', label: '2. Kanban-доска' },
  { id: 'conveyor', label: '3. Конвейер и роли' },
  { id: 'runs', label: '4. Запуски' },
  { id: 'task', label: '5. Карточка задачи' },
  { id: 'agent-log', label: '6. Живой журнал' },
  { id: 'recovery', label: '7. Аварийное восстановление' },
  { id: 'settings', label: '8. Настройки' },
  { id: 'editor', label: 'Editor' },
];

const ACTIVE_LABEL: Record<string, string> = {
  project: 'Проект',
  board: 'Kanban-доска',
  conveyor: 'Конвейер и роли',
  runs: 'Запуски и результаты',
  task: 'Карточка задачи',
  'agent-log': 'Живой журнал агента',
  recovery: 'Аварийное восстановление',
  editor: 'Редактор конвейеров',
  settings: 'Настройки проекта',
};

/**
 * MVP v1 app shell. Left sidebar navigates between the platform sections
 * (project, board, conveyor, runs, task card, live agent log) and the existing
 * canvas editor. The active section renders in the main area.
 */
export default function App() {
  // Track the editor and MVP sections under a single active-tab identifier.
  // The editor is `editor`; the MVP runtime sections reuse the mvp store.
  const activeSection = useMvpStore((s) => s.activeSection);
  const setSection = useMvpStore((s) => s.setSection);

  function renderSection() {
    if (activeSection === 'editor') {
      return (
        <div style={{ display: 'flex', height: '100%', width: '100%' }}>
          <NodePalette />
          <div style={{ flex: 1, position: 'relative' }}>
            <WorkflowCanvas />
          </div>
          <PropertyPanel />
        </div>
      );
    }
    switch (activeSection) {
      case 'project':
        return <ProjectSection />;
      case 'board':
        return <BoardSection />;
      case 'conveyor':
        return <ConveyorSection />;
      case 'runs':
        return <RunsSection />;
      case 'task':
        return <TaskSection />;
      case 'agent-log':
        return <AgentLogSection />;
      case 'recovery':
        return <RecoverySection />;
      case 'settings':
        return <SettingsSection />;
      default:
        return <ProjectSection />;
    }
  }

  return (
    <div style={shellStyle}>
      <aside style={sidebarStyle}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #243043' }}>
          <strong style={{ color: '#fff', fontSize: 14 }}>Multi-Agent Platform</strong>
          <p style={{ margin: '6px 0 0', color: '#8fa6c0', fontSize: 11 }}>MVP v1 UI</p>
        </div>
        <nav style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {NAV.map((item) => {
            const active = activeSection === item.id;
            return (
              <button
                key={item.id}
                data-testid={`nav-${item.id}`}
                onClick={() => setSection(item.id)}
                style={{
                  ...navItemStyle,
                  background: active ? '#1c5fa8' : 'transparent',
                  color: active ? '#fff' : '#c9d6e4',
                }}
              >
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>
      <main style={mainStyle}>
        <div style={topbarStyle}>
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 650 }}>
            {ACTIVE_LABEL[activeSection]}
          </h1>
          <StatusBadge status="running" tone="info" label="MVP v1" />
        </div>
        <div style={{ padding: 16, overflow: 'auto', height: 'calc(100% - 52px)' }}>
          {renderSection()}
        </div>
      </main>
    </div>
  );
}

const shellStyle: CSSProperties = {
  display: 'flex',
  height: '100vh',
  width: '100vw',
  fontFamily: 'system-ui, sans-serif',
  margin: 0,
  background: '#f4f6f8',
};

const sidebarStyle: CSSProperties = {
  width: 224,
  flexShrink: 0,
  background: '#1b2434',
  color: '#c9d6e4',
  display: 'flex',
  flexDirection: 'column',
};

const navItemStyle: CSSProperties = {
  textAlign: 'left',
  padding: '9px 12px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 600,
  margin: 0,
};

const mainStyle: CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  minWidth: 0,
  background: '#f4f6f8',
};

const topbarStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 12,
  padding: '12px 16px',
  background: '#fff',
  borderBottom: '1px solid #e2e6ea',
};
