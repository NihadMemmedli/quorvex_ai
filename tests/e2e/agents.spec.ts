import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const PROJECT = {
  id: 'project-1',
  name: 'Project One',
  base_url: 'https://example.test',
  created_at: '2026-06-08T00:00:00',
  spec_count: 0,
  run_count: 1,
  batch_count: 0,
};

function apiPath(url: string) {
  const parsed = new URL(url);
  return parsed.pathname.replace(/^\/backend-proxy/, '');
}

function completedCustomRun() {
  return {
    id: 'custom-run-reqs',
    agent_type: 'custom',
    runtime: 'claude_sdk',
    status: 'completed',
    created_at: '2026-06-08T10:00:00',
    completed_at: '2026-06-08T10:03:00',
    project_id: PROJECT.id,
    config: {
      agent_name: 'Checkout QA Agent',
      url: 'https://example.test',
      prompt: 'Inspect checkout and produce requirements.',
    },
    result: {
      output: 'Completed checkout review.',
      duration_seconds: 12.4,
      structured_report: {
        summary: 'Checkout review captured one requirement and one regression idea.',
        scope: 'Checkout',
        pages_checked: [{ id: 'P-001', url: '/checkout', status: 'loaded' }],
        findings: [{
          id: 'F-001',
          title: 'Checkout address validation missing',
          severity: 'high',
          page: '/checkout',
          description: 'Invalid addresses do not show validation feedback.',
          evidence: 'The form submitted with an empty postal code.',
        }],
        test_ideas: [{
          id: 'T-001',
          title: 'Checkout address validation',
          priority: 'high',
          page: '/checkout',
          steps: ['Open checkout', 'Submit an empty postal code'],
          expected: 'Validation feedback is visible.',
        }],
        requirements: [{
          id: 'R-001',
          title: 'Checkout requires address validation feedback',
          description: 'Customers must see validation feedback before payment.',
          category: 'validation',
          priority: 'high',
          acceptance_criteria: ['Submitting an empty postal code shows validation feedback.'],
          page: '/checkout',
          evidence: 'The form submitted with an empty postal code.',
          confidence: 0.82,
        }],
        evidence: [{ id: 'E-001', type: 'note', label: 'Observation', value: 'Postal code accepted blank.' }],
        follow_up_actions: [],
        parse_status: 'structured',
      },
    },
    progress: {},
    artifacts: [],
    health: { event_count: 0, tool_event_count: 0, error_event_count: 0, terminal: true },
  };
}

async function authenticate(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', 'project-1');
  });
}

async function routeAgentsApi(page: Page) {
  let run = completedCustomRun();

  await page.route(`${API_BASE}/auth/refresh`, route =>
    route.fulfill({ status: 200, json: { access_token: 'access-token', refresh_token: 'refresh-token' } }),
  );
  await page.route(`${API_BASE}/auth/me`, route =>
    route.fulfill({
      status: 200,
      json: {
        id: 'user-1',
        email: 'qa@example.com',
        full_name: 'QA User',
        is_active: true,
        is_superuser: true,
        email_verified: true,
        created_at: '2026-06-08T00:00:00',
        last_login: null,
      },
    }),
  );
  await page.route(`${API_BASE}/projects`, route => route.fulfill({ status: 200, json: { projects: [PROJECT] } }));
  await page.route(`${API_BASE}/settings`, route => route.fulfill({ status: 200, json: { agent_runtime: 'claude_sdk' } }));
  await page.route(`${API_BASE}/chat/project-context`, route => route.fulfill({ status: 200, json: {} }));
  await page.route(`${API_BASE}/api/agents/tools/catalog`, route => route.fulfill({ status: 200, json: { tools: [] } }));
  await page.route(`${API_BASE}/api/agents/definitions**`, route => route.fulfill({ status: 200, json: [] }));
  await page.route(`${API_BASE}/projects/${PROJECT.id}/browser-auth-sessions`, route => route.fulfill({ status: 200, json: { sessions: [] } }));
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/events**`, route => route.fulfill({ status: 200, json: [] }));
  await page.route(`${API_BASE}/api/agents/exploratory/${run.id}/specs`, route => route.fulfill({ status: 200, json: { specs: [] } }));
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/report-requirements/import**`, async route => {
    const requirement = run.result.structured_report.requirements[0] as Record<string, unknown>;
    requirement.imported_requirement_id = 101;
    requirement.imported_requirement_code = 'REQ-101';
    requirement.imported_at = '2026-06-08T10:05:00';
    return route.fulfill({
      status: 200,
      json: {
        created: 1,
        skipped: 0,
        requirements: [{ item_id: 'R-001', id: 101, req_code: 'REQ-101', title: requirement.title, project_id: PROJECT.id }],
        skipped_items: [],
        run,
      },
    });
  });
  await page.route(`${API_BASE}/api/agents/runs/${run.id}`, route => route.fulfill({ status: 200, json: run }));
  await page.route(`${API_BASE}/api/agents/runs**`, route => route.fulfill({ status: 200, json: [run] }));
  await page.route(`${API_BASE}/**`, (route: Route) => {
    const path = apiPath(route.request().url());
    return route.fulfill({ status: 200, json: { items: [], path } });
  });
}

test.describe('Agents custom report requirements', () => {
  test('renders requirement tab, imports candidates, and keeps spec actions available', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?runId=custom-run-reqs');
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible();
    await expect(page.getByText('Checkout review captured one requirement and one regression idea.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Requirements 1' })).toBeVisible();

    await page.getByRole('button', { name: 'Requirements 1' }).click();
    await expect(page.getByText('R-001: Checkout requires address validation feedback')).toBeVisible();
    await expect(page.getByText('Submitting an empty postal code shows validation feedback.')).toBeVisible();

    await page.getByRole('button', { name: /^Import Requirements$/ }).click();
    await expect(page.getByRole('link', { name: 'REQ-101' })).toHaveAttribute('href', '/requirements?highlight=101');
    await expect(page.getByRole('button', { name: /^Imported$/ })).toBeDisabled();

    await page.getByRole('button', { name: 'Findings 1' }).click();
    await expect(page.getByRole('button', { name: 'Create Spec' })).toBeVisible();
  });
});
