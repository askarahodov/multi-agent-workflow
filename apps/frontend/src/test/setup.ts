import '@testing-library/jest-dom/vitest';

// jsdom does not implement ResizeObserver, which @xyflow/react (the workflow
// canvas) requires at render time. Without a stub the editor and MVP-shell
// tests crash with "ResizeObserver is not defined" before any assertion runs.
if (typeof ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
