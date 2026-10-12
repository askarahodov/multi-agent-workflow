/**
 * Shared MVP UI helpers: status meta (label + colour), time formatting and a
 * small reusable `<StatusBadge>` renderer, so every section renders states
 * consistently (D-luch ADR-101 — errors and states render coherently).
 */

import type { CSSProperties, ReactNode } from 'react';

export type StatusTone = 'muted' | 'info' | 'success' | 'warn' | 'error' | 'accent';

const TONE_COLOURS: Record<StatusTone, { bg: string; fg: string }> = {
  muted: { bg: '#eceef1', fg: '#5b6472' },
  info: { bg: '#e8f1fd', fg: '#1c5fa8' },
  success: { bg: '#e5f6e9', fg: '#18703b' },
  warn: { bg: '#fdf3e1', fg: '#9a6a12' },
  error: { bg: '#fdeae8', fg: '#a3271c' },
  accent: { bg: '#efe9fb', fg: '#6236c3' },
};

/** Best-effort mapping from a raw backend status string to a UI tone. */
export function statusTone(status: string): StatusTone {
  const s = status.toLowerCase();
  if (['completed', 'succeeded', 'success', 'ok', 'idle'].includes(s)) return 'success';
  if (['failed', 'error', 'cancelled', 'rejected'].includes(s)) return 'error';
  if (['blocked', 'waiting', 'expired'].includes(s)) return 'warn';
  if (['running', 'in_progress', 'pending', 'claimed', 'queued'].includes(s)) return 'info';
  if (s === '') return 'muted';
  return 'accent';
}

/** Human label for a status code (kept short so it fits badge pills). */
export function statusLabel(status: string): string {
  const s = status.toLowerCase();
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
  };
  return labels[s] ?? status;
}

export interface StatusBadgeProps {
  status: string;
  tone?: StatusTone;
  label?: string;
}

/** Pill badge rendering a status consistently across all MVP sections. */
export function StatusBadge({ status, tone, label }: StatusBadgeProps): ReactNode {
  const resolved = tone ?? statusTone(status);
  const colour = TONE_COLOURS[resolved];
  const style: CSSProperties = {
    display: 'inline-block',
    padding: '2px 10px',
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    background: colour.bg,
    color: colour.fg,
    whiteSpace: 'nowrap',
  };
  return <span style={style}>{label ?? statusLabel(status)}</span>;
}

/** Format an ISO timestamp for display; returns '—' when absent. */
export function formatDate(value?: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** Section page scaffolding: title strip + body. */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}): ReactNode {
  const style: CSSProperties = {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 16,
    marginBottom: 16,
  };
  return (
    <div style={style}>
      <div>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 650 }}>{title}</h1>
        {subtitle ? (
          <p style={{ margin: '4px 0 0', color: '#5b6472', fontSize: 13 }}>{subtitle}</p>
        ) : null}
      </div>
      {actions ? (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{actions}</div>
      ) : null}
    </div>
  );
}

/** Lightweight card wrapper. */
export function Card({
  title,
  children,
  footer,
}: {
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}): ReactNode {
  const style: CSSProperties = {
    border: '1px solid #e2e6ea',
    borderRadius: 10,
    background: '#fff',
    overflow: 'hidden',
  };
  return (
    <div style={style}>
      {title ? (
        <div
          style={{
            padding: '10px 14px',
            borderBottom: '1px solid #eef0f3',
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          {title}
        </div>
      ) : null}
      <div style={{ padding: 14 }}>{children}</div>
      {footer ? (
        <div style={{ padding: '10px 14px', borderTop: '1px solid #eef0f3' }}>{footer}</div>
      ) : null}
    </div>
  );
}
