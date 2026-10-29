/** Card — bordered surface with optional header/footer (ADR-110 §3.2). */

import type { ReactNode } from 'react';

import styles from './surfaces.module.css';

export interface CardProps {
  title?: ReactNode;
  /** Optional control rendered at the trailing edge of the header. */
  actions?: ReactNode;
  footer?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({ title, actions, footer, className, children }: CardProps) {
  return (
    <section className={className ? `${styles.card} ${className}` : styles.card}>
      {title || actions ? (
        <header className={styles.cardHeader}>
          <span>{title}</span>
          {actions ? <span>{actions}</span> : null}
        </header>
      ) : null}
      <div className={styles.cardBody}>{children}</div>
      {footer ? <footer className={styles.cardFooter}>{footer}</footer> : null}
    </section>
  );
}
