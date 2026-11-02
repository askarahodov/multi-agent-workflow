/** PageHeader — section title strip with subtitle, breadcrumbs and actions. */

import type { ReactNode } from 'react';

import { Breadcrumbs, type Crumb } from '../components/Breadcrumbs';

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  breadcrumbs?: Crumb[];
  /** Heading level used for the title (shell owns the h1). */
  level?: 1 | 2;
}

export function PageHeader({ title, subtitle, actions, breadcrumbs, level = 2 }: PageHeaderProps) {
  const Heading = (level === 1 ? 'h1' : 'h2') as 'h1' | 'h2';
  return (
    <div style={{ marginBlockEnd: 'var(--space-4)' }}>
      {breadcrumbs?.length ? <Breadcrumbs items={breadcrumbs} /> : null}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 'var(--space-4)',
          marginBlockStart: breadcrumbs?.length ? 'var(--space-2)' : 0,
        }}
      >
        <div>
          <Heading style={{ margin: 0, fontSize: 'var(--font-size-xl)', fontWeight: 650 }}>{title}</Heading>
          {subtitle ? (
            <p style={{ margin: '4px 0 0', color: 'var(--color-text-muted)', fontSize: 'var(--font-size-md)' }}>
              {subtitle}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>{actions}</div>
        ) : null}
      </div>
    </div>
  );
}
