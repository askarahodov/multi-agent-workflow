/** Loading placeholders — Skeleton and Spinner. */

import styles from './surfaces.module.css';
import { cx } from './cx';

export interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  radius?: string;
  className?: string;
}

export function Skeleton({ width = '100%', height = 12, radius, className }: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      data-testid="skeleton"
      className={cx(styles.skeleton, className)}
      style={{ width, height, borderRadius: radius }}
    />
  );
}

/** A block of `lines` text skeletons (last line shortened). */
export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div data-testid="skeleton-text" role="status" aria-label="Загрузка данных">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? '60%' : '100%'} />
      ))}
    </div>
  );
}

export function Spinner({ label = 'Загрузка' }: { label?: string }) {
  return (
    <span role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  );
}
