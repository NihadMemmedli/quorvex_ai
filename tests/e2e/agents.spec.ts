import { expect, type Locator, type Page, type Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const APP_BASE = (process.env.BASE_URL || 'http://localhost:3000').replace(/\/$/, '');
const PROJECT = {
  id: 'project-1',
  name: 'Project One',
  base_url: 'https://example.test',
  created_at: '2026-06-08T00:00:00',
  spec_count: 0,
  run_count: 1,
  batch_count: 0,
};

type BrowserAuthSessionFixture = {
  id: string;
  name: string;
  status: string;
  is_default: boolean;
};

function apiPath(url: string) {
  const parsed = new URL(url);
  return parsed.pathname.replace(/^\/backend-proxy/, '');
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

async function expectDialogInViewport(page: Page, dialog: Locator) {
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
}

async function expectLocatorInViewport(page: Page, locator: Locator) {
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
}

async function expectLocatorWithinViewportWidth(page: Page, locator: Locator) {
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
}

function completedCustomRun() {
  const testIdeas = [
    {
      id: 'T-001',
      title: 'Checkout address validation',
      priority: 'high',
      page: '/checkout',
      steps: ['Open checkout', 'Submit an empty postal code'],
      expected: 'Validation feedback is visible.',
    },
    {
      id: 'T-002',
      title: 'Checkout card decline messaging',
      priority: 'high',
      page: '/checkout/payment',
      steps: ['Open payment', 'Submit a declined card'],
      expected: 'The decline reason is shown without clearing the cart.',
    },
    {
      id: 'T-003',
      title: 'Guest checkout email typo recovery',
      priority: 'medium',
      page: '/checkout/contact',
      steps: ['Enter an invalid email', 'Continue checkout'],
      expected: 'The email field receives actionable validation feedback.',
    },
    {
      id: 'T-004',
      title: 'Shipping method recalculates totals',
      priority: 'medium',
      page: '/checkout/shipping',
      steps: ['Select express shipping', 'Return to standard shipping'],
      expected: 'Order totals update after each shipping method change.',
    },
    {
      id: 'T-005',
      title: 'Promo code remains after address edit',
      priority: 'medium',
      page: '/checkout',
      steps: ['Apply a promo code', 'Edit the shipping address'],
      expected: 'The discount remains applied when the address is valid.',
    },
    {
      id: 'T-006',
      title: 'Payment retry keeps customer context',
      priority: 'low',
      page: '/checkout/payment',
      steps: ['Fail payment once', 'Retry with a valid card'],
      expected: 'Customer and shipping details remain populated for retry.',
    },
    {
      id: 'T-007',
      title: 'Order review blocks stale inventory',
      priority: 'medium',
      page: '/checkout/review',
      steps: ['Open review', 'Simulate an out-of-stock line item'],
      expected: 'Checkout blocks submission and identifies the stale item.',
    },
  ];

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
        summary: 'Checkout review captured one requirement and seven regression ideas.',
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
        test_ideas: testIdeas,
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

function completedExploratoryRun(resultOverride: Record<string, unknown> = {}) {
  return {
    id: 'explorer-run-results',
    agent_type: 'exploratory',
    runtime: 'claude_sdk',
    status: 'completed',
    created_at: '2026-06-08T11:00:00',
    completed_at: '2026-06-08T11:04:00',
    project_id: PROJECT.id,
    config: {
      url: 'https://example.test',
      project_id: PROJECT.id,
    },
    result: {
      summary: 'Explorer captured structured evidence.',
      elapsed_time_minutes: 1.2,
      coverage: {
        pages_visited: 2,
        flows_discovered: 1,
        forms_interacted: 0,
        errors_found: 0,
        coverage_score: 0.75,
      },
      event_counts: { page_observed: 2, action_result: 1, flow_candidate: 1 },
      diagnostics: {
        evidence_event_count: 4,
        browser_tool_calls: 3,
        successful_browser_tool_calls: 3,
        dedupe_stats: { duplicate_flows_removed: 1 },
      },
      discovered_flow_summaries: [{
        id: 'flow_1',
        title: 'Open pricing',
        pages: ['https://example.test', 'https://example.test/pricing'],
        steps_count: 2,
        has_happy_path: true,
        has_edge_cases: false,
        entry_point: 'https://example.test',
        exit_point: 'https://example.test/pricing',
        complexity: 'low',
      }],
      total_flows_discovered: 1,
      ...resultOverride,
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

function activeBrowserAuthSession(): BrowserAuthSessionFixture {
  return {
    id: 'browser-session-active',
    name: 'Travel Login',
    status: 'active',
    is_default: true,
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
  browserAuthSessions?: BrowserAuthSessionFixture[];
  onUpdateDefinition?: (payload: Record<string, unknown>) => void;
  onArchiveDefinition?: (id: string) => void;
  onCancelRun?: (id: string) => void;
  onStartExploratory?: (payload: Record<string, unknown>) => void;
  onStartCustom?: (payload: Record<string, unknown>) => void;
  onRetryRun?: (id: string) => void;
  onGenerateReportSpec?: (payload: { itemId: string; itemType: string | null; body: Record<string, unknown> }) => void;
  onPatchReport?: (payload: Record<string, unknown>) => void;
  onPatchReportItem?: (payload: { itemId: string; itemType: string | null; body: Record<string, unknown> }) => void;
  onCleanStaleQueue?: () => Record<string, unknown>;
  failPatchReport?: boolean;
  onRunFetch?: (run: any, fetchCount: number) => any;
  queueStatus?: Record<string, unknown>;
  runOverride?: Record<string, any>;
} = {}) {
  let run = { ...clone(completedCustomRun()), ...options.runOverride };
  let definitions = [...(options.definitions || [])];
  let runFetchCount = 0;

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
  await page.route('**/test-data/datasets**', route => {
    const path = apiPath(route.request().url());
    if (path === '/test-data/datasets') {
      return route.fulfill({
        status: 200,
        json: {
          datasets: [{
            id: 'test-data-dataset-1',
            key: 'wetravel-login-users',
            name: 'WeTravel Login Users',
          }],
        },
      });
    }
    if (path.startsWith('/test-data/datasets/test-data-dataset-1/items')) {
      return route.fulfill({
        status: 200,
        json: {
          items: [{
            id: 'test-data-item-1',
            key: 'valid-user',
            ref: 'wetravel-login-users.valid-user',
            name: 'Valid user',
          }],
        },
      });
    }
    return route.fallback();
  });
  await page.route(`${API_BASE}/api/agents/queue-status`, route => {
    const queueStatus = {
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
      ...options.queueStatus,
    };
    return route.fulfill({ status: 200, json: queueStatus });
  });
  await page.route(`${API_BASE}/api/agents/queue-clean-stale`, route => {
    const payload = options.onCleanStaleQueue?.() || {
      status: 'success',
      cleaned: 0,
      cancelled_orphaned: 0,
      timed_out: 0,
      terminal_owner: 0,
      orphaned_queued: 0,
      stale_ownerless_queued: 0,
      missing_task_refs: 0,
      skipped_active: 0,
    };
    return route.fulfill({ status: 200, json: { status: 'success', ...payload } });
  });
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
    const runDefinitionId = path.match(/^\/api\/agents\/definitions\/([^/]+)\/runs$/)?.[1];
    const definitionId = path.match(/^\/api\/agents\/definitions\/([^/]+)/)?.[1];

    if (request.method() === 'POST' && runDefinitionId) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      options.onStartCustom?.(payload);
      return route.fulfill({
        status: 200,
        json: {
          status: 'queued',
          run_id: 'custom-run-started',
          definition_id: runDefinitionId,
          agent_runtime: 'claude_sdk',
        },
      });
    }

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
  await page.route(`${API_BASE}/projects/${PROJECT.id}/browser-auth-sessions`, route =>
    route.fulfill({ status: 200, json: { sessions: options.browserAuthSessions || [] } }),
  );
  await page.route(`${API_BASE}/api/agents/exploratory`, route => {
    const request = route.request();
    if (request.method() !== 'POST') return route.fallback();
    options.onStartExploratory?.(request.postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      status: 200,
      json: {
        status: 'queued',
        run_id: 'exploratory-run-started',
        temporal_workflow_id: 'agent-exploratory-run-started',
        temporal_run_id: 'temporal-run-1',
        agent_runtime: 'claude_sdk',
        browser_runtime: 'temporal_worker',
        live_view_available: false,
        agent_slots: { active: 1, max: 3, queued: 3 },
      },
    });
  });
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
  await page.route(`${API_BASE}/api/agents/exploratory/flow-spec-jobs/report-spec-job`, route => route.fulfill({
    status: 200,
    json: {
      job_id: 'report-spec-job',
      status: 'completed',
      result: {
        spec_content: '# Checkout address validation\n\nGenerated spec.',
        spec_file: '/tmp/specs/checkout-address-validation.md',
        flow_title: 'Checkout address validation',
        validated: true,
        pipeline: 'native_planner_generator',
        requires_auth: false,
      },
    },
  }));
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/report-items/*/generate-spec**`, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const itemId = apiPath(request.url()).match(/\/report-items\/([^/]+)\/generate-spec$/)?.[1] || '';
    options.onGenerateReportSpec?.({
      itemId: decodeURIComponent(itemId),
      itemType: url.searchParams.get('item_type'),
      body: request.postDataJSON() as Record<string, unknown>,
    });
    return route.fulfill({
      status: 200,
      json: {
        job_id: 'report-spec-job',
        agent_run_id: 'report-spec-agent-run',
      },
    });
  });
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/report-items/*`, async route => {
    const request = route.request();
    if (request.method() !== 'PATCH') return route.fallback();
    if (options.failPatchReport) {
      return route.fulfill({ status: 500, json: { detail: 'Report save failed in test.' } });
    }
    const url = new URL(request.url());
    const itemId = decodeURIComponent(apiPath(request.url()).match(/\/report-items\/([^/]+)$/)?.[1] || '');
    const itemType = url.searchParams.get('item_type');
    const body = request.postDataJSON() as Record<string, unknown>;
    const patch = (body.patch && typeof body.patch === 'object' ? body.patch : body) as Record<string, unknown>;
    options.onPatchReportItem?.({ itemId, itemType, body });

    const report = run.result.structured_report;
    const key = itemType === 'finding' ? 'findings' : itemType === 'test_idea' ? 'test_ideas' : 'requirements';
    report[key] = report[key].map((item: { id: string }) => item.id === itemId ? { ...item, ...patch, id: item.id } : item);
    run = { ...run, result: { ...run.result, structured_report: { ...report } } };
    return route.fulfill({ status: 200, json: run });
  });
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/report**`, async route => {
    const request = route.request();
    if (apiPath(request.url()) !== `/api/agents/runs/${run.id}/report`) return route.fallback();
    if (request.method() !== 'PATCH') return route.fallback();
    if (options.failPatchReport) {
      return route.fulfill({ status: 500, json: { detail: 'Report save failed in test.' } });
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    options.onPatchReport?.(body);
    run = {
      ...run,
      result: {
        ...run.result,
        structured_report: {
          ...run.result.structured_report,
          summary: body.summary,
          scope: body.scope,
        },
      },
    };
    return route.fulfill({ status: 200, json: run });
  });
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
  await page.route(`${API_BASE}/api/agents/runs/${run.id}/retry**`, async route => {
    options.onRetryRun?.(run.id);
    run = {
      ...run,
      status: 'queued',
      temporal_workflow_id: `agent-run-${run.id}-attempt-1`,
      temporal_run_id: 'temporal-retry-run',
      progress: {
        ...(run.progress || {}),
        phase: 'queued',
        status: 'queued',
        retry_in_place: true,
        retry_attempt: 1,
        message: 'Retrying in same run using saved browser auth/session artifacts.',
      },
    };
    return route.fulfill({ status: 200, json: { ...run, run_id: run.id, retry_in_place: true, retry_attempt: 1 } });
  });
  await page.route(`${API_BASE}/api/agents/runs/${run.id}**`, route => {
    if (apiPath(route.request().url()) !== `/api/agents/runs/${run.id}`) return route.fallback();
    runFetchCount += 1;
    if (options.onRunFetch) {
      run = options.onRunFetch(run, runFetchCount);
    }
    return route.fulfill({ status: 200, json: run });
  });
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
      path.startsWith('/test-data/') ||
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

    await page.goto('/agents?agent=custom&runId=custom-run-reqs');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();
    await expect(page.getByText('Checkout review captured one requirement and seven regression ideas.')).toBeVisible();
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

test.describe('Agents create and report spec actions', () => {
  test('passes inserted project test data refs to custom agent runs', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, {
      definitions: [customAgentDefinition()],
    });

    await page.goto('/agents?agent=custom&definitionId=trip-agent');
    await page.getByLabel('Target URL').fill('https://pre.wetravel.to/user/itineraries');
    await page.getByRole('button', { name: /Context & Test Data/ }).click();
    await expect(page.getByLabel('Project Test Data Refs')).toBeVisible();
    await expect(page.getByTestId('test-data-picker-item')).toContainText('Valid user');

    await page.getByTestId('test-data-picker-insert').click();
    await expect(page.getByLabel('Project Test Data Refs')).toHaveValue('wetravel-login-users.valid-user');

    const requestPromise = page.waitForRequest(request =>
      apiPath(request.url()) === '/api/agents/definitions/trip-agent/runs' && request.method() === 'POST',
    );
    await page.locator('#agents-run-setup-panel').getByRole('button', { name: /Start Agent/ }).click();

    const request = await requestPromise;
    expect(request.postDataJSON()).toMatchObject({
      url: 'https://pre.wetravel.to/user/itineraries',
      test_data_refs: ['wetravel-login-users.valid-user'],
      config: {
        test_data_refs: ['wetravel-login-users.valid-user'],
      },
      project_id: PROJECT.id,
    });
  });

  test('keeps run history in its own workspace tab', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents');
    await expect(page.getByText('Run Setup')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Run History' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Explorer/ })).toHaveCount(0);

    await page.getByRole('tab', { name: /History/ }).click();
    await expect(page.getByRole('heading', { name: 'Run History' })).toBeVisible();
    await expect(page.getByRole('button', { name: /Checkout QA Agent/ })).toBeVisible();

    await page.getByRole('button', { name: /Checkout QA Agent/ }).click();
    await expect(page.getByText('Run Setup')).toBeVisible();
    await expect(page.getByText('Checkout review captured one requirement and seven regression ideas.')).toBeVisible();
  });

  test('loads browser login sessions on direct custom agent entry', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, {
      definitions: [customAgentDefinition()],
      browserAuthSessions: [activeBrowserAuthSession()],
    });

    const sessionsRequest = page.waitForRequest(request =>
      apiPath(request.url()) === `/projects/${PROJECT.id}/browser-auth-sessions`,
    );

    await page.goto('/agents?agent=custom&definitionId=trip-agent');
    await sessionsRequest;

    const sessionSelect = page.getByLabel('Browser Login Session');
    await expect(sessionSelect).toBeVisible();
    await expect(sessionSelect).toContainText('Travel Login (Default, active)');
  });

  test('passes selected browser login session to custom agent runs', async ({ page }) => {
    let customRunPayload: Record<string, unknown> | null = null;

    await authenticate(page);
    await routeAgentsApi(page, {
      definitions: [customAgentDefinition()],
      browserAuthSessions: [activeBrowserAuthSession()],
      onStartCustom: payload => {
        customRunPayload = payload;
      },
    });

    await page.goto('/agents?agent=custom&definitionId=trip-agent');
    await page.getByLabel('Target URL').fill('https://example.test/trips');
    await page.getByLabel('Browser Login Session').selectOption('browser-session-active');
    const contextTrigger = page.getByRole('button', { name: /Context & Test Data/ });
    await expect(contextTrigger).toBeVisible();
    await expect(contextTrigger).toContainText('1 ref selected');
    if ((await contextTrigger.getAttribute('aria-expanded')) !== 'true') {
      await contextTrigger.click();
    }
    await expect(page.getByLabel('Project Test Data Refs')).toBeVisible();
    await expect(page.getByTestId('test-data-picker-item')).toContainText('Valid user');
    await expect(page.getByTestId('test-data-picker-insert')).toContainText('Add');
    await expect(page.getByTestId('test-data-picker-edit')).toContainText('Edit');
    await page.getByTestId('test-data-picker-insert').click();
    await expect(page.getByLabel('Project Test Data Refs')).toHaveValue('wetravel-login-users.valid-user');
    await expect(contextTrigger).toContainText('1 ref selected');

    const requestPromise = page.waitForRequest(request =>
      apiPath(request.url()) === '/api/agents/definitions/trip-agent/runs' && request.method() === 'POST',
    );
    await page.locator('#agents-run-setup-panel').getByRole('button', { name: /Start Agent/ }).click();
    const request = await requestPromise;

    expect(request.postDataJSON()).toMatchObject({
      url: 'https://example.test/trips',
      test_data_refs: ['wetravel-login-users.valid-user'],
      config: {
        browser_auth_session_id: 'browser-session-active',
        test_data_refs: ['wetravel-login-users.valid-user'],
      },
      project_id: PROJECT.id,
    });
    expect(customRunPayload?.config).toMatchObject({
      browser_auth_session_id: 'browser-session-active',
    });
  });

  test('keeps custom agent run controls reachable on desktop and mobile', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, {
      definitions: [customAgentDefinition()],
      browserAuthSessions: [activeBrowserAuthSession()],
    });
    const longTargetUrl = 'https://pre.wetravel.to/user/itineraries?view=list&definitionId=2dff6cb2-298d-4053-9fec-492264ec1f96&agent=custom&filter=upcoming-trips-with-extra-long-token-value';

    for (const size of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(size);
      await page.goto('/agents?agent=custom&definitionId=trip-agent');
      await page.getByLabel('Target URL').fill(longTargetUrl);

      await expect(page.getByLabel('Runnable Agent')).toBeVisible();
      await expect(page.getByLabel('Target URL')).toBeVisible();
      await expect(page.getByLabel('Browser Login Session')).toBeVisible();
      await expect(page.getByLabel('Task Prompt')).toBeVisible();
      await expectLocatorWithinViewportWidth(page, page.locator('#agents-run-setup-panel'));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBeTruthy();
      const startButton = page.locator('#agents-run-setup-panel').getByRole('button', { name: /Start Agent/ });
      await expect(startButton).toBeVisible();
      await startButton.scrollIntoViewIfNeeded();
      await expectLocatorInViewport(page, startButton);

      const contextTrigger = page.getByRole('button', { name: /Context & Test Data/ });
      await expect(contextTrigger).toBeVisible();
      if ((await contextTrigger.getAttribute('aria-expanded')) !== 'true') {
        await contextTrigger.click();
      }
      await expect(page.getByLabel('Project Test Data Refs')).toBeVisible();
      await expectLocatorWithinViewportWidth(page, page.locator('#agents-run-setup-panel'));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBeTruthy();
    }
  });

  test('opens the custom agent builder from the run setup create button', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?agent=custom&runId=custom-run-reqs');
    await page.getByRole('button', { name: 'Create custom agent' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();
    await expectDialogInViewport(page, dialog);
    await expect(page).toHaveURL(/agent=custom/);
    await expect(page).toHaveURL(/create=1/);
  });

  test('custom agent runtime dropdown only offers Claude SDK', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?agent=custom&create=1');
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();

    const runtimeSelect = dialog.getByLabel('Runtime');
    await runtimeSelect.click();
    await expect(page.getByRole('option', { name: 'Claude SDK' })).toBeVisible();
    await expect(page.getByRole('option', { name: 'Hermes' })).toHaveCount(0);

    await expect(runtimeSelect).toContainText('Claude SDK');
    await expectDialogInViewport(page, dialog);
  });

  test('opens the custom agent builder from the agent library create button', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?view=library');
    await page.getByRole('button', { name: /^Create Agent$/ }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();
    await expectDialogInViewport(page, dialog);
    await expect(page).toHaveURL(/agent=custom/);
    await expect(page).toHaveURL(/create=1/);
  });

  test('opens the custom agent builder from the empty run view create button and clears create on Escape', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents');
    await expect(page.getByRole('heading', { name: 'Start an agent run' })).toBeVisible();
    await page.getByRole('button', { name: /^Create Agent$/ }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();
    await expectDialogInViewport(page, dialog);
    await expect(page).toHaveURL(/agent=custom/);
    await expect(page).toHaveURL(/create=1/);

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(page).not.toHaveURL(/create=1/);
  });

  test('opens the custom agent builder when create intent is added after mount', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();

    await page.evaluate(() => {
      window.history.pushState(null, '', '/agents?agent=custom&create=1');
    });

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();
    await expectDialogInViewport(page, dialog);
    await expect(page).toHaveURL(/agent=custom/);
    await expect(page).toHaveURL(/create=1/);
  });

  test('opens the spec review modal from a test idea without generating immediately', async ({ page }) => {
    let generateCalls = 0;

    await authenticate(page);
    await routeAgentsApi(page, {
      onGenerateReportSpec: () => {
        generateCalls += 1;
      },
    });

    await page.goto('/agents?definitionId=trip-agent&runId=custom-run-reqs&resultTab=test_ideas');
    await expect(page.getByRole('tab', { name: 'Test Ideas 7' })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('tabpanel').getByRole('button', { name: 'Create Spec' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Checkout address validation' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Generate Test Spec' })).toBeVisible();
    await expect(page.getByTestId('agents-action-status')).toContainText('Reviewing test idea T-001 for spec generation.');
    await expect(page).toHaveURL(/definitionId=trip-agent/);
    await expect(page).toHaveURL(/runId=custom-run-reqs/);
    await expect(page).toHaveURL(/specItemId=T-001/);
    await expect(page).toHaveURL(/specItemType=test_idea/);
    expect(generateCalls).toBe(0);

    await dialog.getByRole('button', { name: 'Close' }).first().click();
    await expect(dialog).toBeHidden();
    await expect(page).not.toHaveURL(/specItemId=/);
    await expect(page).not.toHaveURL(/specItemType=/);
    await expect(page.getByRole('button', { name: 'Create Spec' }).first()).toBeVisible();
  });

  test('opens the spec review modal from a finding without generating immediately', async ({ page }) => {
    let generateCalls = 0;

    await authenticate(page);
    await routeAgentsApi(page, {
      onGenerateReportSpec: () => {
        generateCalls += 1;
      },
    });

    await page.goto('/agents?runId=custom-run-reqs');
    await page.getByRole('tab', { name: 'Findings 1' }).click();
    await page.getByRole('button', { name: 'Create Spec' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Checkout address validation missing' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Generate Test Spec' })).toBeVisible();
    await expect(page).toHaveURL(/specItemId=F-001/);
    await expect(page).toHaveURL(/specItemType=finding/);
    expect(generateCalls).toBe(0);
  });

  test('calls the report item generate-spec endpoint from the spec review modal', async ({ page }) => {
    const generateRequests: Array<{ itemId: string; itemType: string | null; body: Record<string, unknown> }> = [];

    await authenticate(page);
    await routeAgentsApi(page, {
      onGenerateReportSpec: payload => {
        generateRequests.push(payload);
      },
    });

    await page.goto('/agents?runId=custom-run-reqs');
    await page.getByRole('tab', { name: 'Test Ideas 7' }).click();
    await page.getByRole('tabpanel').getByRole('button', { name: 'Create Spec' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Checkout address validation' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Generate Test Spec' })).toBeVisible();
    expect(generateRequests).toHaveLength(0);

    const requestPromise = page.waitForRequest(request => request.url().includes(`/api/agents/runs/custom-run-reqs/report-items/T-001/generate-spec`));
    await dialog.getByRole('button', { name: 'Generate Test Spec' }).click();
    await requestPromise;

    await expect.poll(() => generateRequests.length).toBe(1);
    expect(generateRequests[0]).toMatchObject({ itemId: 'T-001', itemType: 'test_idea', body: { skip_browser_auth: true } });
  });

  test('shows a visible error if polling refresh removes the selected report item', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, {
      onRunFetch: (run, fetchCount) => {
        if (fetchCount < 2) return run;
        return {
          ...run,
          result: {
            ...run.result,
            structured_report: {
              ...run.result.structured_report,
              test_ideas: run.result.structured_report.test_ideas.filter((item: { id: string }) => item.id !== 'T-001'),
            },
          },
        };
      },
    });

    await page.goto('/agents?runId=custom-run-reqs&resultTab=test_ideas&specItemId=T-001&specItemType=test_idea');
    await expect(page.getByTestId('agents-action-status')).toContainText('Report item T-001 was not found in the refreshed agent report.', { timeout: 5000 });
    await expect(page.getByRole('dialog', { name: 'Report Item Unavailable' })).toBeVisible();
  });
});

test.describe('Agents exploratory completed results', () => {
  test('prose-only run shows warning, zero flows, and no spec generation action', async ({ page }) => {
    await authenticate(page);
    const run = completedExploratoryRun({
      summary: 'I documented 4 flows in prose only.',
      coverage: {
        pages_visited: 0,
        flows_discovered: 0,
        forms_interacted: 0,
        errors_found: 0,
        coverage_score: 0,
      },
      event_counts: {},
      diagnostics: {
        evidence_event_count: 0,
        browser_tool_calls: 0,
        successful_browser_tool_calls: 0,
        dedupe_stats: { duplicate_flows_removed: 0 },
      },
      contract_warning: 'The model output claimed flow coverage, but no structured evidence-backed flow summaries were created.',
      exploration_status: 'contract_violation',
      discovered_flow_summaries: [],
      total_flows_discovered: 0,
    });
    await routeAgentsApi(page, { runOverride: run });

    await page.goto(`${APP_BASE}/agents?runId=explorer-run-results`);

    await expect(page.getByTestId('explorer-contract-warnings')).toBeVisible();
    await expect(page.getByTestId('explorer-metric-evidence-events')).toContainText('0');
    await expect(page.getByTestId('explorer-metric-deduped-flows')).toContainText('0');
    await expect(page.getByText('No flows discovered')).toBeVisible();
    await expect(page.getByTestId('explorer-generate-test-specs')).toHaveCount(0);
  });

  test('partial run shows captured artifacts and unsupported candidates without spec generation', async ({ page }) => {
    await authenticate(page);
    await page.route(`${API_BASE}/artifacts/**`, route => route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from('iVBORw0KGgo=', 'base64'),
    }));
    await routeAgentsApi(page, {
      runOverride: {
        ...completedExploratoryRun({
          summary: 'Explorer captured screenshot evidence but no valid flows.',
          coverage: {
            pages_visited: 1,
            flows_discovered: 0,
            forms_interacted: 0,
            errors_found: 0,
            coverage_score: 0.3,
          },
          event_counts: { page_observed: 1, action_result: 1, flow_candidate: 1 },
          diagnostics: {
            evidence_event_count: 3,
            browser_tool_calls: 2,
            successful_browser_tool_calls: 2,
            unsupported_flow_candidates: 1,
            missing_evidence_event_ids: ['evt_999'],
            artifact_count: 1,
            screenshot_count: 1,
            dedupe_stats: { duplicate_flows_removed: 0 },
          },
          contract_warning: 'The model emitted flow candidates with missing evidence event ids; they are shown as unsupported and cannot generate tests.',
          contract_warnings: [
            'The model emitted flow candidates with missing evidence event ids; they are shown as unsupported and cannot generate tests.',
          ],
          artifact_evidence: {
            artifact_count: 1,
            screenshot_count: 1,
            artifacts: [{ name: 'live-step-001.png', path: '/artifacts/explorer-run-results/live-step-001.png', type: 'image' }],
          },
          unsupported_flow_candidates: [{
            id: 'flow_1',
            title: 'Open pricing',
            entry_point: 'https://example.test',
            exit_point: 'https://example.test/pricing',
            missing_evidence_event_ids: ['evt_999'],
          }],
          discovered_flow_summaries: [],
          total_flows_discovered: 0,
        }),
        status: 'completed_partial',
        artifacts: [{ name: 'live-step-001.png', path: '/artifacts/explorer-run-results/live-step-001.png', type: 'image' }],
      },
    });

    await page.goto(`${APP_BASE}/agents?runId=explorer-run-results`);

    await expect(page.getByTestId('explorer-partial-warning')).toContainText('no completed evidence-backed flows');
    await expect(page.getByTestId('explorer-contract-warning')).toHaveCount(1);
    await expect(page.getByTestId('explorer-metric-screenshots')).toContainText('1');
    await expect(page.getByTestId('explorer-metric-artifacts')).toContainText('1');
    await expect(page.getByTestId('explorer-captured-evidence')).toBeVisible();
    await expect(page.getByTestId('explorer-captured-screenshot')).toHaveCount(1);
    await expect(page.getByTestId('explorer-unsupported-flow-candidates')).toBeVisible();
    await expect(page.getByTestId('explorer-unsupported-flow-candidates')).toContainText('missing or empty');
    await expect(page.getByTestId('explorer-unsupported-flow-card')).toContainText('Open pricing');
    await expect(page.getByTestId('explorer-flow-card')).toHaveCount(0);
    await expect(page.getByTestId('explorer-generate-test-specs')).toHaveCount(0);
  });

  test('structured run renders nonzero metrics and flow cards', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, { runOverride: completedExploratoryRun() });

    await page.goto(`${APP_BASE}/agents?runId=explorer-run-results`);

    await expect(page.getByTestId('explorer-metric-evidence-events')).toContainText('4');
    await expect(page.getByTestId('explorer-metric-successful-browser-actions')).toContainText('3');
    await expect(page.getByTestId('explorer-metric-deduped-flows')).toContainText('1');
    await expect(page.getByTestId('explorer-flow-card')).toHaveCount(1);
    await expect(page.getByTestId('explorer-flow-card')).toContainText('Open pricing');
    await expect(page.getByTestId('explorer-generate-test-specs')).toBeVisible();
  });

  test('duplicate flow summaries are not rendered twice', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, {
      runOverride: completedExploratoryRun({
        discovered_flow_summaries: [{
          id: 'flow_1',
          title: 'Open pricing',
          pages: ['https://example.test', 'https://example.test/pricing'],
          steps_count: 2,
          has_happy_path: true,
          has_edge_cases: false,
          entry_point: 'https://example.test',
          exit_point: 'https://example.test/pricing',
          complexity: 'low',
        }],
        total_flows_discovered: 1,
        diagnostics: {
          evidence_event_count: 6,
          browser_tool_calls: 5,
          successful_browser_tool_calls: 5,
          dedupe_stats: { duplicate_flows_removed: 2 },
        },
      }),
    });

    await page.goto(`${APP_BASE}/agents?runId=explorer-run-results`);

    await expect(page.getByTestId('explorer-flow-card')).toHaveCount(1);
    await expect(page.getByTestId('explorer-metric-duplicates-removed')).toContainText('2');
  });
});

test.describe('Agents editable custom report content', () => {
  test('edits a finding and uses the returned run in the report view', async ({ page }) => {
    const patches: Array<{ itemId: string; itemType: string | null; body: Record<string, unknown> }> = [];

    await authenticate(page);
    await routeAgentsApi(page, {
      onPatchReportItem: payload => patches.push(payload),
    });

    await page.goto('/agents?runId=custom-run-reqs&resultTab=findings');
    await page.getByRole('tabpanel').getByRole('button', { name: 'Edit finding F-001' }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit finding F-001' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Title').fill('Checkout postal code validation missing');
    await dialog.getByLabel('Description').fill('Edited finding description from reviewer.');
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByText('F-001: Checkout postal code validation missing')).toBeVisible();
    await expect(page.getByText('Edited finding description from reviewer.')).toBeVisible();
    expect(patches[0]).toMatchObject({
      itemId: 'F-001',
      itemType: 'finding',
      body: {
        patch: {
          title: 'Checkout postal code validation missing',
          description: 'Edited finding description from reviewer.',
        },
      },
    });
  });

  test('edits a test idea before the Create Spec modal opens with edited steps and expected result', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?runId=custom-run-reqs&resultTab=test_ideas');
    await page.getByRole('tabpanel').getByRole('button', { name: 'Edit test idea T-001' }).click();

    const editDialog = page.getByRole('dialog', { name: 'Edit test idea T-001' });
    await expect(editDialog).toBeVisible();
    await editDialog.getByLabel('Steps').fill('Open checkout with edited data\nSubmit a blank edited ZIP');
    await editDialog.getByLabel('Expected').fill('Edited validation feedback is visible.');
    await editDialog.getByRole('button', { name: 'Save Changes' }).click();

    await expect(editDialog).toBeHidden();
    await expect(page.getByText('Open checkout with edited data')).toBeVisible();

    await page.getByRole('tabpanel').getByRole('button', { name: 'Create Spec' }).first().click();
    const specDialog = page.getByRole('dialog');
    await expect(specDialog.getByRole('heading', { name: 'Checkout address validation' })).toBeVisible();
    await expect(specDialog.getByText('Open checkout with edited data')).toBeVisible();
    await expect(specDialog.getByText('Submit a blank edited ZIP')).toBeVisible();
    await expect(specDialog.getByText('Edited validation feedback is visible.')).toBeVisible();
  });

  test('edits a requirement before importing it', async ({ page }) => {
    const patches: Array<{ itemId: string; itemType: string | null; body: Record<string, unknown> }> = [];

    await authenticate(page);
    await routeAgentsApi(page, {
      onPatchReportItem: payload => patches.push(payload),
    });

    await page.goto('/agents?runId=custom-run-reqs&resultTab=requirements');
    await page.getByRole('tabpanel').getByRole('button', { name: 'Edit requirement R-001' }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit requirement R-001' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Title').fill('Checkout requires edited validation feedback');
    await dialog.getByLabel('Acceptance Criteria').fill('Edited empty postal code criterion is imported.');
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByText('R-001: Checkout requires edited validation feedback')).toBeVisible();
    await expect(page.getByText('Edited empty postal code criterion is imported.')).toBeVisible();

    await page.getByRole('button', { name: /^Import$/ }).click();
    await expect(page.getByRole('link', { name: 'REQ-101' })).toHaveAttribute('href', '/requirements?highlight=101');
    expect(patches[0]).toMatchObject({
      itemId: 'R-001',
      itemType: 'requirement',
      body: {
        patch: {
          title: 'Checkout requires edited validation feedback',
          acceptance_criteria: ['Edited empty postal code criterion is imported.'],
        },
      },
    });
  });

  test('edits report summary and scope', async ({ page }) => {
    let patch: Record<string, unknown> | null = null;

    await authenticate(page);
    await routeAgentsApi(page, {
      onPatchReport: payload => {
        patch = payload;
      },
    });

    await page.goto('/agents?runId=custom-run-reqs');
    await page.getByRole('button', { name: 'Edit Report Summary' }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit Report Summary' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Summary').fill('Edited checkout report summary.');
    await dialog.getByLabel('Scope').fill('Edited checkout scope.');
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByText('Edited checkout report summary.')).toBeVisible();
    await expect(page.getByText('Edited checkout scope.')).toBeVisible();
    expect(patch).toMatchObject({
      summary: 'Edited checkout report summary.',
      scope: 'Edited checkout scope.',
    });
  });

  test('keeps the edit dialog open and shows an error when PATCH fails', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page, { failPatchReport: true });

    await page.goto('/agents?runId=custom-run-reqs&resultTab=findings');
    await page.getByRole('tabpanel').getByRole('button', { name: 'Edit finding F-001' }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit finding F-001' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Title').fill('Will not save');
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Report save failed in test.')).toBeVisible();
    await expect(dialog.getByLabel('Title')).toHaveValue('Will not save');
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

    await page.goto('/agents?view=library&agent=custom&definitionId=trip-agent');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Agent Library' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Trip Creator Agent' })).toBeVisible();

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
    await expect(page.getByRole('heading', { name: 'Trip Planner Agent' })).toBeVisible();
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

    await page.goto('/agents?view=library&agent=custom&definitionId=trip-agent');
    await expect(page.getByRole('heading', { name: 'Autonomous Agents' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Agent Library' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Trip Creator Agent' })).toBeVisible();

    await page.getByRole('button', { name: 'Open actions for Trip Creator Agent' }).click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Archive Custom Agent' })).toBeVisible();
    await expect(dialog.getByText('Archive "Trip Creator Agent"?')).toBeVisible();

    await dialog.getByRole('button', { name: /^Archive$/ }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByRole('heading', { name: 'Trip Creator Agent' })).toHaveCount(0);
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

  test('cleans stale running queue tasks from the queue tab', async ({ page }) => {
    let cleanCalls = 0;

    await authenticate(page);
    await routeAgentsApi(page, {
      queueStatus: {
        active: 0,
        raw_running: 1,
        stale_running: 1,
        orphaned_tasks: 1,
        running_tasks: [],
      },
      onCleanStaleQueue: () => {
        cleanCalls += 1;
        return {
          cleaned: 1,
          cancelled_orphaned: 1,
          timed_out: 0,
          terminal_owner: 0,
          orphaned_queued: 0,
          stale_ownerless_queued: 0,
          missing_task_refs: 0,
          skipped_active: 0,
        };
      },
    });

    await page.goto('/agents?view=queue');
    await expect(page.getByText('1 stale running task')).toBeVisible();

    await page.getByRole('button', { name: /Clean stale tasks/ }).click();

    await expect.poll(() => cleanCalls).toBe(1);
    await expect(page.getByText(/Cleaned 1 stale queue task/)).toBeVisible();
  });

  test('searches structured report items', async ({ page }) => {
    let generateCalls = 0;

    await authenticate(page);
    await routeAgentsApi(page, {
      onGenerateReportSpec: () => {
        generateCalls += 1;
      },
    });

    await page.goto('/agents?view=reports&reportQ=address&reportType=finding&reportSeverity=high');
    await expect(page.getByRole('heading', { name: 'Search Reports' })).toBeVisible();
    await expect(page.getByText('Checkout address validation missing')).toBeVisible();

    await page.getByRole('link', { name: 'Open report' }).click();

    await expect(page).toHaveURL(/view=run/);
    await expect(page).toHaveURL(/runId=custom-run-reqs/);
    await expect(page).toHaveURL(/resultTab=findings/);
    await expect(page).toHaveURL(/specItemId=F-001/);
    await expect(page).toHaveURL(/specItemType=finding/);

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Checkout address validation missing' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Generate Test Spec' })).toBeVisible();
    expect(generateCalls).toBe(0);
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

  test('retries failed agent runs in place and keeps the selected run URL', async ({ page }) => {
    let retryCalls = 0;

    await authenticate(page);
    await routeAgentsApi(page, {
      runOverride: {
        status: 'failed',
        result: { error: 'Activity task failed' },
        progress: { phase: 'failed', message: 'Activity task failed' },
      },
      onRetryRun: id => {
        expect(id).toBe('custom-run-reqs');
        retryCalls += 1;
      },
    });

    await page.goto('/agents?runId=custom-run-reqs');
    await expect(page.getByTestId('agents-retry-run')).toBeVisible();
    await page.getByTestId('agents-retry-run').click();

    await expect.poll(() => retryCalls).toBe(1);
    await expect(page).toHaveURL(/runId=custom-run-reqs/);
    await expect(page).not.toHaveURL(/custom-run-started/);
    await expect(page.getByTestId('agents-action-status')).toContainText('Retrying in same run using saved browser auth/session artifacts.');
  });

  test('opens the custom agent builder from create intent and returns to workflow after save', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?agent=custom&create=1&returnTo=/workflow');
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();
    await expectDialogInViewport(page, dialog);
    await dialog.getByLabel('Name').fill('Workflow Agent');
    await dialog.getByLabel('System Prompt').fill('Inspect workflow-created scenarios.');
    await dialog.getByRole('button', { name: 'Save Agent' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByRole('link', { name: 'Return to Workflow' })).toHaveAttribute('href', '/workflow');
  });

  test('clears create intent when cancelling the custom agent builder', async ({ page }) => {
    await authenticate(page);
    await routeAgentsApi(page);

    await page.goto('/agents?agent=custom&create=1&returnTo=/workflow');
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create Custom Agent' })).toBeVisible();

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
    await expect(page).not.toHaveURL(/create=1/);
  });
});
