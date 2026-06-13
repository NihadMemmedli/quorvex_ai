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

function customAgentDefinition() {
  return {
    id: 'trip-agent',
    name: 'Trip Creator Agent',
    description: 'Builds trip flows and validates booking UX.',
    system_prompt: 'Inspect trip creation and report actionable QA findings.',
    runtime: 'claude_sdk',
    model: null,
    timeout_seconds: 1800,
    tool_ids: ['read_file'],
    test_data_refs: ['travelers.primary'],
    status: 'active',
    project_id: PROJECT.id,
  };
}

async function authenticate(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', 'project-1');
  });
}

async function routeAgentsApi(page: Page, options: {
  definitions?: ReturnType<typeof customAgentDefinition>[];
  onUpdateDefinition?: (payload: Record<string, unknown>) => void;
  onArchiveDefinition?: (id: string) => void;
  onCancelRun?: (id: string) => void;
  runOverride?: Partial<ReturnType<typeof completedCustomRun>>;
} = {}) {
  let run = { ...completedCustomRun(), ...options.runOverride };
  let definitions = [...(options.definitions || [])];

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
  await page.route(`${API_BASE}/api/agents/queue-status`, route => route.fulfill({
    status: 200,
    json: {
      mode: 'redis',
      active: 1,
      queued: 2,
      workers_alive: 2,
      worker_processes_alive: 2,
      workers_busy: 1,
      workers_idle: 1,
      capacity_state: 'workers_available',
      stale_running: 0,
      oldest_queued_age_seconds: 75,
      orphaned_tasks: 0,
      running_tasks: [{ id: 'task-1', status: 'running', agent_type: 'custom', heartbeat_alive: true }],
      browser_pool: { running: 1, max_browsers: 3, available: 2, by_type: { agent: 1 } },
    },
  }));
  await page.route(`${API_BASE}/api/agents/reports/search**`, route => route.fulfill({
    status: 200,
    json: {
      count: 1,
      items: [{
        run_id: run.id,
        agent_name: 'Checkout QA Agent',
        created_at: run.created_at,
        type: 'finding',
        item: run.result.structured_report.findings[0],
      }],
    },
  }));
  await page.route(`${API_BASE}/api/agents/definitions**`, async route => {
    const request = route.request();
    const path = apiPath(request.url());
    const definitionId = path.match(/^\/api\/agents\/definitions\/([^/]+)/)?.[1];

    if (request.method() === 'PUT' && definitionId) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      options.onUpdateDefinition?.(payload);
      const existing = definitions.find(definition => definition.id === definitionId);
      const updated = {
        ...(existing || customAgentDefinition()),
        ...payload,
        id: definitionId,
        project_id: PROJECT.id,
        status: 'active',
      } as ReturnType<typeof customAgentDefinition>;
      definitions = definitions.map(definition => definition.id === definitionId ? updated : definition);
      if (!definitions.some(definition => definition.id === definitionId)) definitions.push(updated);
      return route.fulfill({ status: 200, json: updated });
    }

    if (request.method() === 'POST' && !definitionId) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      const created = {
        ...customAgentDefinition(),
        ...payload,
        id: 'created-agent',
        project_id: PROJECT.id,
        status: 'active',
      } as ReturnType<typeof customAgentDefinition>;
      definitions = [created, ...definitions];
      return route.fulfill({ status: 200, json: created });
    }

    if (request.method() === 'DELETE' && definitionId) {
      options.onArchiveDefinition?.(definitionId);
      definitions = definitions.filter(definition => definition.id !== definitionId);
      return route.fulfill({ status: 200, json: { status: 'archived', id: definitionId } });
    }

    return route.fulfill({ status: 200, json: definitions });
  });
  await page.route(`${API_BASE}/projects/${PROJECT.id}/browser-auth-sessions`, route => route.fulfill({ status: 200, json: { sessions: [] } }));
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/trace**`, route =>
    route.fulfill({
      status: 200,
      json: {
        snapshot: {
          id: 'atrace-e2e',
          trace_id: 'atrace-e2e',
          run_id: run.id,
          attempt: 1,
          runtime: 'claude_sdk',
          allowed_tools: [],
          test_data_refs: [],
          created_at: '2026-06-08T10:00:00',
          updated_at: '2026-06-08T10:00:00',
        },
        spans: [],
        events: [],
        memory_injections: [],
        artifacts: [],
        temporal: null,
        correlation: { run_id: run.id, trace_id: 'atrace-e2e', project_id: PROJECT.id },
      },
    }),
  );
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
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/cancel**`, async route => {
    options.onCancelRun?.(run.id);
    run = { ...run, status: 'cancelled', progress: { ...(run.progress || {}), phase: 'cancelled' } };
    return route.fulfill({ status: 200, json: run });
  });
  await page.route(`${API_BASE}/api/agents/runs/${run.id}`, route => route.fulfill({ status: 200, json: run }));
  await page.route(`${API_BASE}/api/agents/runs**`, route => {
    if (apiPath(route.request().url()) === '/api/agents/runs') {
      return route.fulfill({ status: 200, json: [run] });
    }
    return route.fallback();
  });
  await page.route(`${API_BASE}/**`, (route: Route) => {
    const path = apiPath(route.request().url());
    if (
      path === '/auth/refresh' ||
      path === '/auth/me' ||
      path === '/projects' ||
      path === '/settings' ||
      path === '/chat/project-context' ||
      path === `/projects/${PROJECT.id}/browser-auth-sessions` ||
      path.startsWith('/api/agents/')
    ) {
      return route.fallback();
    }
    return route.fulfill({ status: 200, json: { items: [], path } });
  });
}

