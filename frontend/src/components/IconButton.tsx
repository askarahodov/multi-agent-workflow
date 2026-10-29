/**
 * IconButton — icon-only action control.
 *
 * Accessibility rule (ADR-110 §3.3 rule 2): an icon-only button has no visible
 * text, so it MUST carry an accessible name. `label` is required and is applied
 * as `aria-label`; the visual glyph is hidden from assistive tech.
 */

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import styles from './controls.module.css';
import { cx } from './cx';

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name (required — icon-only controls must be labelled). */
  label: string;
  children: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, children, className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cx(styles.iconButton, className)}
      {...rest}
    >
      <span aria-hidden="true">{children}</span>
    </button>
  );
});
