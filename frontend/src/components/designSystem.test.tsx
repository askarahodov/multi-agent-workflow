import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Button } from './Button';
import { IconButton } from './IconButton';
import { Field, Input } from './Field';
import { Card } from './Card';
import { Badge, StatusBadge, statusLabel, statusTone } from './Badge';
import { SkeletonText, Spinner } from './Skeleton';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { Table } from './Table';
import { Tabs } from './Tabs';
import { Dialog } from './Dialog';
import { Tooltip } from './Tooltip';
import { ToastProvider, useToast } from './Toast';
import { Stack, Grid } from './Stack';

afterEach(cleanup);

describe('controls', () => {
  it('Button defaults to type=button and forwards disabled', () => {
    render(
      <Button disabled data-testid="b">
        Save
      </Button>,
    );
    const button = screen.getByTestId('b');
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Save');
  });

  it('IconButton requires an accessible name and hides its glyph', () => {
    render(<IconButton label="Удалить элемент">✕</IconButton>);
    const button = screen.getByRole('button', { name: 'Удалить элемент' });
    expect(button).toHaveAttribute('title', 'Удалить элемент');
    expect(button.querySelector('span')).toHaveAttribute('aria-hidden', 'true');
  });

  it('Field associates label, hint and error with the control', () => {
    render(
      <Field label="Название" hint="до 255 символов" error="Обязательное поле" required>
        {({ id, ...aria }) => <Input id={id} {...aria} />}
      </Field>,
    );
    const input = screen.getByLabelText('Название');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    const describedBy = input.getAttribute('aria-describedby') ?? '';
    expect(describedBy.split(' ').length).toBe(2);
    expect(screen.getByRole('alert')).toHaveTextContent('Обязательное поле');
  });
});

describe('surfaces', () => {
  it('Card renders header, body and footer slots', () => {
    render(
      <Card title="Заголовок" footer="Низ">
        Тело
      </Card>,
    );
    expect(screen.getByText('Заголовок')).toBeInTheDocument();
    // Card titles must expose heading semantics (a11y, ADR-110).
    expect(screen.getByRole('heading', { name: 'Заголовок' })).toBeInTheDocument();
    expect(screen.getByText('Тело')).toBeInTheDocument();
    expect(screen.getByText('Низ')).toBeInTheDocument();
  });

  it('StatusBadge maps status to a label and renders it as text (not colour alone)', () => {
    render(<StatusBadge status="in_progress" />);
    expect(screen.getByText('In progress')).toBeInTheDocument();
  });

  it('statusTone / statusLabel map known statuses', () => {
    expect(statusTone('completed')).toBe('success');
    expect(statusTone('failed')).toBe('error');
    expect(statusTone('blocked')).toBe('warn');
    expect(statusTone('running')).toBe('info');
    expect(statusLabel('in_progress')).toBe('In progress');
    expect(statusLabel('weird')).toBe('weird');
  });

  it('Badge shows a non-colour glyph when icon is enabled', () => {
    const { container } = render(
      <Badge tone="success" icon>
        Готово
      </Badge>,
    );
    const badge = container.firstElementChild as HTMLElement;
    expect(badge).toHaveTextContent('Готово');
    const glyph = badge.querySelector('[aria-hidden="true"]');
    expect(glyph).not.toBeNull();
    expect(glyph).toHaveTextContent('✓');
  });

  it('SkeletonText and Spinner expose a polite status', () => {
    render(
      <div>
        <SkeletonText lines={2} />
        <Spinner />
      </div>,
    );
    expect(screen.getByLabelText('Загрузка данных')).toBeInTheDocument();
    expect(screen.getAllByRole('status').length).toBeGreaterThanOrEqual(2);
  });

  it('EmptyState renders an accessible status with title and body', () => {
    render(<EmptyState title="Пусто" body="Нет данных" />);
    const status = screen.getByTestId('empty-state');
    expect(status).toHaveTextContent('Пусто');
    expect(status).toHaveTextContent('Нет данных');
  });

  it('ErrorState exposes an alert and retry action', async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new Error('boom')} onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('Table renders a caption, scoped headers and cells', () => {
    render(
      <Table
        caption="Задачи"
        columns={[
          { key: 'id', header: 'ID', cell: (r: { id: string }) => r.id },
          { key: 't', header: 'Название', cell: (r: { id: string; t: string }) => r.t },
        ]}
        rows={[{ id: 't1', t: 'Research' }]}
        rowKey={(r) => r.id}
      />,
    );
    expect(screen.getByText('Задачи')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'ID' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Research' })).toBeInTheDocument();
  });
});

describe('Tabs', () => {
  it('implements roving tabindex and arrow-key navigation', async () => {
    render(
      <Tabs
        items={[
          { id: 'a', label: 'A', content: <div>Panel A</div> },
          { id: 'b', label: 'B', content: <div>Panel B</div> },
        ]}
      />,
    );
    const tabA = screen.getByRole('tab', { name: 'A' });
    const tabB = screen.getByRole('tab', { name: 'B' });
    expect(tabA).toHaveAttribute('aria-selected', 'true');
    expect(tabA).toHaveAttribute('tabindex', '0');
    expect(tabB).toHaveAttribute('tabindex', '-1');
    expect(screen.getByText('Panel A')).toBeInTheDocument();

    tabA.focus();
    fireEvent.keyDown(tabA, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'B' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Panel B')).toBeInTheDocument();
  });
});

describe('Dialog', () => {
  it('is modal, labelled by its title, and closes on Escape', () => {
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} title="Подтверждение">
        <button type="button">ОК</button>
      </Dialog>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy as string)).toHaveTextContent('Подтверждение');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('renders nothing when closed', () => {
    render(
      <Dialog open={false} onClose={() => {}} title="X">
        body
      </Dialog>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('Tooltip', () => {
  it('shows on focus and links via aria-describedby', () => {
    render(
      <Tooltip label="Подсказка">
        <button type="button">Кнопка</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole('button', { name: 'Кнопка' });
    fireEvent.focus(trigger);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('Подсказка');
    expect(trigger.closest('[aria-describedby]')).toHaveAttribute('aria-describedby', tooltip.id);
  });
});

function ToastTrigger() {
  const { notify } = useToast();
  return (
    <div>
      <button type="button" onClick={() => notify({ title: 'Готово', message: 'Сохранено', tone: 'success' })}>
        ok
      </button>
      <button type="button" onClick={() => notify({ title: 'Сбой', tone: 'error' })}>
        err
      </button>
    </div>
  );
}

describe('ToastProvider', () => {
  it('has a labelled polite live region and renders notifications by tone', async () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );
    expect(screen.getByRole('region', { name: 'Уведомления' })).toHaveAttribute('aria-live', 'polite');

    await userEvent.click(screen.getByRole('button', { name: 'ok' }));
    expect(screen.getByRole('status')).toHaveTextContent('Сохранено');

    await userEvent.click(screen.getByRole('button', { name: 'err' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Сбой');
  });

  it('throws when useToast is used outside the provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<ToastTrigger />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });
});

describe('layout primitives', () => {
  it('Stack and Grid render their children', () => {
    render(
      <Stack gap={3}>
        <Grid min="auto">
          <div>one</div>
          <div>two</div>
        </Grid>
      </Stack>,
    );
    expect(screen.getByText('one')).toBeInTheDocument();
    expect(screen.getByText('two')).toBeInTheDocument();
  });
});
