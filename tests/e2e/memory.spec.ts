import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

class MemoryDashboardPage {
  constructor(private readonly page: Page) {}

  async routeApi(path: string, handler: (route: Route) => void | Promise<void>) {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    await Promise.all(API_PREFIXES.map(prefix => this.page.route(`${prefix}${normalizedPath}`, handler)));
  }

  async mockBackend() {
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
              spec_count: 1,
              run_count: 0,
              batch_count: 0,
            },
          ],
        },
      }),
    );
    await this.routeApi('/api/memory/diagnostics?*', route =>
      route.fulfill({
        status: 200,
        json: {
          project_id: 'default',
          memory_enabled: true,
          embedding_model: 'local-hash-1536',
          generated_at: '2026-05-24T10:00:00',
          overall_status: 'warning',
          checks: [
            {
              status: 'warning',
              message: 'Some injection events reference missing memories',
              details: { missing_memory_ids: ['missing-memory'], missing_count: 1 },
            },
            {
              status: 'healthy',
              message: 'Browser exploration memory is available',
              details: { states: 3, elements: 12, frontier: 5 },
            },
          ],
          agent_memory: {
            total: 2,
            ready: 1,
            review_required: 1,
            archived_or_inactive: 0,
            by_kind: { project_fact: 1, agent_lesson: 1 },
            by_source: { native_healer: 1, manual_dashboard: 1 },
          },
          browser_memory: { states: 3, elements: 12, frontier: 5, frontier_by_status: { queued: 5 } },
          selector_patterns: { patterns: 4, avg_success_rate: 0.9, actions: { click: 3, fill: 1 } },
          graph: { nodes: 8, edges: 12, node_types: { memory: 2 }, edge_statuses: { active: 12 } },
          injections: {
            total: 6,
            by_stage: { native_generator: 4, native_healer: 2 },
            by_outcome: { injected: 6 },
            missing_memory_ids: ['missing-memory'],
            missing_memory_count: 1,
          },
          stale_memory: { high_impact_count: 1, older_than_days: 30, items: [] },
          recommended_actions: ['Verify stale or review-required memories that were injected.'],
        },
      }),
    );
    await this.routeApi('/api/memory/effectiveness?*', route =>
      route.fulfill({
        status: 200,
        json: {
          project_id: 'default',
          days: 30,
          total_injections: 6,
          stage_stats: [
            {
              stage: 'native_generator',
              injections: 4,
              successes: 3,
              failures: 1,
              empty_recall: 0,
              success_rate: 0.75,
              last_injected_at: '2026-05-24T10:00:00',
            },
          ],
          top_helpful_memories: [
            {
              memory_id: 'mem-helpful',
              summary: 'Login starts on /login.',
              kind: 'project_fact',
              injections: 3,
              successes: 3,
              failures: 0,
              feedback_score: 2,
            },
          ],
          top_harmful_memories: [
            {
              memory_id: 'mem-risk',
              summary: 'Old selector used button text Submit.',
              kind: 'agent_lesson',
              injections: 2,
              successes: 0,
              failures: 2,
              feedback_score: -2,
            },
          ],
          empty_recall_stages: [],
          stale_injections: [{ memory_id: 'mem-risk', stage: 'native_generator', warning: 'high_importance_unverified' }],
          recommended_actions: ['Review memories associated with failed outcomes and archive low-trust items.'],
        },
      }),
    );
    await this.routeApi('/api/memory/repair', async route => {
      const payload = route.request().postDataJSON() as { action: string; dry_run: boolean };
      await route.fulfill({
        status: 200,
        json: {
          action: payload.action,
          dry_run: payload.dry_run,
          changed_count: 1,
          items: [{ memory_id: 'mem-risk' }],
          warnings: [],
        },
      });
    });
    await this.routeApi('/api/memory/context-preview?*', route =>
      route.fulfill({
        status: 200,
        json: {
          context: '## Memory Context\n- [project_fact, score=0.91] Login starts on /login.',
          warnings: ['High-importance memory has not been verified.'],
          score_breakdown: [
            {
              id: 'mem-helpful',
              score: 0.91,
              retrieval_reason: 'project scoped',
              score_breakdown: { confidence: 0.2, importance: 0.1 },
            },
          ],
        },
      }),
    );
    await this.routeApi('/api/memory/patterns?*', route => route.fulfill({ status: 200, json: [] }));
    await this.routeApi('/api/memory/stats?*', route =>
      route.fulfill({ status: 200, json: { total_patterns: 0, avg_success_rate: 0, action_breakdown: {}, project_id: 'default' } }),
    );
    await this.routeApi('/api/memory/browser?*', route =>
      route.fulfill({ status: 200, json: { project_id: 'default', states: [], elements: [], frontier: [] } }),
    );
    await this.routeApi('/api/memory/agent?*', route => route.fulfill({ status: 200, json: [] }));
    await this.routeApi('/api/memory/injections?*', route => route.fulfill({ status: 200, json: [] }));
    await this.routeApi('/api/memory/graph/knowledge?*', route =>
      route.fulfill({ status: 200, json: { nodes: [], edges: [], stats: { node_count: 0, edge_count: 0, node_types: {}, relationship_types: {} } } }),
    );
    await this.routeApi('/api/memory/graph/review?*', route => route.fulfill({ status: 200, json: { edges: [] } }));
  }

  async open() {
    await this.page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });
    await this.page.goto('/memory');
  }
}

test.describe('Memory dashboard', () => {
  test('renders diagnostics, effectiveness, repair results, and scored context preview', async ({ page }) => {
    const memory = new MemoryDashboardPage(page);
    await memory.mockBackend();
    await memory.open();

    await expect(page.getByRole('heading', { name: 'Memory' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Operational health' })).toBeVisible();
    await expect(page.getByText('Some injection events reference missing memories')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Effectiveness' })).toBeVisible();
    await expect(page.getByText('Login starts on /login.')).toBeVisible();
    await expect(page.getByText('Old selector used button text Submit.')).toBeVisible();

    await page.getByRole('button', { name: 'Mark missing refs' }).click();
    await expect(page.getByText('mark missing injection refs dry run found 1 item.')).toBeVisible();
    await expect(page.getByText('"action": "mark_missing_injection_refs"')).toBeVisible();

    await page.getByRole('tab', { name: /Agent Memory/i }).click();
    await page.getByRole('button', { name: /Preview/i }).click();
    await expect(page.getByText('## Memory Context')).toBeVisible();
    await expect(page.getByText('High-importance memory has not been verified.')).toBeVisible();
    await expect(page.getByText('"retrieval_reason": "project scoped"')).toBeVisible();
  });
});
