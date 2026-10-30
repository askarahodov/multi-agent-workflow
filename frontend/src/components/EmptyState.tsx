/** EmptyState — what to show when a data view has no rows. */

import type { ReactNode } from 'react';

import styles from './surfaces.module.css';

export interface EmptyStateProps {
  title: string;
  body?: ReactNode;
  icon?: string;
  action?: ReactNode;
}

export function EmptyState({ title, body, icon = '📭', action }: EmptyStateProps) {
  return (
    <div className={styles.state} data-testid="empty-state" role="status">
      <span className={styles.stateIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.stateTitle}>{title}</span>
      {body ? <span className={styles.stateBody}>{body}</span> : null}
      {action}
    </div>
  );
}
