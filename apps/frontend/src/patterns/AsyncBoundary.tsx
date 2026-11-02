/**
 * AsyncBoundary — declarative loading / error / empty / content states.
 *
 * Every data-driven view renders exactly one of four states through this
 * component so loading/error/empty handling is consistent (ADR-110 §3.6).
 */

import type { ReactNode } from 'react';

import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { SkeletonText } from '../components/Skeleton';

export interface AsyncBoundaryProps {
  loading: boolean;
  error?: Error | string | null;
  isEmpty?: boolean;
  onRetry?: () => void;
  /** Number of skeleton lines rendered while loading. */
  skeletonLines?: number;
  emptyTitle?: string;
  emptyBody?: ReactNode;
  emptyIcon?: string;
  emptyAction?: ReactNode;
  children: ReactNode;
}

export function AsyncBoundary({
  loading,
  error,
  isEmpty = false,
  onRetry,
  skeletonLines = 3,
  emptyTitle = 'Нет данных',
  emptyBody,
  emptyIcon,
  emptyAction,
  children,
}: AsyncBoundaryProps) {
  if (loading) return <SkeletonText lines={skeletonLines} />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (isEmpty) {
    return <EmptyState title={emptyTitle} body={emptyBody} icon={emptyIcon} action={emptyAction} />;
  }
  return <>{children}</>;
}
