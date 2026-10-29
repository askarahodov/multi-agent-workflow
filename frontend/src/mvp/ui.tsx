/**
 * Shared MVP UI helpers.
 *
 * Thin compatibility layer over the design system (`src/components`,
 * `src/patterns`) so the older MVP sections keep their existing import surface
 * (`Card`, `PageHeader`, `StatusBadge`, `formatDate`, status helpers) while
 * rendering the single token-driven component library underneath.
 */

import type { ReactNode } from 'react';

import { Card as DSCard } from '../components/Card';
import {
  StatusBadge as DSStatusBadge,
  statusLabel as dsStatusLabel,
  statusTone as dsStatusTone,
  type StatusBadgeProps as DSStatusBadgeProps,
  type StatusTone,
} from '../components/Badge';
import { PageHeader as DSPageHeader } from '../patterns/PageHeader';

export type { StatusTone };

/** Best-effort mapping from a raw backend status string to a UI tone. */
export const statusTone = dsStatusTone;

/** Human label for a status code. */
export const statusLabel = dsStatusLabel;

export type StatusBadgeProps = DSStatusBadgeProps;

/** Pill badge rendering a status consistently across all MVP sections. */
export function StatusBadge(props: DSStatusBadgeProps): ReactNode {
  return <DSStatusBadge {...props} />;
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
  return <DSPageHeader title={title} subtitle={subtitle} actions={actions} level={2} />;
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
  return (
    <DSCard title={title} footer={footer}>
      {children}
    </DSCard>
  );
}
