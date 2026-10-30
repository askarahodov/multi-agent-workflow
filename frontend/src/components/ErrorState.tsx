/** ErrorState — consistent, actionable error surface (ADR-101 §3.4 / RFC 9457). */

import { Button } from './Button';
import styles from './surfaces.module.css';

export interface ErrorStateProps {
  title?: string;
  error: Error | string;
  onRetry?: () => void;
}

export function ErrorState({ title = 'Не удалось загрузить данные', error, onRetry }: ErrorStateProps) {
  const message = typeof error === 'string' ? error : error.message;
  return (
    <div className={`${styles.state} ${styles.errorState}`} data-testid="error-state" role="alert">
      <span className={styles.stateIcon} aria-hidden="true">
        ⚠
      </span>
      <span className={styles.stateTitle}>{title}</span>
      <span className={styles.stateBody}>{message}</span>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Повторить
        </Button>
      ) : null}
    </div>
  );
}
