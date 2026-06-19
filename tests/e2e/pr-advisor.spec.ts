import { expect, Page, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

const analysis = {
  id: 'pria_e2e_42',
  project_id: 'default',
  provider: 'github',
  owner: 'NihadMemmedli',
  repo: 'quorvex_ai',
  pr_number: 42,
  title: 'Improve checkout validation',
  base_ref: 'main',
  head_ref: 'feature/checkout-validation',
  risk_level: 'medium',
  confidence: 'high',
  summary: 'Analyzed 2 changed files and recommended 2 of 7 automated tests with high confidence.',
  fallback_reason: null,
  changed_files_count: 2,
  selected_tests_count: 2,
  total_candidate_tests: 7,
  estimated_duration_seconds: 180,
  saved_tests_count: 5,
  category_summary: {
    changed_file_areas: {
      frontend_route: 1,
      test: 1,
    },
    selection_sources: {
      route_rule: 1,
      direct_spec: 1,
    },
  },
  repository_index_snapshot: 'ridx_e2e_42',
  batch_id: null,
  created_at: '2026-05-16T10:00:00',
  completed_at: '2026-05-16T10:00:01',
  changed_files: [
    {
      path: 'web/src/app/checkout/page.tsx',
      status: 'modified',
      additions: 22,
      deletions: 4,
      changes: 26,
      area: 'frontend_route',
      risk_level: 'medium',
      reason: 'Next.js route/page change',
    },
    {
      path: 'specs/checkout-validation.md',
      status: 'modified',
      additions: 8,
      deletions: 0,
      changes: 8,
      area: 'test',
      risk_level: 'low',
      reason: 'Test/spec change',
    },
  ],
  selected_tests: [
    {
      spec_name: 'checkout-validation.md',
      test_path: 'tests/generated/checkout-validation.spec.ts',
      reason: 'Changed spec file maps directly to this generated test',
      confidence: 'high',
      risk_level: 'medium',
      selection_source: 'direct_spec',
      estimated_duration_seconds: 90,
      tags: ['e2e'],
      categories: ['checkout'],
    },
    {
      spec_name: 'checkout-smoke.md',
      test_path: 'tests/generated/checkout-smoke.spec.ts',
      reason: "Route path 'checkout' matched spec name",
      confidence: 'high',
      risk_level: 'medium',
      selection_source: 'route_rule',
      estimated_duration_seconds: 90,
      tags: ['smoke'],
      categories: ['checkout'],
    },
  ],
};

class PrAdvisorPage {
  constructor(private readonly page: Page) {}

  async routeApi(path: string, handler: Parameters<Page['route']>[1]) {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    await Promise.all(API_PREFIXES.map(prefix => this.page.route(`${prefix}${normalizedPath}`, handler)));
  }

  async mockBackend() {
    await this.routeApi('/auth/refresh', route =>
      route.fulfill({
        status: 200,
        json: { access_token: 'access-token', refresh_token: 'refresh-token' },
      }),
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
          created_at: '2026-05-16T09:00:00',
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
              created_at: '2026-05-16T09:00:00',
              spec_count: 7,
              run_count: 0,
              batch_count: 0,
            },
          ],
        },
      }),
    );
    await this.routeApi('/github/default/config', route =>
      route.fulfill({
        status: 200,
        json: {
          configured: true,
          owner: 'NihadMemmedli',
          repo: 'quorvex_ai',
          default_ref: 'main',
          token_masked: 'ghp_****',
        },
      }),
    );
    await this.routeApi('/github/default/pr-advisor/analyses', route =>
      route.fulfill({ status: 200, json: [] }),
    );
    await this.routeApi('/github/default/pr-advisor/analyze', async route => {
      const payload = route.request().postDataJSON() as { pr_number: number; ensure_indexed: boolean };
      expect(payload.pr_number).toBe(42);
      expect(payload.ensure_indexed).toBe(true);
      await route.fulfill({ status: 200, json: analysis });
    });
    await this.routeApi('/github/default/pr-advisor/analyses/pria_e2e_42/run', route =>
      route.fulfill({
        status: 200,
        json: {
          analysis_id: 'pria_e2e_42',
          batch_id: 'batch_pr_42',
          run_ids: ['run-1', 'run-2'],
          count: 2,
        },
      }),
    );
  }

  async open() {
    await this.page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });
    await this.page.goto('/pr-advisor');
  }

  async analyzePullRequest(prNumber: string) {
    const prInput = this.page.getByPlaceholder('#');
    await prInput.fill(prNumber);
    await expect(prInput).toHaveValue(prNumber);
    await this.page.getByRole('button', { name: /^Analyze$/ }).click();
  }
}

test.describe('PR Advisor dashboard', () => {
  test('analyzes a GitHub PR, renders recommendations, and starts the recommended batch', async ({ page }) => {
    const advisor = new PrAdvisorPage(page);
    await advisor.mockBackend();
    await advisor.open();

    await expect(page.getByRole('heading', { name: 'PR Advisor' })).toBeVisible();
    await advisor.analyzePullRequest('42');

    await expect(page.getByRole('heading', { name: /PR #42: Improve checkout validation/ })).toBeVisible();
    await expect(page.getByText('Recommended', { exact: true })).toBeVisible();
    await expect(page.getByText('2/7')).toBeVisible();
    await expect(page.getByText('checkout-validation.md', { exact: true })).toBeVisible();
    await expect(page.getByText('checkout-smoke.md', { exact: true })).toBeVisible();
    await expect(page.getByText('Repository index: ridx_e2e_42')).toBeVisible();
    await expect(page.getByText('Changed spec file maps directly to this generated test')).toBeVisible();
    await expect(page.getByText("Route path 'checkout' matched spec name")).toBeVisible();

    await page.getByRole('button', { name: /run recommended/i }).click();
    await page.waitForURL('**/regression/batches/batch_pr_42');
  });
});
