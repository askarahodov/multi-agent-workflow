/**
 * Badge / StatusBadge — status pills.
 *
 * Status is conveyed by text *and* tone, never colour alone (ADR-110 §3.3
 * rule 4): `StatusBadge` always renders the human label. The tone helpers are
 * the single mapping used everywhere a backend status string is displayed.
 */

import type { ReactNode } from 'react';

import styles from './surfaces.module.css';
import { cx } from './cx';

export type StatusTone = 'muted' | 'info' | 'success' | 'warn' | 'error' | 'accent';

const TONE_CLASS: Record<StatusTone, string> = {
  muted: styles.toneMuted,
  info: styles.toneInfo,
  success: styles.toneSuccess,
  warn: styles.toneWarn,
  error: styles.toneError,
  accent: styles.toneAccent,
};

/** Non-colour glyph per tone, exposed to assistive tech via the label text. */
const TONE_ICON: Record<StatusTone, string> = {
  muted: '·',
  info: 'ℹ',
  success: '✓',
  warn: '!',
  error: '✕',
  accent: '★',
};

/** Best-effort mapping from a raw backend status string to a UI tone. */
export function statusTone(status: string): StatusTone {
  const s = status.toLowerCase();
  if (['completed', 'succeeded', 'success', 'ok', 'idle', 'verified'].includes(s)) return 'success';
  if (['failed', 'error', 'cancelled', 'rejected'].includes(s)) return 'error';
  if (['blocked', 'waiting', 'expired', 'paused'].includes(s)) return 'warn';
  if (['running', 'in_progress', 'pending', 'claimed', 'queued'].includes(s)) return 'info';
  if (s === '') return 'muted';
  return 'accent';
}

/** Human label for a status code (kept short so it fits badge pills). */
export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: 'Pending',
    queued: 'Queued',
    running: 'Running',
    in_progress: 'In progress',
    claimed: 'Claimed',
    completed: 'Completed',
    succeeded: 'Succeeded',
    success: 'Success',
    ok: 'OK',
    failed: 'Failed',
    error: 'Error',
    cancelled: 'Cancelled',
    rejected: 'Rejected',
    blocked: 'Blocked',
    waiting: 'Waiting',
    expired: 'Expired',
    idle: 'Idle',
    verified: 'Verified',
  };
  return labels[status.toLowerCase()] ?? status;
}

export interface BadgeProps {
  tone?: StatusTone;
  /** Show the non-colour status glyph (default true). */
  icon?: boolean;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = 'muted', icon = false, className, children }: BadgeProps) {
  return (
    <span className={cx(styles.badge, TONE_CLASS[tone], className)}>
      {icon ? (
        <span className={styles.badgeIcon} aria-hidden="true">
          {TONE_ICON[tone]}
        </span>
      ) : null}
      {children}
    </span>
  );
}

export interface StatusBadgeProps {
  status: string;
  tone?: StatusTone;
  label?: string;
  /** Show the non-colour glyph alongside the text label. */
  icon?: boolean;
  className?: string;
}

/** Pill badge rendering a status consistently across every section. */
export function StatusBadge({ status, tone, label, icon = false, className }: StatusBadgeProps) {
  const resolved = tone ?? statusTone(status);
  return (
    <Badge tone={resolved} icon={icon} className={className}>
      {label ?? statusLabel(status)}
    </Badge>
  );
}
