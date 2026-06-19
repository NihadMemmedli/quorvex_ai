import { expect, type Page, type Route } from '@playwright/test';

export const APP_BASE = process.env.BASE_URL || 'http://localhost:3000';
export const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');

const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

type Project = {
  id: string;
  name: string;
  description?: string | null;
  base_url?: string | null;
  created_at: string;
  last_active?: string;
  spec_count: number;
  run_count: number;
  batch_count: number;
};

type MockState = {
  projects: Project[];
  requests: Array<{ method: string; path: string; body: unknown }>;
};

const now = '2026-06-19T09:00:00Z';

const defaultProject: Project = {
  id: 'default',
  name: 'Default',
  description: 'Default E2E project',
  base_url: 'https://example.test',
  created_at: now,
  last_active: now,
  spec_count: 1,
  run_count: 1,
  batch_count: 0,
};

export function createMockState(): MockState {
  return {
    projects: [defaultProject],
    requests: [],
  };
}

export async function authenticateDashboard(page: Page, projectId = 'default') {
  await page.addInitScript(({ selectedProjectId }) => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', selectedProjectId);
    window.localStorage.setItem('sidebar-collapsed-groups', JSON.stringify({
      'supporting-workflows': false,
      'advanced-tools': false,
    }));
  }, { selectedProjectId: projectId });
}

export function attachUiErrorGuards(page: Page, ignoredConsolePatterns: RegExp[] = []) {
  const ignoredPatterns = [
    /A project must be selected before calling this endpoint/,
    ...ignoredConsolePatterns,
  ];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedResponses: string[] = [];

  page.on('console', message => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (ignoredPatterns.some(pattern => pattern.test(text))) return;
    consoleErrors.push(text);
  });

  page.on('pageerror', error => {
    pageErrors.push(error.message);
  });

  page.on('response', response => {
    const url = response.url();
    if (!url.startsWith(APP_BASE) && !url.startsWith(API_BASE)) return;
    if (response.status() >= 500) {
      failedResponses.push(`${response.status()} ${url}`);
    }
  });

  return {
    async assertClean() {
      expect(pageErrors, 'Unexpected browser page errors').toEqual([]);
      expect(failedResponses, 'Unexpected 5xx responses').toEqual([]);
      expect(consoleErrors, 'Unexpected browser console errors').toEqual([]);
    },
  };
}

function apiPath(url: string) {
  const parsed = new URL(url, APP_BASE);
  return parsed.pathname.replace(/^\/backend-proxy/, '');
}

function requestBody(route: Route) {
  try {
    return route.request().postDataJSON();
  } catch {
    return null;
  }
}

async function fulfill(route: Route, json: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', json });
}

function dashboardPayload() {
  return {
    total_specs: 1,
    total_runs: 1,
    success_rate: 100,
    pass_rate: 100,
    avg_duration_seconds: 12,
    flaky_test_count: 0,
    slowest_test_duration: 12,
    last_run: 'Passed',
    last_run_at: now,
    trends: [{ date: '2026-06-19', passed: 1, failed: 0, total: 1, avg_duration: 12 }],
    errors: [],
    slowest_tests: [],
    flaky_tests: [],
    healing_stats: { overall: { total_heals_attempted: 0, total_heals_succeeded: 0, success_rate: 0 } },
    test_growth_trends: {
      has_data: true,
      trend: [{ date: '2026-06-19', specs: 1, generated: 1, passing: 1 }],
      latest: { specs: 1, generated: 1, passing: 1 },
      growth: { specs: 0, generated: 0, passing: 0 },
    },
    time_of_day_analysis: [],
    failure_patterns: [],
  };
}

function emptyApiSpecs() {
  return {
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
  };
}

function emptyGeneratedTests() {
  return {
    items: [],
    total: 0,
    has_more: false,
    summary: {
      total_tests: 0,
      passing: 0,
      failing: 0,
      never_run: 0,
    },
  };
}

function settingsPayload() {
  return {
    llm_provider: 'none',
    openai_api_key_set: false,
    anthropic_api_key_set: false,
    target_url: 'https://example.test',
    headless: true,
    browser: 'chromium',
    timeout: 30000,
    max_retries: 1,
    enable_healing: true,
  };
}

