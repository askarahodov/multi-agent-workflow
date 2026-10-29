import { test, expect } from '@playwright/test';

/**
 * Browser end-to-end: the live run journey over a real WebSocket.
 *
 * The app is served by the Playwright `webServer` (production build). The
 * orchestration backend is stubbed at the HTTP boundary (`page.route`) and the
 * run event channel at the WebSocket boundary (`page.routeWebSocket`), so the
 * test exercises the real React app, the real `RunEventStream` client and the
 * real reconnect logic in Chromium — not a unit-level fake.
 */

const RUN = {
  id: 'run-1',
  project_id: 'proj-1',
  name: 'Live run',
  status: 'running',
  version: 1,
};

function saga(id: number, event: string, extra: Record<string, unknown> = {}) {
  return {
    type: 'run_event',
    id,
    run_id: RUN.id,
    event,
    aggregate_type: 'task',
    aggregate_id: 'task-1',
    payload: {},
    created_at: new Date().toISOString(),
    ...extra,
  };
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/workflows/runs', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [RUN], next_cursor: null }),
    }),
  );
});

test('watches agents execute over the live WebSocket', async ({ page }) => {
  const connections: string[] = [];
  await page.routeWebSocket(/\/workflows\/runs\/.*\/ws/, (ws) => {
    connections.push(ws.url());
    ws.send(JSON.stringify(saga(1, 'run.launched', { aggregate_type: 'run', aggregate_id: RUN.id })));
    ws.send(JSON.stringify(saga(2, 'task.claimed')));
    ws.send(JSON.stringify(saga(3, 'task.completed', { payload: { summary: 'done' } })));
  });

  await page.goto('/');
  await page.getByTestId('nav-agent-log').click();
  await page.getByTestId('log-run-select').selectOption(RUN.id);

  // The stream opened and delivered the lifecycle events into the live feed.
  await expect(page.getByTestId('log-stream-status')).toHaveText('В реальном времени');
  const entries = page.getByTestId('agent-log-entry');
  await expect(entries).toHaveCount(3);
  await expect(page.getByText(/task\.completed task-1: done/)).toBeVisible();
  expect(connections[0]).toContain(`/workflows/runs/${RUN.id}/ws`);
});

test('recovers from a network blip and resumes from the last event id', async ({ page }) => {
  const connections: string[] = [];
  let dropped = false;
  await page.routeWebSocket(/\/workflows\/runs\/.*\/ws/, (ws) => {
    connections.push(ws.url());
    if (connections.length === 1) {
      ws.send(JSON.stringify(saga(10, 'run.launched', { aggregate_type: 'run', aggregate_id: RUN.id })));
      // Simulate the socket dropping mid-run.
      dropped = true;
      ws.close();
      return;
    }
    // Second connection must resume from the last delivered event id.
    ws.send(JSON.stringify(saga(11, 'task.completed', { payload: { summary: 'recovered' } })));
  });

  await page.goto('/');
  await page.getByTestId('nav-agent-log').click();
  await page.getByTestId('log-run-select').selectOption(RUN.id);

  // The first event arrived, then the stream reconnects and a second socket
  // opens with `after=10` — no duplicate of event 10.
  await expect(page.getByTestId('agent-log-entry')).toHaveCount(2);
  await expect(page.getByText(/task\.completed task-1: recovered/)).toBeVisible();
  expect(dropped).toBe(true);
  expect(connections.length).toBeGreaterThanOrEqual(2);
  expect(connections[1]).toContain('after=10');
});
