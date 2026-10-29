/**
 * AppShell — responsive application chrome (ADR-110 §3.4).
 *
 * Provides: a skip-to-content link, a labelled primary navigation landmark,
 * a top bar with the section title and actions, a main landmark and a polite
 * live region for streamed status updates. Below `md` (768px) the sidebar
 * becomes an off-canvas drawer toggled by a labelled menu button.
 */

import { useEffect, useId, useState, type ReactNode } from 'react';

import styles from './AppShell.module.css';
import { IconButton } from '../components/IconButton';

export interface NavItem {
  id: string;
  label: string;
  icon?: string;
  /** data-testid applied to the nav button (keeps existing test hooks). */
  testId?: string;
}

export interface AppShellProps {
  brand: string;
  brandSubtitle?: string;
  nav: NavItem[];
  activeNav: string;
  onNavigate: (id: string) => void;
  title: string;
  topbarActions?: ReactNode;
  /** Extra content rendered in the polished live region. */
  liveMessage?: string;
  children: ReactNode;
}

export function AppShell({
  brand,
  brandSubtitle,
  nav,
  activeNav,
  onNavigate,
  title,
  topbarActions,
  liveMessage,
  children,
}: AppShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const contentId = 'main-content';
  const liveId = useId();

  // Close the mobile drawer whenever the active section changes.
  useEffect(() => setDrawerOpen(false), [activeNav]);

  return (
    <div className={styles.shell}>
      <a className="skip-link" href={`#${contentId}`}>
        Перейти к содержимому
      </a>

      {drawerOpen ? (
        <div
          className={styles.scrimVisible}
          role="presentation"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}

      <aside
        id="primary-sidebar"
        className={`${styles.sidebar} ${drawerOpen ? styles.drawerOpen : ''}`}
        aria-label="Боковая панель"
      >
        <div className={styles.brand}>
          <span className={styles.brandName}>{brand}</span>
          {brandSubtitle ? <span className={styles.brandSub}>{brandSubtitle}</span> : null}
        </div>
        <nav className={styles.nav} aria-label="Основная навигация">
          {nav.map((item) => (
            <button
              key={item.id}
              type="button"
              data-testid={item.testId}
              aria-current={activeNav === item.id ? 'page' : undefined}
              className={styles.navItem}
              onClick={() => onNavigate(item.id)}
            >
              {item.icon ? (
                <span className={styles.navIcon} aria-hidden="true">
                  {item.icon}
                </span>
              ) : null}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.topbarTitle}>
            <span className={styles.menuButton}>
              <IconButton
                label="Открыть меню"
                aria-expanded={drawerOpen}
                aria-controls="primary-sidebar"
                onClick={() => setDrawerOpen((open) => !open)}
              >
                ☰
              </IconButton>
            </span>
            <h1 style={{ fontSize: 'inherit', margin: 0 }}>{title}</h1>
          </div>
          <div className={styles.topbarActions}>{topbarActions}</div>
        </header>

        {/* Polite live region: announces streamed status/notification text. */}
        <div
          id={liveId}
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="visually-hidden"
          data-testid="shell-live-region"
        >
          {liveMessage}
        </div>

        <main id={contentId} className={styles.content} tabIndex={-1}>
          <div className={styles.contentInner}>{children}</div>
        </main>
      </div>
    </div>
  );
}
