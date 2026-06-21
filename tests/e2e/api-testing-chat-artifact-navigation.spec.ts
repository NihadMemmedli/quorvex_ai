import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

async function routeApi(page: Page, path: string, handler: (route: Route) => void | Promise<void>) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  await Promise.all(API_PREFIXES.map(prefix => page.route(`${prefix}${normalizedPath}`, handler)));
}

test('opens chat-generated API specs in the correct project scope', async ({ page }) => {
  const specRequests: URL[] = [];

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
        created_at: '2026-06-01T09:00:00',
        last_login: null,
      },
    }),
  );
  await routeApi(page, '/projects', route =>
    route.fulfill({
      status: 200,
      json: {
        projects: [
          {
            id: 'default',
            name: 'Default',
            base_url: 'https://default.example.test',
            created_at: '2026-06-01T09:00:00',
            spec_count: 0,
            run_count: 0,
            batch_count: 0,
          },
          {
            id: 'project-a',
            name: 'Project A',
            base_url: 'https://api.example.test',
            created_at: '2026-06-01T09:00:00',
            spec_count: 1,
            run_count: 0,
            batch_count: 0,
          },
        ],
      },
    }),
  );
  await routeApi(page, '/api-testing/specs?*', route => {
    const url = new URL(route.request().url());
    specRequests.push(url);
    const projectId = url.searchParams.get('project_id');
    const search = url.searchParams.get('search') || '';
    const shouldReturnSpec = projectId === 'project-a' && search === 'products-api-demo.md';
    return route.fulfill({
      status: 200,
      json: {
        items: shouldReturnSpec ? [{
          name: 'products-api-demo.md',
          path: 'specs/project-a/api/products-api-demo.md',
          spec_type: 'api',
          has_generated_test: true,
          generated_test_path: 'tests/generated/project-a/products-api-demo.api.spec.ts',
          generated_tests: [{
            name: 'products-api-demo.api.spec.ts',
            path: 'tests/generated/project-a/products-api-demo.api.spec.ts',
            test_count: 5,
          }],
          file_count: 1,
          test_count: 5,
          defined_cases: 5,
          folder: 'api',
          last_run_status: null,
          last_run_at: null,
          tags: [],
        }] : [],
        total: shouldReturnSpec ? 1 : 0,
        has_more: false,
        folders: shouldReturnSpec ? ['api'] : [],
        summary: {
          total_specs: shouldReturnSpec ? 1 : 0,
          with_tests: shouldReturnSpec ? 1 : 0,
          passed: 0,
          failed: 0,
          not_run: shouldReturnSpec ? 1 : 0,
          no_tests: 0,
          total_defined_cases: shouldReturnSpec ? 5 : 0,
          total_generated_tests: shouldReturnSpec ? 5 : 0,
          coverage_pct: shouldReturnSpec ? 100 : 0,
        },
      },
    });
  });
  await routeApi(page, '/api-testing/jobs?*', route => route.fulfill({ status: 200, json: [] }));
  await routeApi(page, '/api-testing/runs/latest-by-spec?*', route => route.fulfill({ status: 200, json: { specs: {} } }));

  await page.addInitScript(() => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', 'default');
  });

  await page.goto('/api-testing?project_id=project-a&tab=specs&spec=products-api-demo.md');

  await expect(page.getByRole('heading', { name: 'API Testing' })).toBeVisible();
  await expect(page.getByText('products-api-demo.md')).toBeVisible();
  await expect(page.getByPlaceholder('Search specs...')).toHaveValue('products-api-demo.md');
  await expect.poll(() => specRequests.some(url =>
    url.searchParams.get('project_id') === 'project-a'
    && url.searchParams.get('search') === 'products-api-demo.md',
  )).toBe(true);
});
