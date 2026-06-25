import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

class OpenApiImportPage {
  constructor(private readonly page: Page) {}

  async routeApi(path: string, handler: (route: Route) => void | Promise<void>) {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    await Promise.all(API_PREFIXES.map(prefix => this.page.route(`${prefix}${normalizedPath}`, handler)));
  }

  async mockBackend(
    capturedBodies: unknown[],
    historyItems?: Array<Record<string, unknown>>,
    historyMode = 'plan_and_tests',
    jobsHandler?: (route: Route) => void | Promise<void>,
  ) {
    const defaultHistoryItems = [
      {
        id: 'oai-e2e',
        job_id: 'job-history-e2e',
        source_type: 'url',
        source_url: 'http://localhost:8001/openapi.json',
        base_url: 'http://localhost:8001',
        feature_filter: null,
        method_filter: [],
        mode: historyMode,
        status: 'completed',
        files_generated: 0,
        generated_paths: [],
        evidence_paths: [],
        spec_paths: ['specs/generated/api/users-operations.md'],
        test_paths: ['tests/generated/openapi-users-operations.api.spec.ts'],
        matched_operations: 2,
        executed_operations: 0,
        blocked_operations: [
          { method: 'GET', path: '/users/{id}', reason: "missing required path parameter 'id'" },
        ],
        failed_operations: [],
        skipped_operations: 0,
        chunk_count: 1,
        recommended_mode: 'plan_and_tests',
        recommended_next_action: 'Review generated tests and run the API test suite.',
        warnings: ['1 operation(s) were blocked because required input could not be generated.'],
        created_at: '2026-06-01T09:00:00Z',
        completed_at: '2026-06-01T09:00:03Z',
      },
    ];
    await this.routeApi('/auth/refresh', route =>
      route.fulfill({ status: 200, json: { access_token: 'access-token', refresh_token: 'refresh-token' } }),
    );
    await this.routeApi('/auth/me', route =>
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
    await this.routeApi('/projects', route =>
      route.fulfill({
        status: 200,
        json: {
          projects: [
            {
              id: 'default',
              name: 'Default',
              base_url: 'https://example.test',
              created_at: '2026-06-01T09:00:00',
              spec_count: 0,
              run_count: 0,
              batch_count: 0,
            },
          ],
        },
      }),
    );
    await this.routeApi('/api-testing/specs?*', route =>
      route.fulfill({
        status: 200,
        json: {
          items: [],
          total: 0,
          has_more: false,
          folders: [],
          summary: {
            total_specs: 0,
            with_tests: 0,
            passed: 0,
            failed: 0,
            not_run: 0,
            no_tests: 0,
            total_defined_cases: 0,
            total_generated_tests: 0,
            coverage_pct: 0,
          },
        },
      }),
    );
    const jobsListHandler = jobsHandler || (route => route.fulfill({ status: 200, json: [] }));
    await this.routeApi('/api-testing/jobs', jobsListHandler);
    await this.routeApi('/api-testing/jobs?*', jobsListHandler);
    await this.routeApi('/api-testing/runs/latest-by-spec?*', route => route.fulfill({ status: 200, json: { specs: {} } }));
    const importHistoryHandler = (route: Route) =>
      route.fulfill({
        status: 200,
        json: {
          total: (historyItems || defaultHistoryItems).length,
          has_more: false,
          items: historyItems || defaultHistoryItems,
        },
      });
    await this.routeApi('/api-testing/import-history', importHistoryHandler);
    await this.routeApi('/api-testing/import-history?*', importHistoryHandler);
    const importOpenApiHandler = async (route: Route) => {
      capturedBodies.push(route.request().postDataJSON());
      await route.fulfill({
        status: 200,
        json: {
          job_id: 'job-e2e',
          status: 'running',
          message: 'OpenAPI import started',
        },
      });
    };
    await this.routeApi('/api-testing/import-openapi', importOpenApiHandler);
    await this.routeApi('/api-testing/import-openapi?*', importOpenApiHandler);
    await this.routeApi('/api-testing/jobs/job-e2e', route =>
      route.fulfill({
        status: 200,
        json: {
          job_id: 'job-e2e',
          status: 'completed',
          type: 'openapi_import',
          message: 'Matched 2 operation(s), generated 1 spec(s) and 1 test file(s)',
          result: {
            matched_operations: 2,
            executed_operations: 0,
            blocked_operations: [
              { method: 'GET', path: '/users/{id}', reason: "missing required path parameter 'id'" },
            ],
            evidence_paths: [],
            spec_paths: ['specs/generated/api/users-operations.md'],
            test_paths: ['tests/generated/openapi-users-operations.api.spec.ts'],
            files: ['tests/generated/openapi-users-operations.api.spec.ts'],
          },
        },
      }),
    );
  }

  async open() {
    await this.page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });
    await this.page.goto('/api-testing');
    await this.page.getByRole('button', { name: /OpenAPI Import/ }).click();
    await expect(this.page.getByRole('heading', { name: 'Import OpenAPI / Swagger Specification' })).toBeVisible();
  }
}

