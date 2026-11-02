/**
 * Tooltip — accessible description on hover/focus (ADR-110 §3.2).
 *
 * The trigger receives `aria-describedby` pointing at the tooltip, which is
 * shown for both pointer hover and keyboard focus, so keyboard users get the
 * same affordance as mouse users.
 */

import { useId, useState, type ReactNode } from 'react';

import styles from './overlays.module.css';

export interface TooltipProps {
  label: string;
  children: ReactNode;
}

export function Tooltip({ label, children }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span
      className={styles.tooltipWrap}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open ? (
        <span role="tooltip" id={id} className={styles.tooltip}>
          {label}
        </span>
      ) : null}
    </span>
  );
}
