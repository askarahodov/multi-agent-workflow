/**
 * Button — token-driven, accessible action control (ADR-110 §3.2).
 *
 * Variants map to intent; `type` defaults to `button` so a component dropped
 * inside a form never submits by accident.
 */

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import styles from './controls.module.css';
import { cx } from './cx';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Optional leading icon (decorative unless it carries its own label). */
  leadingIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', leadingIcon, className, type = 'button', children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(styles.button, styles[variant], size !== 'md' ? styles[size] : undefined, className)}
      {...rest}
    >
      {leadingIcon}
      {children}
    </button>
  );
});
