import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

const PROJECT = {
  id: 'default',
  name: 'Default',
  base_url: 'https://example.test',
  created_at: '2026-06-07T10:00:00',
  spec_count: 8,
  run_count: 4,
  batch_count: 0,
};

async function routeApi(page: Page, pathGlob: string, handler: (route: Route) => void | Promise<void>) {
  const normalizedPath = pathGlob.startsWith('/') ? pathGlob : `/${pathGlob}`;
  await Promise.all(API_PREFIXES.map(prefix => page.route(`${prefix}${normalizedPath}`, handler)));
}

async function mockShell(page: Page) {
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
  await routeApi(page, '/api/agents/queue-status**', route => route.fulfill({ status: 200, json: { active: 0, queued: 0, running_tasks: [] } }));
  await routeApi(page, '/chat/project-context**', route => route.fulfill({ status: 200, json: {} }));
  await routeApi(page, '/chat/conversations**', route => route.fulfill({ status: 200, json: [] }));
}

async function openCoverage(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', 'default');
  });
  await page.goto('/coverage');
}

test.describe('Coverage Intelligence', () => {
  test('renders RTM, discovered app, and execution coverage as separate lenses', async ({ page }) => {
    await mockShell(page);
    await routeApi(page, '/api/memory/projects', route =>
      route.fulfill({ status: 200, json: { projects: [{ id: 'default', name: 'Default', pattern_count: 12 }] } }),
    );
    await routeApi(page, '/api/memory/coverage/gaps**', route =>
      route.fulfill({
        status: 200,
        json: [
          {
            type: 'untested_element',
            element_id: 'el-1',
            element_type: 'button',
            url: 'https://example.test/checkout',
            description: 'Checkout button has no test coverage',
            priority: 'high',
          },
        ],
      }),
    );
    await routeApi(page, '/api/memory/coverage/suggestions**', route =>
      route.fulfill({
        status: 200,
        json: [
          {
            title: 'Cover checkout CTA',
            description: 'Create a test for checkout CTA behavior.',
            type: 'element',
            priority: 'medium',
            suggested_steps: ['Click checkout'],
          },
        ],
      }),
    );
    await routeApi(page, '/api/memory/coverage/summary**', route =>
      route.fulfill({
        status: 200,
        json: {
          total_patterns: 12,
          graph_stats: { page_count: 3, element_count: 18, flow_count: 4, total_nodes: 25, total_edges: 31 },
        },
      }),
    );
    await routeApi(page, '/rtm/coverage**', route =>
      route.fulfill({
        status: 200,
        json: { total_requirements: 10, covered: 4, partial: 2, uncovered: 4, coverage_percentage: 40 },
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
    await routeApi(page, '/rtm?**', route =>
      route.fulfill({
        status: 200,
        json: {
          items: [{ id: 102, code: 'REQ-102', title: 'Checkout partial mapping', category: 'forms', priority: 'medium', coverage_status: 'partial' }],
          total: 1,
          has_more: false,
          summary: { total_requirements: 10, covered: 4, partial: 2, uncovered: 4, coverage_percentage: 40 },
        },
      }),
    );
    await routeApi(page, '/analytics/coverage-overview**', route =>
      route.fulfill({
        status: 200,
        json: { total_specs: 8, total_test_files: 5, specs_with_tests: 5, specs_run_at_least_once: 3, run_coverage_percent: 37.5, tags_distribution: [] },
      }),
    );

    await openCoverage(page);

    await expect(page.getByRole('heading', { name: 'Coverage Intelligence' })).toBeVisible();
    await expect(page.getByText('RTM Requirement Coverage')).toBeVisible();
    await expect(page.getByText('Discovered App Coverage')).toBeVisible();
    await expect(page.getByText('Execution Coverage')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Primary Queue' })).toBeVisible();
    await expect(page.getByText('Checkout requires confirmation')).toBeVisible();
    await expect(page.getByText('Checkout button has no test coverage')).toBeVisible();
    await expect(page.getByText('3 of 8 specs have run at least once')).toBeVisible();
  });

  test('distinguishes empty requirement, memory, and execution states', async ({ page }) => {
    await mockShell(page);
    await routeApi(page, '/api/memory/projects', route =>
      route.fulfill({ status: 200, json: { projects: [{ id: 'default', name: 'Default', pattern_count: 0 }] } }),
    );
    await routeApi(page, '/api/memory/coverage/gaps**', route => route.fulfill({ status: 200, json: [] }));
    await routeApi(page, '/api/memory/coverage/suggestions**', route => route.fulfill({ status: 200, json: [] }));
    await routeApi(page, '/api/memory/coverage/summary**', route =>
      route.fulfill({ status: 200, json: { total_patterns: 0, graph_stats: { page_count: 0, element_count: 0, flow_count: 0, total_nodes: 0, total_edges: 0 } } }),
    );
    await routeApi(page, '/rtm/coverage**', route =>
      route.fulfill({ status: 200, json: { total_requirements: 0, covered: 0, partial: 0, uncovered: 0, coverage_percentage: 0 } }),
    );
    await routeApi(page, '/rtm/gaps**', route => route.fulfill({ status: 200, json: [] }));
    await routeApi(page, '/rtm?**', route =>
      route.fulfill({ status: 200, json: { items: [], total: 0, has_more: false, summary: { total_requirements: 0, covered: 0, partial: 0, uncovered: 0, coverage_percentage: 0 } } }),
    );
    await routeApi(page, '/analytics/coverage-overview**', route =>
      route.fulfill({ status: 200, json: { total_specs: 0, total_test_files: 0, specs_with_tests: 0, specs_run_at_least_once: 0, run_coverage_percent: 0, tags_distribution: [] } }),
    );

    await openCoverage(page);

    await expect(page.getByText('No requirements yet')).toHaveCount(2);
    await expect(page.getByText('No memory gaps')).toHaveCount(2);
    await expect(page.getByText('No executed specs data')).toBeVisible();
  });
});
