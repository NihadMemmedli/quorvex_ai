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

type DashboardMockOptions = {
  dashboard?: Record<string, unknown>;
  sessions?: Array<Record<string, unknown>>;
  queue?: Record<string, unknown>;
  pendingQuestionsBySession?: Record<string, Array<Record<string, unknown>>>;
};

async function routeApi(page: Page, pathGlob: string, handler: (route: Route) => void | Promise<void>) {
  const normalizedPath = pathGlob.startsWith('/') ? pathGlob : `/${pathGlob}`;
  await Promise.all(API_PREFIXES.map(prefix => page.route(`${prefix}${normalizedPath}`, handler)));
}

async function mockDashboardBackend(page: Page, options: DashboardMockOptions = {}) {
  const dashboard = {
    total_specs: 4,
    total_runs: 3,
    success_rate: 100,
    pass_rate: 100,
    avg_duration_seconds: 12,
    flaky_test_count: 0,
    last_run: '2026-06-07T10:00:00',
    last_run_at: '2026-06-07T10:00:00',
    ...options.dashboard,
  };
  const sessions = options.sessions ?? [];
  const queue = {
    mode: 'temporal',
    active: 0,
    queued: 0,
    orphaned_tasks: 0,
    stale_running: 0,
    temporal: { available: true, worker_pollers: { workflow: 1, activity: 1 } },
    running_tasks: [],
    ...options.queue,
  };
  const pendingQuestionsBySession = options.pendingQuestionsBySession ?? {};

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
      json: dashboard,
    }),
  );
  await routeApi(page, '/autopilot/sessions**', route => route.fulfill({ status: 200, json: sessions }));
  await routeApi(page, '/autopilot/**/questions**', route => {
    const sessionId = new URL(route.request().url()).pathname.match(/\/autopilot\/([^/]+)\/questions/)?.[1] ?? '';
    route.fulfill({ status: 200, json: pendingQuestionsBySession[sessionId] ?? [] });
  });
  await routeApi(page, '/api/agents/queue-status**', route =>
    route.fulfill({
      status: 200,
      json: queue,
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
    await expect(page.getByRole('heading', { name: 'Top Risks' })).toHaveCount(0);

    const signalsPanel = page.getByRole('region', { name: 'Quality Signals' });
    await expect(signalsPanel.getByText('RTM coverage', { exact: true })).toHaveCount(1);
    await expect(signalsPanel.getByText('RTM gaps', { exact: true })).toHaveCount(0);

    const rtmCoverageLink = signalsPanel.getByRole('link', { name: /RTM coverage/i });
    await expect(rtmCoverageLink).toHaveAttribute('href', '/rtm?coverage_status=uncovered');
    await rtmCoverageLink.focus();
    await rtmCoverageLink.press('Enter');

    await expect(page).toHaveURL(/\/rtm\?coverage_status=uncovered$/);
    await expect(page.getByRole('heading', { name: 'RTM' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'uncovered', exact: true })).toHaveAttribute('aria-pressed', 'true');
  });

  test('renders every dashboard signal once when multiple risks are active', async ({ page }) => {
    await mockDashboardBackend(page, {
      dashboard: {
        total_runs: 6,
        success_rate: 55,
        pass_rate: 55,
        flaky_test_count: 3,
      },
      sessions: [
        {
          id: 'failed-1',
          project_id: 'default',
          entry_urls: ['https://example.test/checkout'],
          status: 'failed',
          current_phase: 'test_execution',
          overall_progress: 100,
          current_phase_progress: 100,
          total_pages_discovered: 2,
          total_flows_discovered: 1,
          total_requirements_generated: 0,
          total_specs_generated: 1,
          total_tests_generated: 4,
          total_tests_passed: 2,
          total_tests_failed: 2,
          error_message: 'Generated checkout tests failed',
          created_at: '2026-06-07T09:00:00',
          started_at: '2026-06-07T09:01:00',
          completed_at: '2026-06-07T09:05:00',
        },
        {
          id: 'awaiting-1',
          project_id: 'default',
          entry_urls: ['https://example.test/review'],
          status: 'awaiting_input',
          current_phase: 'review_gate',
          overall_progress: 70,
          current_phase_progress: 50,
          total_pages_discovered: 3,
          total_flows_discovered: 1,
          total_requirements_generated: 1,
          total_specs_generated: 1,
          total_tests_generated: 2,
          total_tests_passed: 2,
          total_tests_failed: 0,
          error_message: null,
          created_at: '2026-06-07T11:00:00',
          started_at: '2026-06-07T11:01:00',
          completed_at: null,
        },
      ],
      queue: {
        mode: 'temporal',
        active: 1,
        queued: 2,
        orphaned_tasks: 1,
        stale_running: 1,
        temporal: { available: true, worker_pollers: { workflow: 1, activity: 1 } },
        running_tasks: [],
      },
      pendingQuestionsBySession: {
        'awaiting-1': [
          {
            id: 7,
            session_id: 'awaiting-1',
            phase_name: 'review_gate',
            question_text: 'Approve generated checkout assertions?',
            status: 'pending',
            auto_continue_at: null,
          },
        ],
      },
    });
    await page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Quality Overview' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Top Risks' })).toHaveCount(0);

    const signalsPanel = page.getByRole('region', { name: 'Quality Signals' });
    const signalLabels = [
      'Failed generated tests',
      'Pass rate',
      'Flaky tests',
      'Pending review gates',
      'RTM coverage',
      'Automation confidence',
      'Recent run age',
    ];
    for (const label of signalLabels) {
      await expect(signalsPanel.getByText(label, { exact: true })).toHaveCount(1);
      await expect(page.getByText(label, { exact: true })).toHaveCount(1);
    }
    await expect(signalsPanel.getByText('RTM gaps', { exact: true })).toHaveCount(0);
    await expect(signalsPanel.getByRole('link', { name: /Failed generated tests/i })).toHaveAttribute('href', /\/autopilot\?sessionId=failed-1$/);
    await expect(signalsPanel.getByRole('link', { name: /Flaky tests/i })).toHaveAttribute('href', '/analytics');
    await expect(signalsPanel.getByRole('link', { name: /RTM coverage/i })).toHaveAttribute('href', '/rtm?coverage_status=uncovered');
    await expect(signalsPanel.getByRole('link', { name: /Automation confidence/i })).toHaveAttribute('href', '/workflow');
  });
});
