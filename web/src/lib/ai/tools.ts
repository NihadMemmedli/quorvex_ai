import { tool } from 'ai';
import { z } from 'zod';
import { backendFetch } from './backend-client';

type ToolResult = Record<string, unknown> | null;

// ===== Mutating tool execution configs (used by proxy route for HitL approval) =====

export const MUTATING_TOOL_CONFIGS: Record<string, {
  label: string;
  method: string;
  getPath: (args: Record<string, unknown>) => string;
  getBody?: (args: Record<string, unknown>, projectId?: string) => Record<string, unknown>;
}> = {
  runTestSpec: {
    label: 'Run Test Spec',
    method: 'POST',
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid }),
  },
  startExploration: {
    label: 'Start Exploration',
    method: 'POST',
    getPath: () => '/exploration/start',
    getBody: (args, pid) => ({ entry_url: args.url, project_id: pid, max_interactions: args.maxInteractions ?? 50 }),
  },
  generateRequirements: {
    label: 'Generate Requirements',
    method: 'POST',
    getPath: (args) => `/requirements/generate?project_id=${args._projectId || 'default'}`,
    getBody: (args) => ({ exploration_session_id: args.sessionId }),
  },
  createTestSpec: {
    label: 'Create Test Spec',
    method: 'POST',
    getPath: () => '/specs',
    getBody: (args, pid) => ({ name: args.specName, content: args.content, project_id: pid }),
  },
  runRegressionBatch: {
    label: 'Run Regression Batch',
    method: 'POST',
    getPath: () => '/runs/bulk',
    getBody: (args, pid) => ({ spec_names: args.specNames, project_id: pid }),
  },
  triggerSecurityScan: {
    label: 'Trigger Security Scan',
    method: 'POST',
    getPath: () => '/security-testing/scan/quick',
    getBody: (args, pid) => ({ target_url: args.url, project_id: pid }),
  },
  retryFailedRun: {
    label: 'Retry Failed Run',
    method: 'POST',
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid }),
  },
  updateTestSpec: {
    label: 'Update Test Spec',
    method: 'PUT',
    getPath: (args) => `/specs/${encodeURIComponent(String(args.specName))}`,
    getBody: (args) => ({ content: args.content, reason: args.reason }),
  },
  healFailedRun: {
    label: 'Heal Failed Run',
    method: 'POST',
    getPath: () => '/runs',
    getBody: (args) => ({ spec_name: args.specName, hybrid_mode: args.useHybridHealing }),
  },
  triggerScheduleNow: {
    label: 'Trigger Schedule Now',
    method: 'POST',
    getPath: (args) => `/scheduling/${args._projectId || 'default'}/schedules/${args.scheduleId}/run-now`,
  },
  rerunFailedTests: {
    label: 'Rerun Failed Tests',
    method: 'POST',
    getPath: (args) => `/regression/batches/${args.batchId}/rerun-failed`,
  },
  analyzeLoadTestRun: {
    label: 'Analyze Load Test Run',
    method: 'POST',
    getPath: (args) => `/load-testing/runs/${args.runId}/analyze`,
  },
  analyzeSecurityRun: {
    label: 'Analyze Security Run',
    method: 'POST',
    getPath: (args) => `/security-testing/analyze/${args.runId}`,
  },
  triageSecurityFinding: {
    label: 'Triage Security Finding',
    method: 'PATCH',
    getPath: (args) => `/security-testing/findings/${args.findingId}/status`,
    getBody: (args) => ({ status: args.status, notes: args.notes }),
  },
  suggestLlmSpecImprovements: {
    label: 'Suggest LLM Spec Improvements',
    method: 'POST',
    getPath: (args) => `/llm-testing/specs/${encodeURIComponent(String(args.specName))}/suggest-improvements`,
  },
  suggestDbFixes: {
    label: 'Suggest DB Fixes',
    method: 'POST',
    getPath: (args) => `/database-testing/suggest/${args.runId}`,
  },
  startAutoPilot: {
    label: 'Start Auto Pilot',
    method: 'POST',
    getPath: () => '/autopilot/start',
    getBody: (args, pid) => ({
      entry_urls: args.urls,
      project_id: pid || 'default',
      instructions: args.instructions || undefined,
      max_interactions: args.maxInteractions ?? 50,
      reactive_mode: true,
    }),
  },
  answerAutoPilotQuestion: {
    label: 'Answer Auto Pilot Question',
    method: 'POST',
    getPath: (args) => `/autopilot/${args.sessionId}/answer`,
    getBody: (args) => ({
      question_id: args.questionId,
      answer_text: args.answer,
    }),
  },
  cancelAutoPilot: {
    label: 'Cancel Auto Pilot',
    method: 'POST',
    getPath: (args) => `/autopilot/${args.sessionId}/cancel`,
  },
};

