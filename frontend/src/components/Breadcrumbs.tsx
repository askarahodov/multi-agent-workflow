/** Breadcrumbs — navigation trail with a labelled nav landmark. */

import styles from './nav.module.css';

export interface Crumb {
  label: string;
  onClick?: () => void;
}

export function Breadcrumbs({ items, label = 'Хлебные крошки' }: { items: Crumb[]; label?: string }) {
  return (
    <nav aria-label={label}>
      <ol className={styles.breadcrumbs}>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className={styles.breadcrumbItem}>
              {isLast || !item.onClick ? (
                <span
                  className={isLast ? styles.breadcrumbCurrent : undefined}
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </span>
              ) : (
                <button type="button" className={styles.tab} onClick={item.onClick}>
                  {item.label}
                </button>
              )}
              {!isLast ? (
                <span className={styles.breadcrumbSep} aria-hidden="true">
                  /
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