test.describe('OpenAPI import plan and tests', () => {
  test.describe.configure({ mode: 'serial' });

  test('defaults imports to plan_and_tests and keeps history compact', async ({ page }) => {
    const capturedBodies: unknown[] = [];
    const importPage = new OpenApiImportPage(page);
    await importPage.mockBackend(capturedBodies);
    await importPage.open();

    await page.getByPlaceholder('https://api.example.com/openapi.json').fill('http://localhost:8001/openapi.json');
    await expect(page.getByPlaceholder('http://localhost:8001')).toHaveValue('http://localhost:8001');
    await page.getByRole('button', { name: 'Import & Generate Tests' }).click();

    await expect.poll(() => capturedBodies.length).toBe(1);
    expect(capturedBodies[0]).toMatchObject({
      url: 'http://localhost:8001/openapi.json',
      base_url: 'http://localhost:8001',
      mode: 'plan_and_tests',
      project_id: 'default',
    });

    await expect(page.getByText('OpenAPI import and test generation started')).toBeVisible();
    await expect(page.getByText('Blocked operations')).toHaveCount(0);
    await page.getByRole('button', { name: /Details/ }).click();
    await expect(page.getByText('users-operations.md')).toBeVisible();
    await expect(page.getByText('openapi-users-operations.api.spec.ts')).toBeVisible();
    await expect(page.getByText('Blocked operations')).toBeVisible();
    await expect(page.getByText(/GET \/users\/\{id\}/)).toBeVisible();
  });

  test('re-import ignores unsupported historical modes', async ({ page }) => {
    const capturedBodies: unknown[] = [];
    const importPage = new OpenApiImportPage(page);
    await importPage.mockBackend(capturedBodies, undefined, 'retired_mode');
    await importPage.open();

    await page.getByRole('button', { name: 'Re-import' }).click();

    await expect.poll(() => capturedBodies.length).toBe(1);
    expect(capturedBodies[0]).toMatchObject({
      url: 'http://localhost:8001/openapi.json',
      base_url: 'http://localhost:8001',
      mode: 'plan_and_tests',
      project_id: 'default',
    });
  });

  test('uses settings for missing-input history before re-importing', async ({ page }) => {
    const capturedBodies: unknown[] = [];
    const importPage = new OpenApiImportPage(page);
    await importPage.mockBackend(capturedBodies, [
      {
        id: 'oai-needs-input',
        job_id: 'job-needs-input',
        source_type: 'url',
        source_url: 'https://service.example.test/openapi.json',
        base_url: null,
        feature_filter: 'users',
        method_filter: [],
        mode: 'plan_and_tests',
        status: 'needs_input',
        needs_input: true,
        missing_fields: ['base_url'],
        files_generated: 0,
        generated_paths: [],
        evidence_paths: [],
        spec_paths: [],
        test_paths: [],
        matched_operations: 2,
        executed_operations: 0,
        blocked_operations: [],
        failed_operations: [],
        skipped_operations: 0,
        chunk_count: 1,
        recommended_mode: 'plan_and_tests',
        recommended_next_action: 'Enter API Server URL and re-import.',
        warnings: [],
        diagnostics: {},
        created_at: '2026-06-01T09:00:00Z',
        completed_at: '2026-06-01T09:00:03Z',
      },
    ]);
    await importPage.open();

    await page.getByRole('button', { name: /Use settings/ }).click();

    await expect(page.getByLabel('OpenAPI Spec URL')).toHaveValue('https://service.example.test/openapi.json');
    await expect(page.getByLabel('Feature Filter (optional)')).toHaveValue('users');
    await expect(page.getByLabel('API Server URL')).toBeFocused();
    expect(capturedBodies).toHaveLength(0);

    await page.getByLabel('API Server URL').fill('https://service.example.test');
    await page.getByRole('button', { name: 'Import & Generate Tests' }).click();
    await expect.poll(() => capturedBodies.length).toBe(1);
    expect(capturedBodies[0]).toMatchObject({
      url: 'https://service.example.test/openapi.json',
      base_url: 'https://service.example.test',
      feature_filter: 'users',
      mode: 'plan_and_tests',
      project_id: 'default',
    });
  });

  test('shows expired running history as failed with actionable details', async ({ page }) => {
    const capturedBodies: unknown[] = [];
    const importPage = new OpenApiImportPage(page);
    await importPage.mockBackend(capturedBodies, [
      {
        id: 'oai-expired',
        job_id: 'job-expired',
        source_type: 'url',
        source_url: 'https://service.example.test/openapi.json',
        base_url: 'https://service.example.test',
        feature_filter: null,
        method_filter: [],
        mode: 'plan_and_tests',
        status: 'failed',
        needs_input: false,
        missing_fields: [],
        files_generated: 0,
        generated_paths: [],
        evidence_paths: [],
        spec_paths: [],
        test_paths: [],
        matched_operations: 0,
        executed_operations: 0,
        blocked_operations: [],
        failed_operations: [],
        skipped_operations: 0,
        chunk_count: 0,
        recommended_mode: 'plan_and_tests',
        recommended_next_action: null,
        warnings: [],
        diagnostics: {},
        error_message: 'Import status expired before completion; re-import to retry.',
        created_at: '2026-06-01T06:00:00Z',
        completed_at: '2026-06-01T09:00:00Z',
      },
    ]);
    await importPage.open();

    await expect(page.locator('div').filter({ hasText: /^Failed$/ }).first()).toBeVisible();
    await expect(page.getByText('Import status expired before completion; re-import to retry.')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Import Jobs' })).toHaveCount(0);
  });

  test('clears stale running jobs after backend reports none', async ({ page }) => {
    const capturedBodies: unknown[] = [];
    const importPage = new OpenApiImportPage(page);
    let returnRunningJobs = true;
    await importPage.mockBackend(capturedBodies, undefined, 'plan_and_tests', route => {
      return route.fulfill({
        status: 200,
        json: returnRunningJobs
          ? [
              {
                job_id: 'stale-batch',
                status: 'running',
                stage: 'batch',
                message: 'Batch direct run started with 1 generated test(s)',
                result: { child_job_ids: ['completed-child'] },
                project_id: 'default',
              },
            ]
          : [],
      });
    });
    await importPage.open();

    await expect(page.getByText('Jobs running...')).toBeVisible();
    returnRunningJobs = false;
    await page.reload();
    await expect(page.getByText('Jobs running...')).toHaveCount(0);
  });
});
