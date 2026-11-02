/**
 * Tabs — WAI-ARIA tabs pattern (ADR-110 §3.2, R5).
 *
 * Implements roving tabindex: only the active tab is in the tab order, and
 * Left/Right/Home/End arrows move focus and selection. Each panel is associated
 * with its tab via `aria-controls` / `aria-labelledby`.
 */

import { useId, useRef, useState, type ReactNode } from 'react';

import styles from './nav.module.css';

export interface TabItem {
  id: string;
  label: string;
  content: ReactNode;
}

export interface TabsProps {
  items: TabItem[];
  /** Controlled active tab id (uncontrolled when omitted). */
  value?: string;
  onChange?: (id: string) => void;
  label?: string;
}

export function Tabs({ items, value, onChange, label = 'Разделы' }: TabsProps) {
  const [internal, setInternal] = useState(items[0]?.id);
  const active = value ?? internal;
  const baseId = useId();
  const listRef = useRef<HTMLDivElement>(null);

  function select(id: string) {
    if (value === undefined) setInternal(id);
    onChange?.(id);
  }

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const order = { ArrowRight: 1, ArrowLeft: -1, Home: -index, End: items.length - 1 - index };
    const delta = order[event.key as keyof typeof order];
    if (delta === undefined) return;
    event.preventDefault();
    const next = items[(index + delta + items.length) % items.length];
    select(next.id);
    listRef.current?.querySelectorAll<HTMLElement>('[role="tab"]')[((index + delta + items.length) % items.length)]?.focus();
  }

  const activeItem = items.find((item) => item.id === active) ?? items[0];

  return (
    <div>
      <div ref={listRef} role="tablist" aria-label={label} className={styles.tablist}>
        {items.map((item, index) => {
          const selected = item.id === activeItem?.id;
          return (
            <button
              key={item.id}
              role="tab"
              id={`${baseId}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              className={styles.tab}
              onClick={() => select(item.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {activeItem ? (
        <div
          role="tabpanel"
          id={`${baseId}-panel-${activeItem.id}`}
          aria-labelledby={`${baseId}-tab-${activeItem.id}`}
          tabIndex={0}
        >
          {activeItem.content}
        </div>
      ) : null}
    </div>
  );
}