test.describe('Agents custom report requirements', () => {
  test('renders requirement tab, imports candidates, and keeps spec actions available', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?runId=custom-run-reqs');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();
    await expect(page.getByText('Checkout review captured one requirement and one regression idea.')).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Requirements 1' })).toBeVisible();

    await page.getByRole('tab', { name: 'Requirements 1' }).click();
    await expect(page.getByText('R-001: Checkout requires address validation feedback')).toBeVisible();
    await expect(page.getByText('Submitting an empty postal code shows validation feedback.')).toBeVisible();

    await page.getByRole('button', { name: /^Import Requirements$/ }).click();
    await expect(page.getByRole('link', { name: 'REQ-101' })).toHaveAttribute('href', '/requirements?highlight=101');
    await expect(page.getByRole('button', { name: /^Imported$/ })).toBeDisabled();

    await page.getByRole('tab', { name: 'Findings 1' }).click();
    await expect(page.getByRole('button', { name: 'Create Spec' })).toBeVisible();
  });
});

test.describe('Agents custom definition menu', () => {
  test('opens the edit dialog from the custom agent action menu and saves changes', async ({ page }) => {
    let updatePayload: Record<string, unknown> | null = null;

    await authenticate(page);
    await routeAgentsApi(page, {
      definitions: [customAgentDefinition()],
      onUpdateDefinition: payload => {
        updatePayload = payload;
      },
    });

    await page.goto('/agents?agent=custom&definitionId=trip-agent');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Trip Creator Agent 1 tools' })).toBeVisible();

    await page.getByRole('button', { name: 'Open actions for Trip Creator Agent' }).click();
    await page.getByRole('menuitem', { name: 'Edit' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Edit Custom Agent' })).toBeVisible();
    await expect(dialog.getByLabel('Name')).toHaveValue('Trip Creator Agent');
    await expect(dialog.getByLabel('System Prompt')).toHaveValue('Inspect trip creation and report actionable QA findings.');
    await expect(dialog.getByLabel('Default Test Data Refs')).toHaveValue('travelers.primary');

    await dialog.getByLabel('Name').fill('Trip Planner Agent');
    await dialog.getByRole('button', { name: 'Save Agent' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: 'Trip Planner Agent 1 tools' })).toBeVisible();
    expect(updatePayload?.name).toBe('Trip Planner Agent');
    expect(updatePayload?.project_id).toBe(PROJECT.id);
  });

  test('opens the archive confirmation from the custom agent action menu and archives the agent', async ({ page }) => {
    let archivedId: string | null = null;

    await authenticate(page);
    await routeAgentsApi(page, {
      definitions: [customAgentDefinition()],
      onArchiveDefinition: id => {
        archivedId = id;
      },
    });

    await page.goto('/agents?agent=custom&definitionId=trip-agent');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Trip Creator Agent 1 tools' })).toBeVisible();

    await page.getByRole('button', { name: 'Open actions for Trip Creator Agent' }).click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Archive Custom Agent' })).toBeVisible();
    await expect(dialog.getByText('Archive "Trip Creator Agent"?')).toBeVisible();

    await dialog.getByRole('button', { name: /^Archive$/ }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: 'Trip Creator Agent 1 tools' })).toHaveCount(0);
    await expect(page.getByText('No custom agents yet.')).toBeVisible();
    expect(archivedId).toBe('trip-agent');
  });
});

test.describe('Agents workspace views', () => {
  test('shows queue capacity from the queue status endpoint', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?view=queue');
    await expect(page.getByRole('tab', { name: /Queue/ })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('heading', { name: 'Queue Capacity' })).toBeVisible();
    await expect(page.getByText('1/3')).toBeVisible();
    await expect(page.getByText('task-1')).toBeVisible();
  });

  test('searches structured report items', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?view=reports&reportQ=address&reportType=finding&reportSeverity=high');
    await expect(page.getByRole('heading', { name: 'Search Reports' })).toBeVisible();
    await expect(page.getByText('Checkout address validation missing')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Open report' })).toHaveAttribute('href', /runId=custom-run-reqs/);
  });

  test('confirms before cancelling an active run and calls the API once', async ({ page }) => {
    let cancelCalls = 0;

    await authenticate(page);
    await routeAgentsApi(page, {
      runOverride: { status: 'running', progress: { phase: 'running' } },
      onCancelRun: () => {
        cancelCalls += 1;
      },
    });

    await page.goto('/agents?runId=custom-run-reqs');
    await expect(page.getByRole('button', { name: 'Cancel agent run' })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel agent run' }).click();

    const dialog = page.getByRole('dialog', { name: 'Cancel Agent Run' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(dialog).toBeHidden();
    expect(cancelCalls).toBe(0);

    await page.getByRole('button', { name: 'Cancel agent run' }).click();
    await page.getByRole('dialog', { name: 'Cancel Agent Run' }).getByRole('button', { name: 'Cancel Run' }).click();
    await expect(page.getByRole('dialog', { name: 'Cancel Agent Run' })).toBeHidden();
    expect(cancelCalls).toBe(1);
  });

  test('opens the custom agent builder from create intent and returns to workflow after save', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?agent=custom&create=1&returnTo=/workflow');
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();
    await dialog.getByLabel('Name').fill('Workflow Agent');
    await dialog.getByLabel('System Prompt').fill('Inspect workflow-created scenarios.');
    await dialog.getByRole('button', { name: 'Save Agent' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByRole('link', { name: 'Return to Workflow' })).toHaveAttribute('href', '/workflow');
  });
});
