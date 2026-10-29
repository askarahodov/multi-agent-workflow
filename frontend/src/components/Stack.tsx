/** Layout primitives — Stack, Grid, Split (ADR-110 §3.4). */

import type { CSSProperties, ElementType, ReactNode } from 'react';

import styles from './layout.module.css';
import { cx } from './cx';

export interface StackProps {
  gap?: number;
  as?: ElementType;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}

export function Stack({ gap = 4, as: Tag = 'div', className, style, children }: StackProps) {
  const rem = `var(--space-${gap})`;
  return (
    <Tag className={cx(styles.stack, className)} style={{ gap: rem, ...style }}>
      {children}
    </Tag>
  );
}

export interface GridProps {
  /** `auto` (260px min), `wide` (340px min) or explicit min column width. */
  min?: number | 'auto' | 'wide';
  gap?: number;
  className?: string;
  children: ReactNode;
}

export function Grid({ min = 'auto', gap = 4, className, children }: GridProps) {
  const base = min === 'wide' ? styles.autoGridWide : styles.autoGrid;
  const style =
    typeof min === 'number'
      ? { gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: `var(--space-${gap})` }
      : { gap: `var(--space-${gap})` };
  return (
    <div className={cx(base, className)} style={style}>
      {children}
    </div>
  );
}

export function Split({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx(styles.split, className)}>{children}</div>;
}