function workflowCatalog() {
  return {
    step_types: [
      {
        type: 'start_autopilot',
        label: 'Run AutoPilot',
        description: 'Start an AutoPilot session.',
        category: 'Automation',
        default_input: { entry_url: 'https://example.test' },
      },
      {
        type: 'review_gate',
        label: 'Review Results',
        description: 'Pause for a manual review.',
        category: 'Control',
        default_input: {},
      },
    ],
    templates: [],
  };
}

function mockJsonFor(path: string, method: string): unknown {
  if (path.startsWith('/dashboard')) return dashboardPayload();

  if (path.startsWith('/auth/refresh')) return { access_token: 'access-token', refresh_token: 'refresh-token' };
  if (path.startsWith('/auth/login')) return { access_token: 'access-token', refresh_token: 'refresh-token' };
  if (path.startsWith('/auth/register')) return { id: 'user-new', email: 'new-user@example.test' };
  if (path.startsWith('/auth/me')) {
    return {
      id: 'user-1',
      email: 'qa@example.com',
      full_name: 'QA User',
      is_active: true,
      is_superuser: true,
      email_verified: true,
      created_at: now,
      last_login: now,
    };
  }
  if (path.startsWith('/auth/logout')) return { ok: true };

  if (path.startsWith('/queue-status') || path.startsWith('/api/agents/queue-status')) {
    return {
      mode: 'browser_pool',
      active: 0,
      max: 4,
      queued: 0,
      available: 4,
      workers_alive: 1,
      running_tasks: [],
    };
  }

  if (path.startsWith('/settings')) return settingsPayload();
  if (path.startsWith('/execution-settings')) return { max_workers: 2, default_timeout: 30000, retries: 1 };
  if (path.startsWith('/api/browser-pool/status')) return { status: 'ready', active: 0, available: 4 };
  if (path.startsWith('/api/mobile-testing/health')) return { status: 'unavailable', devices: [] };

  if (path.startsWith('/specs/list')) {
    const item = {
      name: 'e2e-smoke.md',
      path: 'specs/e2e-smoke.md',
      content: '# E2E Smoke\n\nValidate the dashboard.',
      is_template: false,
      has_generated_test: true,
      tags: ['e2e'],
      updated_at: now,
    };
    return {
      items: [item],
      specs: [item],
      total: 1,
      has_more: false,
      folders: [],
    };
  }
  if (path.startsWith('/specs/folders')) return { folders: [] };
  if (path.startsWith('/specs/automated')) return { specs: [], total: 0 };
  if (path.startsWith('/spec-metadata')) return {};
  if (path === '/specs' && method === 'POST') return { name: 'e2e-created.md', path: 'specs/e2e-created.md' };
  if (path.startsWith('/runs/bulk')) return { batch_id: 'batch-e2e', run_ids: ['run-e2e'] };
  if (path === '/runs' && method === 'POST') return { run_id: 'run-e2e', status: 'queued' };
  if (path.startsWith('/runs')) return { runs: [], total: 0, has_more: false };
  if (path.startsWith('/stop-all') || path.startsWith('/queue/clear')) return { ok: true };

  if (path.startsWith('/regression/batches/trend')) return [];
  if (path.startsWith('/regression/flaky-tests')) return [];
  if (path.startsWith('/regression/batches')) return { batches: [], total: 0, has_more: false };

  if (path.startsWith('/requirements/stats')) return { total: 0, confirmed: 0, draft: 0, needs_review: 0 };
  if (path.startsWith('/requirements/duplicates')) return { duplicates: [] };
  if (path.startsWith('/requirements/check-duplicate')) return { has_exact_match: false, exact_match: null, near_matches: [], recommendation: 'create_new' };
  if (path === '/requirements' && method === 'POST') {
    return {
      id: 'req-e2e',
      req_code: 'REQ-E2E-1',
      title: 'E2E user can authenticate',
      description: 'Created through the mocked UI smoke path.',
      category: 'other',
      priority: 'medium',
      status: 'draft',
      acceptance_criteria: [],
      created_at: now,
      updated_at: now,
    };
  }
  if (path.startsWith('/requirements/generate-jobs')) return { status: 'completed', items: [] };
  if (path.startsWith('/requirements/generate')) return { job_id: 'req-job-e2e', status: 'queued' };
  if (path.startsWith('/requirements')) return { items: [], total: 0, has_more: false };

  if (path.startsWith('/rtm/coverage')) return { total_requirements: 0, covered: 0, partial: 0, uncovered: 0, coverage_percent: 0 };
  if (path.startsWith('/rtm/gaps')) return [];
  if (path.startsWith('/rtm/trend')) return [];
  if (path.startsWith('/rtm/snapshots')) return { snapshots: [] };
  if (path.startsWith('/rtm')) return { items: [], requirements: [], total: 0, has_more: false };

  if (path.startsWith('/api/memory/projects')) return { projects: [{ id: 'default', name: 'Default' }] };
  if (path.startsWith('/api/memory/coverage/gaps')) return [];
  if (path.startsWith('/api/memory/coverage/suggestions')) return [];
  if (path.startsWith('/api/memory/coverage/summary')) return { covered_elements: 0, total_elements: 0, coverage_percentage: 0 };
  if (path.startsWith('/api/memory/diagnostics')) {
    return {
      project_id: 'default',
      memory_enabled: true,
      embedding_model: 'e2e-mock',
      generated_at: now,
      overall_status: 'healthy',
      checks: [{ status: 'healthy', message: 'Mock memory service is ready', details: {} }],
      agent_memory: {
        total: 0,
        ready: 0,
        review_required: 0,
        archived_or_inactive: 0,
        by_kind: {},
        by_type: {},
        by_status: {},
        by_source: {},
      },
      browser_memory: { states: 0, elements: 0, frontier: 0, frontier_by_status: {} },
      selector_patterns: { patterns: 0, avg_success_rate: 0, actions: {} },
      graph: { nodes: 0, edges: 0, node_types: {}, edge_statuses: {}, memory_nodes_without_backing_memory: [] },
      injections: { total: 0, by_stage: {}, by_outcome: {}, missing_memory_ids: [], missing_memory_count: 0 },
      stale_memory: { high_impact_count: 0, older_than_days: 30, items: [] },
      recommended_actions: [],
    };
  }
  if (path.startsWith('/api/memory/effectiveness')) {
    return {
      project_id: 'default',
      days: 30,
      total_injections: 0,
      stage_stats: [],
      top_helpful_memories: [],
      top_harmful_memories: [],
      empty_recall_stages: [],
      stale_injections: [],
      recommended_actions: [],
    };
  }
  if (path.startsWith('/api/memory/patterns')) return [];
  if (path.startsWith('/api/memory/stats')) {
    return { total_patterns: 0, avg_success_rate: 0, action_breakdown: {}, project_id: 'default' };
  }
  if (path.startsWith('/api/memory/browser')) return { project_id: 'default', states: [], elements: [], frontier: [] };
  if (path.startsWith('/api/memory/agent')) return [];
  if (path.startsWith('/api/memory/injections')) return [];
  if (path.startsWith('/api/memory/graph/knowledge')) {
    return {
      nodes: [],
      edges: [],
      stats: { node_count: 0, edge_count: 0, node_types: {}, relationship_types: {} },
    };
  }
  if (path.startsWith('/api/memory/graph/review')) return { edges: [] };
  if (path.startsWith('/api/memory/graph')) {
    return {
      nodes: [],
      edges: [],
      stats: { node_count: 0, edge_count: 0, node_types: {}, relationship_types: {} },
    };
  }
  if (path.startsWith('/api/memory/context-preview')) return { context: '', memories: [] };
  if (path.startsWith('/api/memory')) return { items: [], total: 0 };

  if (path.startsWith('/analytics/coverage-overview')) {
    return { total_specs: 1, total_test_files: 1, specs_with_tests: 1, specs_run_at_least_once: 1, run_coverage_percent: 100 };
  }
  if (path.startsWith('/analytics/pass-rate-trends')) return { trends: [] };
  if (path.startsWith('/analytics/spec-performance')) return { specs: [] };
  if (path.startsWith('/analytics/failure-classification')) return { categories: [] };
  if (path.startsWith('/analytics/flake-detection')) return { flaky_tests: [] };

  if (path.startsWith('/autopilot/sessions')) return [];
  if (path.startsWith('/autopilot/start')) return { id: 'autopilot-e2e', status: 'queued', entry_urls: ['https://example.test'] };
  if (path.startsWith('/autopilot')) return { id: 'autopilot-e2e', status: 'completed', phases: [], questions: [], tasks: [] };

  if (path.startsWith('/exploration')) return [];

  if (path.startsWith('/autonomous/default/diagnostics')) return { status: 'ready', checks: [] };
  if (path.startsWith('/autonomous/default/missions')) return [];
  if (path.startsWith('/autonomous/default/proposals')) return [];
  if (path.startsWith('/autonomous/default/approvals')) return [];
  if (path.startsWith('/autonomous/default/work-items')) return [];
  if (path.startsWith('/autonomous')) return [];

  if (path.startsWith('/api/agents/tools/catalog')) return { tools: [] };
  if (path.startsWith('/api/agents/definitions')) return { definitions: [], items: [] };
  if (path.startsWith('/api/agents/runs')) return { runs: [], items: [], total: 0 };
  if (path.startsWith('/api/agents')) return { items: [], runs: [], total: 0 };

  if (path.startsWith('/workflows/admin/step-types')) return { step_types: workflowCatalog().step_types };
  if (path.startsWith('/workflows/temporal/health')) return { status: 'ready', temporal_available: false };
  if (path.startsWith('/workflows/catalog')) return workflowCatalog();
  if (path.startsWith('/workflows/definitions')) return method === 'POST' ? { id: 'wf-e2e', name: 'E2E Workflow', steps: [] } : [];
  if (path.startsWith('/workflows/runs')) return [];
  if (path.startsWith('/workflows/schedules')) return [];
  if (path.startsWith('/workflows/analytics')) return { runs_by_status: {}, success_rate: 0 };
  if (path.startsWith('/workflows/notifications')) return [];
  if (path.startsWith('/workflows/events')) return [];
  if (path.startsWith('/workflows/validate')) return { valid: true, errors: [] };
  if (path.startsWith('/workflows')) return { ok: true };

  if (path.startsWith('/api-testing/specs')) return emptyApiSpecs();
  if (path.startsWith('/api-testing/generated-tests')) return emptyGeneratedTests();
  if (path.startsWith('/api-testing/jobs')) return [];
  if (path.startsWith('/api-testing/runs/latest-by-spec')) return { specs: {} };
  if (path.startsWith('/api-testing/runs')) return { items: [], total: 0, has_more: false };
  if (path.startsWith('/api-testing/import-history')) return { items: [], total: 0, has_more: false };
  if (path.startsWith('/api-testing')) return { job_id: 'api-job-e2e', status: 'completed', message: 'Dry-run completed' };

  if (path.startsWith('/load-testing/status')) return { mode: 'local', workers_connected: 0, queue_length: 0, running_tasks: 0, load_test_active: false };
  if (path.startsWith('/load-testing/system-limits')) {
    return {
      k6_max_vus: 50,
      k6_max_duration: '5m',
      k6_timeout_seconds: 360,
      max_browser_instances: 4,
      browser_slots_available: 4,
      browser_slots_running: 0,
      execution_mode: 'local',
      workers_connected: 0,
      effective_max_vus: 50,
      load_test_lock_active: false,
      lock_ttl_seconds: 0,
    };
  }
  if (path.startsWith('/load-testing/dashboard')) {
    return {
      total_runs: 0,
      completed_runs: 0,
      failed_runs: 0,
      pass_rate: 0,
      avg_p95_ms: 0,
      avg_rps: 0,
      total_requests_all_time: 0,
      recent_runs: [],
      p95_trend: [],
      top_slow_endpoints: [],
    };
  }
  if (path.startsWith('/load-testing/specs')) return [];
  if (path.startsWith('/load-testing/scripts')) return [];
  if (path.startsWith('/load-testing/runs')) return { runs: [], total: 0, has_more: false };
  if (path.startsWith('/load-testing/jobs')) return { job_id: 'load-job-e2e', status: 'completed' };
  if (path.startsWith('/load-testing')) return { job_id: 'load-job-e2e', status: 'completed' };

  if (path.startsWith('/security-testing/capabilities')) {
    return {
      quick: { available: true, message: 'Ready' },
      nuclei: { available: false, path: null, message: 'Unavailable in E2E dry run' },
      zap: { available: false, version: null, host: 'localhost', port: 8090, message: 'Unavailable in E2E dry run', error: null },
      defaults: { active_scan_level: 'safe', security_scan_timeout: 60, nuclei_timeout: 60 },
    };
  }
  if (path.startsWith('/security-testing/specs')) return [];
  if (path.startsWith('/security-testing/runs')) return [];
  if (path.startsWith('/security-testing/findings/summary')) {
    return {
      total_open: 0,
      by_severity: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
      by_status: { open: 0, false_positive: 0, fixed: 0, accepted_risk: 0 },
    };
  }
  if (path.startsWith('/security-testing/findings')) return { findings: [], total: 0 };
  if (path.startsWith('/security-testing/targets')) return [];
  if (path.startsWith('/security-testing')) return { job_id: 'sec-job-e2e', status: 'completed' };

  if (path.startsWith('/database-testing/connections')) return [];
  if (path.startsWith('/database-testing/specs')) return [];
  if (path.startsWith('/database-testing/runs')) return { runs: [], total: 0 };
  if (path.startsWith('/database-testing')) return { job_id: 'db-job-e2e', status: 'completed' };

  if (path.startsWith('/llm-testing/openrouter/models')) return { models: [] };
  if (path.startsWith('/llm-testing/providers')) return [];
  if (path.startsWith('/llm-testing/specs')) return [];
  if (path.startsWith('/llm-testing/datasets')) return [];
  if (path.startsWith('/llm-testing/runs')) return [];
  if (path.startsWith('/llm-testing/comparisons')) return [];
  if (path.startsWith('/llm-testing/schedules')) return [];
  if (path.startsWith('/llm-testing/analytics')) return { items: [], trends: [], overview: {} };
  if (path.startsWith('/llm-testing')) return { job_id: 'llm-job-e2e', status: 'completed' };

  if (path.startsWith('/scheduling/validate-cron')) return { valid: true, description: 'Every day' };
  if (path.startsWith('/scheduling/default/schedules')) return [];
  if (path.startsWith('/scheduling/default/executions')) return { executions: [], total: 0 };
  if (path.startsWith('/scheduling')) return [];

  if (path.startsWith('/projects/default/ci/providers')) return [];
  if (path.startsWith('/projects/default/ci/workflows')) return [];
  if (path.startsWith('/projects/default/ci/runs')) return [];
  if (path.startsWith('/projects/default/ci')) return { ok: true };
  if (path.startsWith('/github/default/quality-gates')) return [];
  if (path.startsWith('/github/default/pr-advisor/analyses')) return [];
  if (path.startsWith('/github/default/config')) return { configured: false };
  if (path.startsWith('/github/default')) return { configured: false };
  if (path.startsWith('/gitlab/default') || path.startsWith('/jira/default') || path.startsWith('/testrail/default')) return { configured: false };

  if (path.startsWith('/test-data/datasets')) return { datasets: [], items: [], total: 0 };
  if (path.startsWith('/test-data')) return { items: [], total: 0 };

  if (path === '/recordings/start') {
    return {
      id: 'recording-e2e',
      project_id: 'default',
      name: 'E2E recording',
      target_url: 'https://example.test/login',
      status: 'recording',
      created_at: now,
      started_at: now,
      stopped_at: null,
      events_count: 0,
      artifacts: [],
    };
  }
  if (path.startsWith('/recordings/recording-e2e/stop')) {
    return {
      id: 'recording-e2e',
      project_id: 'default',
      name: 'E2E recording',
      target_url: 'https://example.test/login',
      status: 'stopped',
      created_at: now,
      started_at: now,
      stopped_at: now,
      events_count: 1,
      artifacts: [],
    };
  }
  if (path.startsWith('/recordings/recording-e2e/import')) {
    return {
      session: {
        id: 'recording-e2e',
        project_id: 'default',
        name: 'E2E recording',
        target_url: 'https://example.test/login',
        status: 'imported',
        created_at: now,
        started_at: now,
        stopped_at: now,
        events_count: 1,
        artifacts: [],
      },
      spec_name: 'recorded-e2e.md',
      spec_path: 'specs/recorded-e2e.md',
    };
  }
  if (path.startsWith('/recordings')) return { items: [], total: 0 };

  if (path.startsWith('/users')) {
    if (/^\/users\/[^/]+\/projects$/.test(path)) return { user_id: 'user-1', projects: [] };
    return {
      users: [
        {
          id: 'user-1',
          email: 'qa@example.com',
          full_name: 'QA User',
          is_active: true,
          is_superuser: true,
          email_verified: true,
          created_at: now,
          last_login: now,
        },
      ],
      total: 1,
    };
  }

  if (path.startsWith('/chat/conversations')) return { conversations: [], items: [], total: 0 };
  if (path.startsWith('/chat/project-context')) return {};
  if (path.startsWith('/chat/search-entities')) return { items: [] };
  if (path.startsWith('/chat')) return { ok: true, message: { id: 'msg-e2e', content: 'Mock assistant response' } };

  if (path.startsWith('/api/prd/projects')) return { projects: [] };
  if (path.startsWith('/api/prd')) return { items: [], features: [], generations: [] };
  if (path.startsWith('/prd')) return { items: [] };

  return { ok: true, items: [], total: 0 };
}

