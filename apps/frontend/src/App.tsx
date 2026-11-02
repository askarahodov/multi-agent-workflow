import { useMvpStore, type MvpSection } from './mvp/mvpStore';
import { AppShell, type NavItem } from './patterns/AppShell';
import { I18nProvider, useI18n, type Locale } from './i18n';
import { Select, ToastProvider } from './components';
import ProjectDashboard from './pages/ProjectDashboard';
import TaskBoard from './pages/TaskBoard';
import AgentMonitor from './pages/AgentMonitor';
import SettingsPage from './pages/SettingsPage';
import ConveyorSection from './mvp/sections/ConveyorSection';
import RunsSection from './mvp/sections/RunsSection';
import TaskSection from './mvp/sections/TaskSection';
import RecoverySection from './mvp/sections/RecoverySection';
import NodePalette from './editor/NodePalette';
import WorkflowCanvas from './editor/WorkflowCanvas';
import PropertyPanel from './editor/PropertyPanel';

/**
 * Platform app shell.
 *
 * Composes the design-system `AppShell` (responsive, accessible navigation and
 * live region) with the section layouts. Providers are mounted here so the
 * whole tree has access to i18n (ru default / en fallback, ADR-110 §3.5) and
 * toast notifications (ADR-110 §3.2).
 */
export default function App() {
  return (
    <I18nProvider>
      <ToastProvider>
        <AppFrame />
      </ToastProvider>
    </I18nProvider>
  );
}

function AppFrame() {
  const { t, locale, setLocale } = useI18n();
  const activeSection = useMvpStore((s) => s.activeSection);
  const setSection = useMvpStore((s) => s.setSection);

  const nav: NavItem[] = [
    { id: 'project', label: t('nav.project'), icon: '📁', testId: 'nav-project' },
    { id: 'board', label: t('nav.board'), icon: '🗂', testId: 'nav-board' },
    { id: 'conveyor', label: t('nav.conveyor'), icon: '⚙', testId: 'nav-conveyor' },
    { id: 'runs', label: t('nav.runs'), icon: '▶', testId: 'nav-runs' },
    { id: 'task', label: t('nav.task'), icon: '🗒', testId: 'nav-task' },
    { id: 'agent-log', label: t('nav.agentLog'), icon: '🛰', testId: 'nav-agent-log' },
    { id: 'recovery', label: t('nav.recovery'), icon: '🛟', testId: 'nav-recovery' },
    { id: 'settings', label: t('nav.settings'), icon: '⚙', testId: 'nav-settings' },
    { id: 'editor', label: t('nav.editor'), icon: '🧩', testId: 'nav-editor' },
  ];

  const activeItem = nav.find((item) => item.id === activeSection);

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
        return <ProjectDashboard />;
      case 'board':
        return <TaskBoard />;
      case 'conveyor':
        return <ConveyorSection />;
      case 'runs':
        return <RunsSection />;
      case 'task':
        return <TaskSection />;
      case 'agent-log':
        return <AgentMonitor />;
      case 'recovery':
        return <RecoverySection />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <ProjectDashboard />;
    }
  }

  return (
    <AppShell
      brand={t('shell.brand')}
      brandSubtitle={t('shell.subtitle')}
      nav={nav}
      activeNav={activeSection}
      onNavigate={(id) => setSection(id as MvpSection)}
      title={activeItem?.label ?? ''}
      topbarActions={
        <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-muted)' }}>
            {t('shell.language')}
          </span>
          <Select
            aria-label={t('shell.language')}
            value={locale}
            onChange={(e) => setLocale(e.target.value as Locale)}
            style={{ marginBlockEnd: 0, width: 'auto' }}
          >
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </Select>
        </label>
      }
    >
      {renderSection()}
    </AppShell>
  );
}