export const MUTATING_TOOL_NAMES = new Set(Object.keys(MUTATING_TOOL_CONFIGS));

/**
 * Create all assistant tools with the given auth context.
 * Each tool uses AI SDK v6 tool() with proper Zod schemas.
 */
export function createAssistantTools(authToken?: string, projectId?: string) {
  const opts = { authToken, projectId };

  function projectParams() {
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    return params;
  }

  async function fetchTool(path: string, method = 'GET', body?: Record<string, unknown>): Promise<ToolResult> {
    const res = await backendFetch(path, { ...opts, method, body });
    if (!res.ok) return { error: res.error } as ToolResult;
    return res.data as ToolResult;
  }

  return {
    // ===== Read-only tools =====

    getDashboardStats: tool({
      description: 'Get dashboard overview statistics: total specs, recent runs, pass rates, and trends.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        return fetchTool('/dashboard');
      },
    }),

    listTestSpecs: tool({
      description: 'List available test specifications with their status and tags. Optionally filter by tag. Supports pagination via limit/offset — check has_more in response to know if more results exist.',
      inputSchema: z.object({
        tag: z.string().optional().describe('Filter specs by tag'),
        limit: z.number().optional().default(100).describe('Max results to return (default 100, max 200)'),
        offset: z.number().optional().default(0).describe('Pagination offset to fetch next page'),
      }),
      execute: async ({ tag, limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        if (tag) params.set('tag', tag);
        if (limit) params.set('limit', String(limit));
        if (offset) params.set('offset', String(offset));
        return fetchTool(`/specs?${params}`);
      },
    }),

    getTestRunDetails: tool({
      description: 'Get detailed results for a specific test run including status, duration, and error messages.',
      inputSchema: z.object({
        runId: z.string().describe('The test run ID'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/runs/${runId}`);
      },
    }),

    getRecentRuns: tool({
      description: 'Get recent test execution history with pass/fail status. Supports pagination via limit/offset.',
      inputSchema: z.object({
        limit: z.number().optional().default(50).describe('Number of recent runs to fetch (default 50)'),
        offset: z.number().optional().default(0).describe('Pagination offset'),
      }),
      execute: async ({ limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 50));
        if (offset) params.set('offset', String(offset));
        return fetchTool(`/runs?${params}`);
      },
    }),

    listExplorations: tool({
      description: 'List AI exploration sessions with their status, pages/flows discovered.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/exploration?${params}`);
      },
    }),

    getRequirements: tool({
      description: 'List requirements with their category, priority, and coverage status.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements?${params}`);
      },
    }),

    getRTMSummary: tool({
      description: 'Get requirements traceability matrix coverage summary: covered, partial, uncovered requirements.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/coverage?${params}`);
      },
    }),

    getLoadTestResults: tool({
      description: 'Get load test run history with performance metrics (response times, RPS, error rates).',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/runs?${params}`);
      },
    }),

    getSecurityFindings: tool({
      description: 'Get security scan findings summary with severity counts (critical, high, medium, low).',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/security-testing/findings/summary?${params}`);
      },
    }),

    getBrowserPoolStatus: tool({
      description: 'Get current browser resource pool status: active browsers, queue length, available slots.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        return fetchTool('/api/browser-pool/status');
      },
    }),

    getPassRateTrends: tool({
      description: 'Get test pass rate trends over time with daily data points.',
      inputSchema: z.object({
        period: z.enum(['7d', '30d', '90d']).optional().default('30d'),
      }),
      execute: async ({ period }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('period', period ?? '30d');
        return fetchTool(`/analytics/pass-rate-trends?${params}`);
      },
    }),

    getFlakeDetection: tool({
      description: 'Detect flaky tests that intermittently pass and fail.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/analytics/flake-detection?${params}`);
      },
    }),

    getFailureClassification: tool({
      description: 'Get failure classification breakdown by category (selector, timeout, assertion, network, etc).',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/analytics/failure-classification?${params}`);
      },
    }),

    getSpecContent: tool({
      description: 'Get the full content of a test specification file.',
      inputSchema: z.object({
        specName: z.string().describe('The spec file name e.g. login-test.md'),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/specs/${specName}?${params}`);
      },
    }),

    getSpecGeneratedCode: tool({
      description: 'Get the generated Playwright test code for a spec.',
      inputSchema: z.object({
        specName: z.string().describe('The spec file name'),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/specs/${specName}/generated-code?${params}`);
      },
    }),

    getExplorationDetails: tool({
      description: 'Get detailed exploration session results including discovered pages, flows, and API endpoints.',
      inputSchema: z.object({
        sessionId: z.string().describe('The exploration session ID'),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        return fetchTool(`/exploration/${sessionId}/details`);
      },
    }),

    getRegressionBatches: tool({
      description: 'Get regression batch results with pass/fail counts and duration. Supports pagination via limit/offset.',
      inputSchema: z.object({
        limit: z.number().optional().default(50).describe('Number of batches to fetch (default 50)'),
        offset: z.number().optional().default(0).describe('Pagination offset'),
      }),
      execute: async ({ limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 50));
        if (offset) params.set('offset', String(offset));
        return fetchTool(`/regression/batches?${params}`);
      },
    }),

    getSecurityRunDetails: tool({
      description: 'Get detailed security scan results including findings by severity.',
      inputSchema: z.object({
        runId: z.string().describe('The security scan run ID'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/security-testing/runs/${runId}`);
      },
    }),

    // ===== Memory & Knowledge Base tools =====

    searchMemory: tool({
      description: 'Search the memory system for similar test patterns by description. Uses semantic search to find proven test approaches.',
      inputSchema: z.object({
        description: z.string().describe('Description of what you are looking for (e.g., "login form submission")'),
        nResults: z.number().optional().default(5).describe('Number of results'),
        minSuccessRate: z.number().optional().default(0.5).describe('Minimum success rate filter (0-1)'),
      }),
      execute: async ({ description, nResults, minSuccessRate }): Promise<ToolResult> => {
        return fetchTool('/api/memory/similar', 'POST', {
          description,
          n_results: nResults ?? 5,
          min_success_rate: minSuccessRate ?? 0.5,
          project_id: projectId,
        });
      },
    }),

    getProvenSelectors: tool({
      description: 'Get proven CSS/role selectors that have worked well for similar UI elements in previous tests.',
      inputSchema: z.object({
        elementDescription: z.string().describe('Description of the UI element (e.g., "submit button", "email input")'),
        action: z.string().optional().describe('Action type filter (e.g., "click", "fill")'),
        minSuccessRate: z.number().optional().default(0.7).describe('Minimum success rate (0-1)'),
      }),
      execute: async ({ elementDescription, action, minSuccessRate }): Promise<ToolResult> => {
        const params = new URLSearchParams();
        params.set('element_description', elementDescription);
        if (action) params.set('action', action);
        params.set('min_success_rate', String(minSuccessRate ?? 0.7));
        if (projectId) params.set('project_id', projectId);
        return fetchTool(`/api/memory/selectors?${params}`);
      },
    }),

    getCoverageGaps: tool({
      description: 'Get untested elements and flows discovered during exploration that lack test coverage.',
      inputSchema: z.object({
        url: z.string().optional().describe('Filter gaps by URL'),
        maxResults: z.number().optional().default(20).describe('Maximum results'),
      }),
      execute: async ({ url, maxResults }): Promise<ToolResult> => {
        const params = new URLSearchParams();
        if (url) params.set('url', url);
        params.set('max_results', String(maxResults ?? 20));
        if (projectId) params.set('project_id', projectId);
        return fetchTool(`/api/memory/coverage/gaps?${params}`);
      },
    }),

    getTestSuggestions: tool({
      description: 'Get AI-powered test suggestions based on coverage analysis and discovered application structure.',
      inputSchema: z.object({
        url: z.string().optional().describe('Base URL for context'),
        feature: z.string().optional().describe('Feature name for context'),
        maxSuggestions: z.number().optional().default(10).describe('Maximum suggestions'),
      }),
      execute: async ({ url, feature, maxSuggestions }): Promise<ToolResult> => {
        const params = new URLSearchParams();
        if (url) params.set('url', url);
        if (feature) params.set('feature', feature);
        params.set('max_suggestions', String(maxSuggestions ?? 10));
        if (projectId) params.set('project_id', projectId);
        return fetchTool(`/api/memory/coverage/suggestions?${params}`);
      },
    }),

    // ===== Action tools (mutating) =====

    runTestSpec: tool({
      description: 'Execute a test specification. Returns a run ID that can be used to check status. IMPORTANT: Use the spec_name field from run data (the file name like "login-test.md"), NOT the test_name (human-friendly display name).',
      inputSchema: z.object({
        specName: z.string().describe('The spec file name/path (e.g. "login-test.md"). Use spec_name from run data, not the human-friendly test_name.'),
      }),
    }),

    startExploration: tool({
      description: 'Start an AI-powered exploration of a web application URL to discover pages, flows, and API endpoints.',
      inputSchema: z.object({
        url: z.string().describe('The URL to explore'),
        maxInteractions: z.number().optional().default(50).describe('Maximum interactions during exploration'),
      }),
    }),

    generateRequirements: tool({
      description: 'Generate functional requirements from exploration session data using AI.',
      inputSchema: z.object({
        sessionId: z.string().describe('The exploration session ID to generate requirements from'),
      }),
    }),

    createTestSpec: tool({
      description: 'Create a new test specification.',
      inputSchema: z.object({
        specName: z.string(),
        content: z.string().describe('Markdown spec content with steps'),
      }),
    }),

    runRegressionBatch: tool({
      description: 'Run multiple test specs as a regression batch.',
      inputSchema: z.object({
        specNames: z.array(z.string()).describe('Array of spec names to run as a batch'),
      }),
    }),

    triggerSecurityScan: tool({
      description: 'Run a quick security scan on a URL.',
      inputSchema: z.object({
        url: z.string().describe('The target URL to scan'),
      }),
    }),

    retryFailedRun: tool({
      description: 'Re-run a test that previously failed. IMPORTANT: Use the spec_name field from run data (the file name like "login-test.md"), NOT the test_name (human-friendly display name).',
      inputSchema: z.object({
        specName: z.string().describe('The spec file name (e.g. "login-test.md"). Use spec_name from run data, not the human-friendly test_name.'),
      }),
    }),

    pollRunStatus: tool({
      description: 'Check the current status of a running test. Use this to poll for completion after starting a run.',
      inputSchema: z.object({
        runId: z.string().describe('The run ID to check status for'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/runs/${runId}`);
      },
    }),

    navigateToPage: tool({
      description: 'Suggest a dashboard page for the user to navigate to. Returns a URL path that the user can click.',
      inputSchema: z.object({
        path: z.string().describe('The dashboard page path (e.g. "/specs", "/exploration", "/runs")'),
        reason: z.string().describe('Why you are suggesting this navigation'),
      }),
      execute: async ({ path, reason }): Promise<ToolResult> => {
        return { navigateTo: path, reason };
      },
    }),

    // ===== Spec Management Tools =====

    updateTestSpec: tool({
      description: 'Update the content of a test specification. Use after analyzing a spec with getSpecContent.',
      inputSchema: z.object({
        specName: z.string().describe('The spec file name (e.g., "login-test.md")'),
        content: z.string().describe('The new spec content in markdown format'),
        reason: z.string().describe('Brief reason for the update'),
      }),
    }),

    listSpecTemplates: tool({
      description: 'List available test specification templates that can be included in specs using @include directive.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        return fetchTool('/specs/templates');
      },
    }),

    // ===== Run Diagnostics Tools =====

    getRunLogs: tool({
      description: 'Get detailed execution logs for a test run, including step-by-step results and error messages. Use this to diagnose why a test failed.',
      inputSchema: z.object({
        runId: z.string().describe('The test run ID'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        const runDetails = await fetchTool(`/runs/${runId}`);
        const validationData = await fetchTool(`/runs/${runId}/validation`).catch(() => null);
        return {
          ...((runDetails as Record<string, unknown>) || {}),
          validation: validationData,
        } as ToolResult;
      },
    }),

    healFailedRun: tool({
      description: 'Re-run a failed test with healing enabled. Creates a new test run for the same spec. IMPORTANT: Use the spec_name field from run data (the file name like "login-test.md"), NOT the test_name.',
      inputSchema: z.object({
        specName: z.string().describe('The spec file name (e.g. "login-test.md"). Use spec_name from run data, not the human-friendly test_name.'),
        useHybridHealing: z.boolean().optional().default(false).describe('Use extended hybrid healing mode'),
      }),
    }),

    // ===== LLM Testing Tools =====

    getLlmProviders: tool({
      description: 'List configured LLM providers with their health status and pricing.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/llm-testing/providers?${params}`);
      },
    }),

    getLlmTestRuns: tool({
      description: 'Get recent LLM test execution history. Supports pagination via limit/offset.',
      inputSchema: z.object({
        limit: z.number().optional().default(50).describe('Number of runs to fetch (default 50)'),
        offset: z.number().optional().default(0).describe('Pagination offset'),
      }),
      execute: async ({ limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 50));
        if (offset) params.set('offset', String(offset));
        return fetchTool(`/llm-testing/runs?${params}`);
      },
    }),

    getLlmAnalytics: tool({
      description: 'Get LLM testing analytics overview including trends and performance metrics.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/llm-testing/analytics/overview?${params}`);
      },
    }),

    // ===== Schedule Management Tools =====

    listSchedules: tool({
      description: 'List all configured test schedules (cron jobs) for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/scheduling/${pid}/schedules`);
      },
    }),

    triggerScheduleNow: tool({
      description: 'Trigger a scheduled test to run immediately.',
      inputSchema: z.object({
        scheduleId: z.number().describe('The schedule ID to trigger'),
      }),
    }),

    // ===== API & Database Testing Tools =====

    getApiTestRuns: tool({
      description: 'Get API test execution history. Supports pagination via limit/offset.',
      inputSchema: z.object({
        limit: z.number().optional().default(50).describe('Number of runs to fetch (default 50)'),
        offset: z.number().optional().default(0).describe('Pagination offset'),
      }),
      execute: async ({ limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 50));
        if (offset) params.set('offset', String(offset));
        return fetchTool(`/api-testing/runs?${params}`);
      },
    }),

    getDatabaseTestSummary: tool({
      description: 'Get database testing summary for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/database-testing/summary?${params}`);
      },
    }),

    // ===== Regression Analysis Tools =====

    compareBatches: tool({
      description: 'Compare two or more regression batches side by side — pass/fail diff, new failures, fixed tests.',
      inputSchema: z.object({
        batchIds: z.array(z.string()).min(2).describe('Array of batch IDs to compare'),
      }),
      execute: async ({ batchIds }): Promise<ToolResult> => {
        return fetchTool('/regression/batches/compare', 'POST', { batch_ids: batchIds });
      },
    }),

    getBatchTrend: tool({
      description: 'Get regression batch pass/fail trend over time for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/regression/batches/trend?${params}`);
      },
    }),

    getBatchErrorSummary: tool({
      description: 'Get aggregated error summary for a regression batch — groups failures by error type and suggests fixes.',
      inputSchema: z.object({
        batchId: z.string().describe('The regression batch ID'),
      }),
      execute: async ({ batchId }): Promise<ToolResult> => {
        return fetchTool(`/regression/batches/${batchId}/error-summary`);
      },
    }),

    rerunFailedTests: tool({
      description: 'Re-run only the failed tests from a regression batch.',
      inputSchema: z.object({
        batchId: z.string().describe('The regression batch ID'),
      }),
    }),

    getRegressionFlakyTests: tool({
      description: 'Get flaky tests specific to regression batches — tests that flip between pass and fail across batches.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/regression/flaky-tests?${params}`);
      },
    }),

    // ===== Load Testing Analysis Tools =====

    compareLoadTestRuns: tool({
      description: 'Compare two load test runs side by side — response times, throughput, error rates, percentiles.',
      inputSchema: z.object({
        runIds: z.array(z.string()).min(2).describe('Array of load test run IDs to compare'),
      }),
      execute: async ({ runIds }): Promise<ToolResult> => {
        const params = new URLSearchParams();
        params.set('run_ids', runIds.join(','));
        return fetchTool(`/load-testing/runs/compare?${params}`);
      },
    }),

    getLoadTestDashboard: tool({
      description: 'Get load testing dashboard overview — recent runs, average response times, peak throughput, system health.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/dashboard?${params}`);
      },
    }),

    getLoadTestTrends: tool({
      description: 'Get load testing performance trends over time — response time and throughput trend lines.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/runs/trends?${params}`);
      },
    }),

    analyzeLoadTestRun: tool({
      description: 'Run AI-powered analysis on a load test run — identifies bottlenecks, anomalies, and recommendations.',
      inputSchema: z.object({
        runId: z.string().describe('The load test run ID to analyze'),
      }),
    }),

    getLoadTestSystemLimits: tool({
      description: 'Get current load testing system limits — max VUs, max duration, worker status, and resource caps.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        return fetchTool('/load-testing/system-limits');
      },
    }),

    // ===== Security Testing Analysis Tools =====

    analyzeSecurityRun: tool({
      description: 'Run AI-powered analysis on a security scan — prioritized findings, remediation steps, risk assessment.',
      inputSchema: z.object({
        runId: z.string().describe('The security scan run ID to analyze'),
      }),
    }),

    triageSecurityFinding: tool({
      description: 'Update the status of a security finding (e.g., mark as false positive, fixed, or accepted risk).',
      inputSchema: z.object({
        findingId: z.string().describe('The security finding ID'),
        status: z.enum(['open', 'false_positive', 'fixed', 'accepted_risk']).describe('New status for the finding'),
        notes: z.string().optional().describe('Optional notes explaining the triage decision'),
      }),
    }),

    compareSecurityScans: tool({
      description: 'Compare two security scan runs — new findings, resolved findings, severity changes.',
      inputSchema: z.object({
        runIds: z.array(z.string()).min(2).describe('Array of security scan run IDs to compare'),
      }),
      execute: async ({ runIds }): Promise<ToolResult> => {
        const params = new URLSearchParams();
        params.set('run_ids', runIds.join(','));
        return fetchTool(`/security-testing/runs/compare?${params}`);
      },
    }),

    // ===== RTM Analysis Tools =====

    getRTMGaps: tool({
      description: 'Get RTM coverage gaps — requirements without test coverage and suggested test names.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/gaps?${params}`);
      },
    }),

    exportRTM: tool({
      description: 'Export the requirements traceability matrix in a specified format.',
      inputSchema: z.object({
        format: z.enum(['csv', 'json', 'html']).describe('Export format'),
      }),
      execute: async ({ format }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/export/${format}?${params}`);
      },
    }),

    getRTMTrend: tool({
      description: 'Get RTM coverage trend over time — how test coverage of requirements has changed.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/trend?${params}`);
      },
    }),

    // ===== LLM Testing Extended Tools =====

    getLlmComparisonMatrix: tool({
      description: 'Get a comparison matrix for an LLM comparison run — scores, latencies, costs across providers.',
      inputSchema: z.object({
        comparisonId: z.string().describe('The LLM comparison run ID'),
      }),
      execute: async ({ comparisonId }): Promise<ToolResult> => {
        return fetchTool(`/llm-testing/comparisons/${comparisonId}/matrix`);
      },
    }),

    getLlmGoldenDashboard: tool({
      description: 'Get the LLM golden dataset dashboard — benchmark results against golden test cases.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/llm-testing/analytics/golden-dashboard?${params}`);
      },
    }),

    getLlmCostTracking: tool({
      description: 'Get LLM cost tracking breakdown by provider and model over a time period.',
      inputSchema: z.object({
        period: z.enum(['7d', '30d', '90d']).optional().default('30d').describe('Time period for cost tracking'),
      }),
      execute: async ({ period }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('period', period ?? '30d');
        return fetchTool(`/llm-testing/analytics/cost-tracking?${params}`);
      },
    }),

    suggestLlmSpecImprovements: tool({
      description: 'Get AI-powered suggestions for improving an LLM test spec — better test cases, edge cases, prompt improvements.',
      inputSchema: z.object({
        specName: z.string().describe('The LLM test spec name'),
      }),
    }),

    // ===== Database Testing Extended Tools =====

    getDbSchemaAnalysis: tool({
      description: 'Get database schema analysis results from a test run — tables, relationships, constraints, issues.',
      inputSchema: z.object({
        runId: z.string().describe('The database test run ID'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/database-testing/runs/${runId}/schema`);
      },
    }),

    getDbChecks: tool({
      description: 'Get data quality check results from a database test run, optionally filtered by status.',
      inputSchema: z.object({
        runId: z.string().describe('The database test run ID'),
        status: z.enum(['passed', 'failed', 'error']).optional().describe('Filter checks by status'),
      }),
      execute: async ({ runId, status }): Promise<ToolResult> => {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        return fetchTool(`/database-testing/runs/${runId}/checks?${params}`);
      },
    }),

    suggestDbFixes: tool({
      description: 'Get AI-powered fix suggestions for failed database quality checks.',
      inputSchema: z.object({
        runId: z.string().describe('The database test run ID with failures'),
      }),
    }),

    // ===== Auto Pilot Tools =====

    startAutoPilot: tool({
      description: 'Start an Auto Pilot session that autonomously explores a web app, generates requirements, creates test specs, generates and validates Playwright tests, and produces coverage reports. This is a long-running pipeline (10-60 min). Use for broad "test everything" requests.',
      inputSchema: z.object({
        urls: z.array(z.string()).min(1).describe('Entry URLs to explore'),
        instructions: z.string().optional().describe('Optional instructions to guide the pipeline (e.g., focus areas, login credentials)'),
        maxInteractions: z.number().optional().default(50).describe('Max browser interactions during exploration (1-200)'),
      }),
    }),

    getAutoPilotStatus: tool({
      description: 'Get the current status of an Auto Pilot session including phase progress, stats, and any pending checkpoint questions that need user input.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID'),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        const [session, phases, questions] = await Promise.all([
          fetchTool(`/autopilot/${sessionId}`),
          fetchTool(`/autopilot/${sessionId}/phases`),
          fetchTool(`/autopilot/${sessionId}/questions?status=pending`),
        ]);
        return { session, phases, pendingQuestions: questions } as ToolResult;
      },
    }),

    answerAutoPilotQuestion: tool({
      description: 'Answer a checkpoint question from the Auto Pilot pipeline. The pipeline pauses at key decision points and waits for user input before continuing.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID'),
        questionId: z.number().describe('The question ID to answer'),
        answer: z.string().describe('The answer text'),
      }),
    }),

    cancelAutoPilot: tool({
      description: 'Cancel a running Auto Pilot session.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID to cancel'),
      }),
    }),

    listAutoPilotSessions: tool({
      description: 'List all Auto Pilot sessions for the current project with their status and progress summary.',
      inputSchema: z.object({
        status: z.enum(['running', 'completed', 'failed', 'cancelled', 'paused']).optional().describe('Filter by session status'),
      }),
      execute: async ({ status }): Promise<ToolResult> => {
        const params = projectParams();
        if (status) params.set('status', status);
        return fetchTool(`/autopilot/sessions?${params}`);
      },
    }),

    // ===== Composite Workflow Tools =====

    analyzeFailures: tool({
      description: 'Comprehensive failure analysis — fetches recent runs, failure classifications, and flaky tests in parallel. Optionally analyzes a specific batch.',
      inputSchema: z.object({
        batchId: z.string().optional().describe('Optional batch ID to focus analysis on'),
      }),
      execute: async ({ batchId }): Promise<ToolResult> => {
        const params = projectParams();
        const calls: Promise<ToolResult>[] = [
          fetchTool(`/runs?${params}&limit=10`),
          fetchTool(`/analytics/failure-classification?${params}`),
          fetchTool(`/analytics/flake-detection?${params}`),
        ];
        if (batchId) {
          calls.push(fetchTool(`/regression/batches/${batchId}/error-summary`));
        }
        const [recentRuns, failureClasses, flakyTests, batchErrors] = await Promise.all(calls);
        return {
          recentRuns,
          failureClassification: failureClasses,
          flakyTests,
          ...(batchErrors ? { batchErrorSummary: batchErrors } : {}),
        } as ToolResult;
      },
    }),

    fullHealthCheck: tool({
      description: 'Full system health check — dashboard stats, pass rate trends, browser pool status, flaky tests, RTM coverage, and load test system limits in one call.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        const [dashboard, trends, browserPool, flaky, rtmCoverage, systemLimits] = await Promise.all([
          fetchTool('/dashboard'),
          fetchTool(`/analytics/pass-rate-trends?${params}&period=7d`),
          fetchTool('/api/browser-pool/status'),
          fetchTool(`/analytics/flake-detection?${params}`),
          fetchTool(`/rtm/coverage?${params}`),
          fetchTool('/load-testing/system-limits'),
        ]);
        return { dashboard, passTrends: trends, browserPool, flakyTests: flaky, rtmCoverage, loadTestLimits: systemLimits } as ToolResult;
      },
    }),

    securityAudit: tool({
      description: 'Security posture review — findings summary, recent scans, and comparison of the latest two scans.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        const [summary, runs] = await Promise.all([
          fetchTool(`/security-testing/findings/summary?${params}`),
          fetchTool(`/security-testing/runs?${params}`),
        ]);
        // Compare latest 2 scans if available
        let comparison: ToolResult = null;
        const runList = runs && (runs as any).runs;
        if (Array.isArray(runList) && runList.length >= 2) {
          const ids = runList.slice(0, 2).map((r: any) => r.id || r.run_id);
          const compareParams = new URLSearchParams();
          compareParams.set('run_ids', ids.join(','));
          comparison = await fetchTool(`/security-testing/runs/compare?${compareParams}`);
        }
        return { findingsSummary: summary, recentScans: runs, scanComparison: comparison } as ToolResult;
      },
    }),
  };
}