async function handleProjectRoute(route: Route, state: MockState, path: string, method: string) {
  if (path === '/projects' && method === 'GET') {
    return fulfill(route, { projects: state.projects });
  }

  if (path === '/projects' && method === 'POST') {
    const body = requestBody(route) as Partial<Project> | null;
    const project: Project = {
      id: `project-${state.projects.length + 1}`,
      name: body?.name || `Project ${state.projects.length + 1}`,
      description: body?.description ?? '',
      base_url: body?.base_url ?? '',
      created_at: now,
      last_active: now,
      spec_count: 0,
      run_count: 0,
      batch_count: 0,
    };
    state.projects.push(project);
    return fulfill(route, project, 201);
  }

  const projectMatch = path.match(/^\/projects\/([^/]+)$/);
  if (projectMatch && method === 'PUT') {
    const id = decodeURIComponent(projectMatch[1]);
    const body = requestBody(route) as Partial<Project> | null;
    const project = state.projects.find(candidate => candidate.id === id);
    if (!project) return fulfill(route, { detail: 'Project not found' }, 404);
    Object.assign(project, body);
    return fulfill(route, project);
  }

  if (projectMatch && method === 'DELETE') {
    const id = decodeURIComponent(projectMatch[1]);
    state.projects = state.projects.filter(project => project.id !== id);
    return fulfill(route, { status: 'deleted', id });
  }

  if (path.startsWith('/projects/default/credentials')) {
    return fulfill(route, { credentials: [], items: [] });
  }

  if (path.startsWith('/projects/default/browser-auth-sessions')) {
    return fulfill(route, { sessions: [] });
  }

  if (/^\/projects\/[^/]+\/my-role$/.test(path)) return fulfill(route, { role: 'owner' });
  if (/^\/projects\/[^/]+\/members/.test(path)) return fulfill(route, { members: [] });

  return null;
}

export async function installDashboardApiMocks(page: Page, state = createMockState()) {
  await Promise.all(API_PREFIXES.map(prefix => page.route(`${prefix}/**`, async route => {
    const method = route.request().method();
    const path = apiPath(route.request().url());
    state.requests.push({ method, path, body: method === 'GET' ? null : requestBody(route) });

    const projectHandled = await handleProjectRoute(route, state, path, method);
    if (projectHandled !== null) return;

    await fulfill(route, mockJsonFor(path, method));
  })));

  return state;
}

export async function expectPageReady(page: Page, heading: string | RegExp) {
  await expect(page.locator('main').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible({ timeout: 20_000 });
}
