import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppShell } from './AppShell';
import { PageHeader } from './PageHeader';
import { AsyncBoundary } from './AsyncBoundary';

afterEach(cleanup);

const NAV = [
  { id: 'project', label: 'Проект', testId: 'nav-project' },
  { id: 'board', label: 'Доска', testId: 'nav-board' },
];

describe('AppShell', () => {
  it('provides a skip link, labelled nav, main landmark and live region', () => {
    render(
      <AppShell brand="Platform" brandSubtitle="Sub" nav={NAV} activeNav="project" onNavigate={() => {}} title="Проект">
        <p>content</p>
      </AppShell>,
    );
    const skip = screen.getByRole('link', { name: 'Перейти к содержимому' });
    expect(skip).toHaveAttribute('href', '#main-content');
    expect(screen.getByRole('navigation', { name: 'Основная навигация' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content');
    expect(screen.getByTestId('nav-project')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('shell-live-region')).toHaveAttribute('aria-live', 'polite');
  });

  it('navigates on nav click and toggles the mobile drawer button', async () => {
    const onNavigate = vi.fn();
    render(
      <AppShell brand="P" nav={NAV} activeNav="project" onNavigate={onNavigate} title="Проект">
        <p>content</p>
      </AppShell>,
    );
    await userEvent.click(screen.getByTestId('nav-board'));
    expect(onNavigate).toHaveBeenCalledWith('board');

    const menu = screen.getByRole('button', { name: 'Открыть меню' });
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('PageHeader', () => {
  it('renders a level-2 heading with subtitle and breadcrumbs', () => {
    render(<PageHeader title="Заголовок" subtitle="Подзаголовок" breadcrumbs={[{ label: 'Платформа' }, { label: 'Проект' }]} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Заголовок' })).toBeInTheDocument();
    expect(screen.getByText('Подзаголовок')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Хлебные крошки' })).toBeInTheDocument();
    expect(screen.getByText('Проект')).toHaveAttribute('aria-current', 'page');
  });
});

describe('AsyncBoundary', () => {
  it('renders a loading skeleton first', () => {
    render(
      <AsyncBoundary loading skeletonLines={2}>
        <p>ready</p>
      </AsyncBoundary>,
    );
    expect(screen.getByTestId('skeleton-text')).toBeInTheDocument();
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
  });

  it('renders an error state with retry', async () => {
    const onRetry = vi.fn();
    render(
      <AsyncBoundary loading={false} error={new Error('nope')} onRetry={onRetry}>
        <p>ready</p>
      </AsyncBoundary>,
    );
    expect(screen.getByTestId('error-state')).toHaveTextContent('nope');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders an empty state when empty', () => {
    render(
      <AsyncBoundary loading={false} isEmpty emptyTitle="Пусто">
        <p>ready</p>
      </AsyncBoundary>,
    );
    expect(screen.getByTestId('empty-state')).toHaveTextContent('Пусто');
  });

  it('renders children when data is present', () => {
    render(
      <AsyncBoundary loading={false}>
        <p>ready</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText('ready')).toBeInTheDocument();
  });
});
