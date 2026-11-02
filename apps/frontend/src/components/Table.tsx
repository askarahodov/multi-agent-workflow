/** Table — semantic, scrollable data table (ADR-110 §3.2). */

import type { ReactNode } from 'react';

import styles from './surfaces.module.css';

export interface Column<T> {
  /** Stable key for React and the column header. */
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Align the column (defaults to start). */
  align?: 'start' | 'end' | 'center';
}

export interface TableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  caption?: string;
  /** Accessible label when no visible caption is shown. */
  ariaLabel?: string;
}

export function Table<T>({ columns, rows, rowKey, caption, ariaLabel }: TableProps<T>) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} aria-label={ariaLabel}>
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" style={{ textAlign: column.align ?? 'start' }}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} style={{ textAlign: column.align ?? 'start' }}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
