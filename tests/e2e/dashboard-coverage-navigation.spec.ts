import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

const PROJECT = {
  id: 'default',
  name: 'Default',
  base_url: 'https://example.test',
  created_at: '2026-06-07T10:00:00',
  spec_count: 4,
  run_count: 3,
  batch_count: 0,
};

async function routeApi(page: Page, pathGlob: string, handler: (route: Route) => void | Promise<void>) {
  const normalizedPath = pathGlob.startsWith('/') ? pathGlob : `/${pathGlob}`;
  await Promise.all(API_PREFIXES.map(prefix => page.route(`${prefix}${normalizedPath}`, handler)));
}

async function mockDashboardBackend(page: Page) {
  await routeApi(page, '/auth/refresh', route =>
    route.fulfill({ status: 200, json: { access_token: 'access-token', refresh_token: 'refresh-token' } }),
  );
  await routeApi(page, '/auth/me', route =>
    route.fulfill({
      status: 200,
      json: {
        id: 'user-1',
        email: 'qa@example.com',
        full_name: 'QA User',
        is_active: true,
        is_superuser: true,
        email_verified: true,
        created_at: '2026-06-07T10:00:00',
        last_login: null,
      },
    }),
  );
  await routeApi(page, '/projects', route => route.fulfill({ status: 200, json: { projects: [PROJECT] } }));
  await routeApi(page, '/dashboard**', route =>
    route.fulfill({
      status: 200,
      json: {
        total_specs: 4,
        total_runs: 3,
        success_rate: 100,
        pass_rate: 100,
        avg_duration_seconds: 12,
        flaky_test_count: 0,
        last_run: '2026-06-07T10:00:00',
        last_run_at: '2026-06-07T10:00:00',
      },
    }),
  );
  await routeApi(page, '/autopilot/sessions**', route => route.fulfill({ status: 200, json: [] }));
  await routeApi(page, '/api/agents/queue-status**', route =>
    route.fulfill({
      status: 200,
      json: {
        mode: 'temporal',
        active: 0,
        queued: 0,
        orphaned_tasks: 0,
        stale_running: 0,
        temporal: { available: true, worker_pollers: { workflow: 1, activity: 1 } },
        running_tasks: [],
      },
    }),
  );
  await routeApi(page, '/exploration**', route => route.fulfill({ status: 200, json: [] }));
  await routeApi(page, '/requirements/stats**', route => route.fulfill({ status: 200, json: { total: 10 } }));
  await routeApi(page, '/rtm/coverage**', route =>
    route.fulfill({
      status: 200,
      json: {
        total_requirements: 10,
        covered: 4,
        partial: 1,
        uncovered: 5,
        coverage_percentage: 40,
      },
    }),
  );
  await routeApi(page, '/rtm/gaps**', route =>
    route.fulfill({
      status: 200,
      json: [
        {
          requirement_id: 101,
          requirement_code: 'REQ-101',
          title: 'Checkout requires confirmation',
          category: 'forms',
          priority: 'high',
          suggested_test: { description: 'Verify checkout confirmation.', steps: ['Open checkout', 'Confirm order'] },
        },
      ],
    }),
  );
  await routeApi(page, '/rtm/trend**', route => route.fulfill({ status: 200, json: [] }));
  await routeApi(page, '/rtm?**', route =>
    route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: 101,
            code: 'REQ-101',
            title: 'Checkout requires confirmation',
            description: null,
            category: 'forms',
            priority: 'high',
            status: 'approved',
            acceptance_criteria: [],
            tests: [],
            coverage_status: 'uncovered',
          },
        ],
        total: 1,
        has_more: false,
        summary: {
          total_requirements: 10,
          covered: 4,
          partial: 1,
          uncovered: 5,
          coverage_percentage: 40,
        },
      },
    }),
  );
}

test.describe('Dashboard coverage navigation', () => {
  test('opens RTM uncovered requirements from the Quality Signals coverage row', async ({ page }) => {
    await mockDashboardBackend(page);
    await page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Quality Overview' })).toBeVisible();

    await page.getByRole('link', { name: /RTM gaps/i }).click();

    await expect(page).toHaveURL(/\/rtm\?coverage_status=uncovered$/);
    await expect(page.getByRole('heading', { name: 'RTM' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'uncovered' })).toHaveAttribute('aria-pressed', 'true');
  });
});
