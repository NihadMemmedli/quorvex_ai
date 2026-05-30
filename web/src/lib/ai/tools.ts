import { tool } from 'ai';
import { z } from 'zod';
import { backendFetch } from './backend-client';
import { ASSISTANT_WORKFLOW_CAPABILITIES } from './workflow-capabilities';

type ToolResult = Record<string, unknown> | null;

const RUNNER_SUBSET_SUITES = [
  'auto',
  'python-unit',
  'python-integration',
  'frontend-typecheck',
  'frontend-lint',
  'playwright-generated',
  'playwright-e2e',
  'all-safe',
] as const;

const RUNNER_SUBSET_BROWSERS = ['chromium', 'firefox', 'webkit'] as const;
const RUNNER_SUBSET_MARKERS = ['not integration', 'integration'] as const;
const CI_TEST_SUBSET_MODES = ['manual', 'pr-impact', 'both'] as const;
const CI_TEST_SUBSET_ITEM_SCHEMA = z.object({
  specName: z.string().describe('Quorvex spec name, e.g. folder/login.md'),
  targetPath: z.string().optional().describe('Optional repo-relative Playwright test path under tests/generated or tests/e2e'),
});

const CHAT_CONTROL_DOMAINS = [
  { domain: 'Core UI testing', status: 'supported', tools: ['listTestSpecs', 'createTestSpec', 'runTestSpec', 'getRunLogs', 'healFailedRun', 'runRegressionBatch'] },
  { domain: 'Coverage planning', status: 'supported', tools: ['planUiTestCoverage', 'getRTMSummary', 'getRTMGaps', 'getCoverageGaps', 'getTestSuggestions'] },
  { domain: 'Custom workflows', status: 'supported', tools: ['listWorkflows', 'listWorkflowCatalog', 'getWorkflow', 'createWorkflow', 'updateWorkflow', 'duplicateWorkflow', 'archiveWorkflow', 'startWorkflow', 'startWorkflowFromStep', 'getWorkflowStatus', 'retryWorkflowFailedStep', 'pauseWorkflowRun', 'resumeWorkflowRun', 'cancelWorkflowRun'], notes: ['Workflow catalog includes agent report materialization into requirements/specs'] },
  { domain: 'Explorer Agent', status: 'supported', tools: ['startExplorerAgent', 'getAgentRun', 'getExplorerGeneratedSpecs', 'generateExplorerFlowTest'] },
  { domain: 'Discovery exploration', status: 'supported', tools: ['startDiscoveryExploration', 'getExplorationDetails', 'getExplorationFlows', 'generateApiTestsFromExploration'] },
  { domain: 'Specs and artifacts', status: 'supported', tools: ['getSpecContent', 'getSpecGeneratedCode', 'moveSpec', 'renameSpec', 'splitSpec'] },
  { domain: 'Regression operations', status: 'supported', tools: ['getRegressionBatchDetail', 'cancelRegressionBatch', 'getSpecHistory', 'exportRegressionBatch'] },
  { domain: 'Integrations follow-through', status: 'partial', tools: ['generateJiraBugReport', 'createJiraIssue', 'pushTestRailCases', 'syncTestRailResults', 'createCiTestSubset', 'openCiTestSubsetPullRequest'], missing: ['Jira/TestRail/GitHub credential setup remains dashboard-led by default'] },
  { domain: 'Admin and users', status: 'partial', tools: ['listProjectMembers', 'listProjects'], missing: ['User invite, disable, and role management are intentionally not chat-mutatable in this pass'] },
];

// ===== Mutating tool execution configs (used by proxy route for HitL approval) =====

export const MUTATING_TOOL_CONFIGS: Record<string, { label: string }> = {
  runTestSpec: { label: 'Run Test Spec' },
  startDiscoveryExploration: { label: 'Start Discovery Exploration' },
  startExploration: { label: 'Start Exploration' },
  startExplorerAgent: { label: 'Start Explorer Agent' },
  startAdhocCustomAgent: { label: 'Start Custom Agent' },
  createCustomAgentDefinition: { label: 'Save Custom Agent' },
  startCustomAgentFromReport: { label: 'Start Custom Agent From Report' },
  synthesizeExplorerSpecs: { label: 'Synthesize Explorer Specs' },
  analyzeExplorerPrerequisites: { label: 'Analyze Explorer Prerequisites' },
  generateExplorerFlowSpec: { label: 'Generate Explorer Flow Spec' },
  generateExplorerFlowTest: { label: 'Generate Explorer Flow Test' },
  updateExplorerFlow: { label: 'Update Explorer Flow' },
  deleteExplorerFlow: { label: 'Delete Explorer Flow' },
  saveExplorerSession: { label: 'Save Explorer Session' },
  deleteExplorerSession: { label: 'Delete Explorer Session' },
  stopExploration: { label: 'Stop Exploration' },
  generateApiSpecsFromExploration: { label: 'Generate API Specs From Exploration' },
  generateApiTestsFromExploration: { label: 'Generate API Tests From Exploration' },
  generateRequirements: { label: 'Generate Requirements' },
  createRequirement: { label: 'Create Requirement' },
  bulkCreateRequirements: { label: 'Bulk Create Requirements' },
  updateRequirement: { label: 'Update Requirement' },
  deleteRequirement: { label: 'Delete Requirement' },
  generateSpecFromRequirement: { label: 'Generate Spec From Requirement' },
  bulkGenerateRequirementSpecs: { label: 'Bulk Generate Requirement Specs' },
  mergeRequirements: { label: 'Merge Requirements' },
  generateRTM: { label: 'Generate RTM' },
  createRTMSnapshot: { label: 'Create RTM Snapshot' },
  createRTMEntry: { label: 'Create RTM Entry' },
  deleteRTMEntry: { label: 'Delete RTM Entry' },
  createTestSpec: { label: 'Create Test Spec' },
  createTestSpecFromAgentReport: { label: 'Create Test Spec From Agent Report' },
  updateTestSpec: { label: 'Update Test Spec' },
  updateGeneratedCode: { label: 'Update Generated Code' },
  updateSpecMetadata: { label: 'Update Spec Metadata' },
  moveSpec: { label: 'Move Spec' },
  renameSpec: { label: 'Rename Spec' },
  splitSpec: { label: 'Split Spec' },
  createSpecFolder: { label: 'Create Spec Folder' },
  runRegressionBatch: { label: 'Run Regression Batch' },
  executeUiTestCoveragePlan: { label: 'Execute UI Test Coverage Plan' },
  stopRun: { label: 'Stop Test Run' },
  stopAllJobs: { label: 'Stop All Jobs' },
  clearQueue: { label: 'Clear Queue' },
  triggerSecurityScan: { label: 'Trigger Security Scan' },
  runSecurityScan: { label: 'Run Security Scan' },
  stopSecurityScan: { label: 'Stop Security Scan' },
  createSecuritySpec: { label: 'Create Security Spec' },
  updateSecuritySpec: { label: 'Update Security Spec' },
  deleteSecuritySpec: { label: 'Delete Security Spec' },
  generateSecuritySpecFromExploration: { label: 'Generate Security Spec From Exploration' },
  quarantineSpec: { label: 'Quarantine Spec' },
  unquarantineSpec: { label: 'Unquarantine Spec' },
  retryFailedRun: { label: 'Retry Failed Run' },
  healFailedRun: { label: 'Heal Failed Run' },
  triggerScheduleNow: { label: 'Trigger Schedule Now' },
  rerunFailedTests: { label: 'Rerun Failed Tests' },
  refreshRegressionBatch: { label: 'Refresh Regression Batch' },
  cancelRegressionBatch: { label: 'Cancel Regression Batch' },
  renameRegressionBatch: { label: 'Rename Regression Batch' },
  deleteRegressionBatch: { label: 'Delete Regression Batch' },
  analyzeLoadTestRun: { label: 'Analyze Load Test Run' },
  stopLoadTestRun: { label: 'Stop Load Test Run' },
  forceUnlockLoadTesting: { label: 'Force Unlock Load Testing' },
  createLoadSpec: { label: 'Create Load Spec' },
  updateLoadSpec: { label: 'Update Load Spec' },
  deleteLoadSpec: { label: 'Delete Load Spec' },
  generateLoadScript: { label: 'Generate Load Script' },
  runLoadTest: { label: 'Run Load Test' },
  runLoadTestFromSpec: { label: 'Run Load Test From Spec' },
  analyzeSecurityRun: { label: 'Analyze Security Run' },
  triageSecurityFinding: { label: 'Triage Security Finding' },
  suggestLlmSpecImprovements: { label: 'Suggest LLM Spec Improvements' },
  suggestDbFixes: { label: 'Suggest DB Fixes' },
  generateDatabaseSpec: { label: 'Generate Database Spec' },
  saveGeneratedDatabaseSpec: { label: 'Save Generated Database Spec' },
  createApiSpec: { label: 'Create API Spec' },
  updateApiSpec: { label: 'Update API Spec' },
  deleteApiSpec: { label: 'Delete API Spec' },
  createAndGenerateApiTest: { label: 'Create and Generate API Test' },
  importOpenApiSpec: { label: 'Import OpenAPI Spec' },
  generateApiTest: { label: 'Generate API Test' },
  runApiTest: { label: 'Run API Test' },
  runApiTestDirect: { label: 'Run Generated API Test' },
  generateApiEdgeCases: { label: 'Generate API Edge Cases' },
  startAutoPilot: { label: 'Start Auto Pilot' },
  pauseAutoPilot: { label: 'Pause Auto Pilot' },
  resumeAutoPilot: { label: 'Resume Auto Pilot' },
  answerAutoPilotQuestion: { label: 'Answer Auto Pilot Question' },
  stopAutoPilotTestTask: { label: 'Stop Auto Pilot Test Task' },
  cancelAutoPilot: { label: 'Cancel Auto Pilot' },
  createWorkflow: { label: 'Create Custom Workflow' },
  updateWorkflow: { label: 'Update Custom Workflow' },
  duplicateWorkflow: { label: 'Duplicate Custom Workflow' },
  archiveWorkflow: { label: 'Archive Custom Workflow' },
  startWorkflow: { label: 'Start Custom Workflow' },
  startWorkflowFromStep: { label: 'Start Custom Workflow From Step' },
  retryWorkflowFailedStep: { label: 'Retry Custom Workflow Failed Step' },
  pauseWorkflowRun: { label: 'Pause Custom Workflow Run' },
  resumeWorkflowRun: { label: 'Resume Custom Workflow Run' },
  cancelWorkflowRun: { label: 'Cancel Custom Workflow Run' },
  createProject: { label: 'Create Project' },
  updateProject: { label: 'Update Project' },
  deleteProject: { label: 'Delete Project' },
  assignSpecToProject: { label: 'Assign Spec to Project' },
  bulkAssignSpecsToProject: { label: 'Bulk Assign Specs to Project' },
  setProjectCredential: { label: 'Set Project Credential' },
  removeProjectCredential: { label: 'Remove Project Credential' },
  startRecording: { label: 'Start Recording' },
  stopRecording: { label: 'Stop Recording' },
  importRecording: { label: 'Import Recording' },
  createSchedule: { label: 'Create Schedule' },
  updateSchedule: { label: 'Update Schedule' },
  deleteSchedule: { label: 'Delete Schedule' },
  toggleSchedule: { label: 'Toggle Schedule' },
  updateAssistantSettings: { label: 'Update Assistant Settings' },
  generatePrdPlan: { label: 'Generate PRD Test Plan' },
  stopPrdGeneration: { label: 'Stop PRD Generation' },
  generatePrdTest: { label: 'Generate PRD Test' },
  healPrdTest: { label: 'Heal PRD Test' },
  runPrdTest: { label: 'Run PRD Test' },
  syncCiRuns: { label: 'Sync CI Runs' },
  dispatchCiWorkflow: { label: 'Dispatch CI Workflow' },
  cancelCiRun: { label: 'Cancel CI Run' },
  rerunCiRun: { label: 'Rerun CI Run' },
  generateCiWorkflowChange: { label: 'Generate CI Workflow Change' },
  openCiWorkflowPullRequest: { label: 'Open CI Workflow Pull Request' },
  updateCiProviderDefaults: { label: 'Update CI Provider Defaults' },
  createCiTestSubset: { label: 'Create CI Test Subset' },
  updateCiTestSubset: { label: 'Update CI Test Subset' },
  deleteCiTestSubset: { label: 'Delete CI Test Subset' },
  openCiTestSubsetPullRequest: { label: 'Open CI Test Subset Pull Request' },
  dispatchCiTestSubset: { label: 'Dispatch CI Test Subset' },
  analyzePullRequestTests: { label: 'Analyze Pull Request Tests' },
  runPrAdvisorRecommendedTests: { label: 'Run PR Advisor Recommended Tests' },
  startPrQualityGate: { label: 'Start PR Quality Gate' },
  generateJiraBugReport: { label: 'Generate Jira Bug Report' },
  createJiraIssue: { label: 'Create Jira Issue' },
  pushTestRailCases: { label: 'Push TestRail Cases' },
  syncTestRailResults: { label: 'Sync TestRail Results' },
  deleteTestRailMapping: { label: 'Delete TestRail Mapping' },
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

  async function fetchTool(path: string, method = 'GET', body?: unknown): Promise<ToolResult> {
    const res = await backendFetch(path, { ...opts, method, body });
    if (!res.ok) return { error: res.error } as ToolResult;
    return res.data as ToolResult;
  }

  return {
    // ===== Read-only tools =====

    getWorkflowCapabilities: tool({
      description: 'Show which dashboard workflows the chatbot can inspect, start, monitor, stop, analyze, or improve. Use this when the user asks what can be controlled from chat.',
      inputSchema: z.object({
        section: z.string().optional().describe('Optional dashboard section filter, e.g. "CI/CD", "Projects", "Schedules"'),
      }),
      execute: async ({ section }): Promise<ToolResult> => {
        const capabilities = section
          ? ASSISTANT_WORKFLOW_CAPABILITIES.filter((capability) =>
              capability.section.toLowerCase().includes(section.toLowerCase())
              || capability.page.toLowerCase().includes(section.toLowerCase())
            )
          : ASSISTANT_WORKFLOW_CAPABILITIES;
        return { capabilities, count: capabilities.length } as ToolResult;
      },
    }),

    getChatControlAudit: tool({
      description: 'Audit chatbot control coverage by domain, including supported, partial, and intentionally omitted areas. Use this when users ask what is missing or how chat control can improve.',
      inputSchema: z.object({
        includeRecommendations: z.boolean().optional().default(true),
      }),
      execute: async ({ includeRecommendations }): Promise<ToolResult> => {
        const partial = CHAT_CONTROL_DOMAINS.filter((domain) => domain.status !== 'supported');
        return {
          summary: {
            domains: CHAT_CONTROL_DOMAINS.length,
            supported: CHAT_CONTROL_DOMAINS.filter((domain) => domain.status === 'supported').length,
            partial: partial.length,
            declared_workflows: ASSISTANT_WORKFLOW_CAPABILITIES.length,
          },
          domains: CHAT_CONTROL_DOMAINS,
          gaps: partial,
          recommended_actions: includeRecommendations ? [
            'Use planUiTestCoverage before creating or running new tests.',
            'Use analyzeUiTestRunArtifacts after failures before healing or filing bugs.',
            'Use Explorer Agent flow tools to turn discovered flows into runnable specs.',
            'Use Jira/TestRail tools only after project integrations are configured.',
          ] : [],
        } as ToolResult;
      },
    }),

    planUiTestCoverage: tool({
      description: 'Build a chat-native UI test coverage plan from specs, requirements, RTM gaps, memory coverage gaps, test suggestions, recent runs, and flaky tests.',
      inputSchema: z.object({
        focus: z.string().optional().describe('Optional product area, page, requirement, or risk to focus on'),
        limit: z.number().optional().default(20),
      }),
      execute: async ({ focus, limit }): Promise<ToolResult> => {
        const params = projectParams();
        const suggestionParams = new URLSearchParams(params);
        suggestionParams.set('max_suggestions', String(limit ?? 20));
        if (focus) suggestionParams.set('feature', focus);
        const coverageGapParams = new URLSearchParams(params);
        coverageGapParams.set('max_results', String(limit ?? 20));
        if (focus) coverageGapParams.set('url', focus);
        const recentRunParams = new URLSearchParams(params);
        recentRunParams.set('limit', '10');
        const [specs, requirements, rtmCoverage, rtmGaps, memoryGaps, suggestions, recentRuns, flaky] = await Promise.all([
          fetchTool(`/specs?${params}`),
          fetchTool(`/requirements?${params}`),
          fetchTool(`/rtm/coverage?${params}`),
          fetchTool(`/rtm/gaps?${params}`),
          fetchTool(`/api/memory/coverage/gaps?${coverageGapParams}`),
          fetchTool(`/api/memory/coverage/suggestions?${suggestionParams}`),
          fetchTool(`/runs?${recentRunParams}`),
          fetchTool(`/analytics/flake-detection?${params}`),
        ]);
        return {
          focus: focus || null,
          inputs: { specs, requirements, rtmCoverage, rtmGaps, memoryGaps, suggestions, recentRuns, flaky },
          recommended_next_steps: [
            'Create or update specs for uncovered high-priority requirements.',
            'Run a targeted regression batch for affected specs.',
            'Analyze failed artifacts before healing or filing external bugs.',
          ],
        } as ToolResult;
      },
    }),

    analyzeUiTestRunArtifacts: tool({
      description: 'Analyze a UI test run with logs, validation data, generated code, artifacts, failure classification, Jira issue status, and fix suggestions.',
      inputSchema: z.object({
        runId: z.string().describe('Run ID to analyze'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        const params = projectParams();
        const run = await fetchTool(`/runs/${encodeURIComponent(runId)}?${params}`);
        const specName = run && typeof run === 'object' ? String((run as Record<string, unknown>).spec_name || '') : '';
        const [validation, failureClassification, jiraIssue, generatedCode] = await Promise.all([
          fetchTool(`/runs/${encodeURIComponent(runId)}/validation`).catch((error) => ({ error: String(error) }) as ToolResult),
          fetchTool(`/analytics/failure-classification?${params}`),
          fetchTool(`/jira/${encodeURIComponent(projectId || 'default')}/issues/${encodeURIComponent(runId)}`).catch(() => null),
          specName ? fetchTool(`/specs/${encodeURIComponent(specName)}/generated-code?${params}`).catch(() => null) : Promise.resolve(null),
        ]);
        return {
          run,
          validation,
          failureClassification,
          jiraIssue,
          generatedCode,
          recommended_next_steps: [
            'If the failure is selector or timing related, inspect generated code and run healing.',
            'If the failure is product behavior, generate a Jira bug report before rerunning.',
            'If the spec is flaky, quarantine it or run a focused regression comparison.',
          ],
        } as ToolResult;
      },
    }),

    getDashboardStats: tool({
      description: 'Get dashboard overview statistics: total specs, recent runs, pass rates, and trends.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        return fetchTool('/dashboard');
      },
    }),

    // ===== Project Workspace Tools =====

    listProjects: tool({
      description: 'List projects and their spec/run/batch counts.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/projects'),
    }),

    getProject: tool({
      description: 'Get project details including spec/run/batch counts.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
      }),
      execute: async ({ projectId: requestedProjectId }): Promise<ToolResult> => {
        return fetchTool(`/projects/${encodeURIComponent(requestedProjectId || projectId || 'default')}`);
      },
    }),

    listProjectMembers: tool({
      description: 'List members for the current or specified project.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
      }),
      execute: async ({ projectId: requestedProjectId }): Promise<ToolResult> => {
        return fetchTool(`/projects/${encodeURIComponent(requestedProjectId || projectId || 'default')}/members`);
      },
    }),

    listProjectCredentials: tool({
      description: 'List masked project credentials for the current or specified project.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
        includeEnv: z.boolean().optional().default(true).describe('Include masked .env-backed credentials'),
      }),
      execute: async ({ projectId: requestedProjectId, includeEnv }): Promise<ToolResult> => {
        const pid = requestedProjectId || projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/credentials?include_env=${includeEnv ?? true}`);
      },
    }),

    createProject: tool({
      description: 'Create a new project. Requires approval.',
      inputSchema: z.object({
        name: z.string().describe('Project name'),
        baseUrl: z.string().optional().describe('Optional base URL for the project'),
        description: z.string().optional().describe('Optional project description'),
      }),
    }),

    updateProject: tool({
      description: 'Update a project name, base URL, or description. Requires approval.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
        name: z.string().optional(),
        baseUrl: z.string().optional(),
        description: z.string().optional(),
      }),
    }),

    deleteProject: tool({
      description: 'Delete a project and reassign its content. Requires approval.',
      inputSchema: z.object({
        projectId: z.string().describe('Project ID to delete'),
        reassignTo: z.string().optional().describe('Project ID to reassign content to. Defaults to default project.'),
      }),
    }),

    assignSpecToProject: tool({
      description: 'Assign one spec to a project. Requires approval.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
        specName: z.string().describe('Spec name/path to assign'),
      }),
    }),

    bulkAssignSpecsToProject: tool({
      description: 'Assign multiple specs to a project. Requires approval.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
        specNames: z.array(z.string()).min(1).describe('Spec names/paths to assign'),
      }),
    }),

    setProjectCredential: tool({
      description: 'Add or update a project credential. Requires approval and redacts the value in chat history.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
        key: z.string().describe('Credential key, e.g. APP_USERNAME'),
        value: z.string().describe('Credential value'),
      }),
    }),

    removeProjectCredential: tool({
      description: 'Remove a project-specific credential. Requires approval.',
      inputSchema: z.object({
        projectId: z.string().optional().describe('Project ID. Defaults to the current project.'),
        key: z.string().describe('Credential key to remove'),
      }),
    }),

    // ===== Recording Tools =====

    listRecordings: tool({
      description: 'List Playwright recorder sessions for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/recordings?${params}`);
      },
    }),

    getRecording: tool({
      description: 'Get recording session status and artifact paths.',
      inputSchema: z.object({
        recordingId: z.string().describe('Recording session ID'),
      }),
      execute: async ({ recordingId }): Promise<ToolResult> => {
        return fetchTool(`/recordings/${encodeURIComponent(recordingId)}`);
      },
    }),

    getRecordingCode: tool({
      description: 'Get generated Playwright code for a recording session.',
      inputSchema: z.object({
        recordingId: z.string().describe('Recording session ID'),
      }),
      execute: async ({ recordingId }): Promise<ToolResult> => {
        const code = await fetchTool(`/recordings/${encodeURIComponent(recordingId)}/code`) as unknown;
        return typeof code === 'string' ? { code } : code as ToolResult;
      },
    }),

    startRecording: tool({
      description: 'Start a Playwright codegen recording session for a target URL. Requires approval.',
      inputSchema: z.object({
        targetUrl: z.string().url().describe('URL to record'),
        name: z.string().optional().describe('Optional recording name'),
        viewportSize: z.string().optional().describe('Viewport size like "1280,720"'),
        device: z.string().optional().describe('Optional Playwright device name'),
        loadStoragePath: z.string().optional().describe('Optional storage state path'),
        saveStorage: z.boolean().optional().default(false),
        saveHar: z.boolean().optional().default(false),
      }),
    }),

    stopRecording: tool({
      description: 'Stop an active recording session. Requires approval.',
      inputSchema: z.object({
        recordingId: z.string().describe('Recording session ID'),
      }),
    }),

    importRecording: tool({
      description: 'Import a completed or stopped recording into a spec and generated test file. Requires approval.',
      inputSchema: z.object({
        recordingId: z.string().describe('Recording session ID'),
        name: z.string().optional().describe('Optional spec title/name'),
      }),
    }),

    // ===== Settings Tools =====

    getAssistantSettings: tool({
      description: 'Get masked AI assistant runtime settings.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/settings'),
    }),

    testAssistantSettingsConnection: tool({
      description: 'Test the active AI assistant provider/model connection.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/settings/test-connection', 'POST'),
    }),

    testAssistantHermesConnection: tool({
      description: 'Test the configured Hermes gateway connection.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/settings/test-hermes', 'POST'),
    }),

    updateAssistantSettings: tool({
      description: 'Update AI assistant provider settings. Requires approval.',
      inputSchema: z.object({
        llmProvider: z.string().describe('Provider label, e.g. anthropic, openai, openrouter, zai, custom'),
        apiKey: z.string().optional().describe('New API key/token. Omit to keep current key.'),
        baseUrl: z.string().optional().describe('Optional provider base URL'),
        modelName: z.string().optional().describe('Model name to use'),
        lightModel: z.string().optional().describe('Optional light model tier'),
        standardModel: z.string().optional().describe('Optional standard model tier'),
        deepModel: z.string().optional().describe('Optional deep model tier'),
        toolDeepModel: z.string().optional().describe('Optional tool-deep model tier'),
        chatModel: z.string().optional().describe('Optional assistant chat model tier'),
        embeddingModel: z.string().optional().describe('Optional embedding model'),
        agentRuntime: z.enum(['claude_sdk', 'hermes']).optional().describe('Default runtime for autonomous missions and custom agents'),
        assistantRuntime: z.enum(['claude_sdk', 'openai', 'hermes']).optional().describe('Runtime used by dashboard assistant chat'),
        hermesEnabled: z.boolean().optional().describe('Whether Hermes backend support is enabled'),
        hermesApiUrl: z.string().optional().describe('Hermes gateway API URL'),
        hermesApiKey: z.string().optional().describe('Hermes gateway API key. Omit to keep current key.'),
        hermesModel: z.string().optional().describe('Hermes OpenAI-compatible model ID'),
        hermesSyncProvider: z.boolean().optional().describe('Whether to mirror the selected LLM provider into Hermes config'),
      }),
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
      inputSchema: z.object({
        search: z.string().optional().describe('Optional search text'),
        category: z.string().optional().describe('Optional category filter'),
        priority: z.string().optional().describe('Optional priority filter'),
        status: z.string().optional().describe('Optional status filter'),
      }),
      execute: async ({ search, category, priority, status }): Promise<ToolResult> => {
        const params = projectParams();
        if (search) params.set('search', search);
        if (category) params.set('category', category);
        if (priority) params.set('priority', priority);
        if (status) params.set('status', status);
        return fetchTool(`/requirements?${params}`);
      },
    }),

    getRequirementDetails: tool({
      description: 'Get one requirement by ID, including acceptance criteria and traceability fields.',
      inputSchema: z.object({
        requirementId: z.number().describe('Requirement ID'),
      }),
      execute: async ({ requirementId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/${requirementId}?${params}`);
      },
    }),

    getRequirementStats: tool({
      description: 'Get requirement counts by category, priority, status, and coverage.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/stats?${params}`);
      },
    }),

    getRequirementHealth: tool({
      description: 'Get requirement-system health and duplicate/coverage signals.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/health?${params}`);
      },
    }),

    listRequirementCategories: tool({
      description: 'List requirement categories currently used by the project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/categories/list?${params}`);
      },
    }),

    findDuplicateRequirements: tool({
      description: 'List requirement duplicate groups detected by the backend.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/duplicates?${params}`);
      },
    }),

    checkRequirementDuplicate: tool({
      description: 'Check whether a proposed requirement title/description duplicates existing requirements.',
      inputSchema: z.object({
        title: z.string(),
        description: z.string().optional(),
      }),
      execute: async ({ title, description }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/check-duplicate?${params}`, 'POST', { title, description });
      },
    }),

    getRequirementsGenerateJob: tool({
      description: 'Get status for a requirements generation job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/requirements/generate-jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    getBulkSpecGenerationJob: tool({
      description: 'Get status for a bulk requirement-to-spec generation job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/requirements/bulk-generate-jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    getRequirementSpecStatus: tool({
      description: 'Check whether a requirement already has generated specs or linked tests.',
      inputSchema: z.object({
        requirementId: z.number(),
      }),
      execute: async ({ requirementId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/requirements/${requirementId}/spec-status?${params}`);
      },
    }),

    createRequirement: tool({
      description: 'Create a requirement with acceptance criteria. Requires approval.',
      inputSchema: z.object({
        title: z.string(),
        description: z.string().optional(),
        category: z.string().optional().default('other'),
        priority: z.enum(['low', 'medium', 'high', 'critical']).optional().default('medium'),
        acceptanceCriteria: z.array(z.string()).optional().default([]),
      }),
    }),

    bulkCreateRequirements: tool({
      description: 'Create multiple requirements in one request. Requires approval.',
      inputSchema: z.object({
        items: z.array(z.object({
          title: z.string(),
          description: z.string().optional(),
          category: z.string().optional().default('other'),
          priority: z.enum(['low', 'medium', 'high', 'critical']).optional().default('medium'),
          acceptanceCriteria: z.array(z.string()).optional().default([]),
        })).min(1),
      }),
    }),

    updateRequirement: tool({
      description: 'Update a requirement title, description, category, priority, status, or acceptance criteria. Requires approval.',
      inputSchema: z.object({
        requirementId: z.number(),
        title: z.string().optional(),
        description: z.string().optional(),
        category: z.string().optional(),
        priority: z.enum(['low', 'medium', 'high', 'critical']).optional(),
        status: z.string().optional(),
        acceptanceCriteria: z.array(z.string()).optional(),
      }),
    }),

    deleteRequirement: tool({
      description: 'Delete a requirement. Requires approval.',
      inputSchema: z.object({
        requirementId: z.number(),
      }),
    }),

    generateSpecFromRequirement: tool({
      description: 'Generate a test spec for a single requirement. Requires approval.',
      inputSchema: z.object({
        requirementId: z.number(),
        targetUrl: z.string().url(),
        loginUrl: z.string().url().optional(),
        credentials: z.record(z.unknown()).optional(),
        forceRegenerate: z.boolean().optional().default(false),
      }),
    }),

    bulkGenerateRequirementSpecs: tool({
      description: 'Generate specs for uncovered requirements in the current project. Requires approval.',
      inputSchema: z.object({
        targetUrl: z.string().url(),
        loginUrl: z.string().url().optional(),
        credentials: z.record(z.unknown()).optional(),
      }),
    }),

    mergeRequirements: tool({
      description: 'Merge duplicate requirements into a canonical requirement. Requires approval.',
      inputSchema: z.object({
        canonicalId: z.number(),
        duplicateIds: z.array(z.number()).min(1),
        mergeAcceptanceCriteria: z.boolean().optional().default(true),
      }),
    }),

    getRTMSummary: tool({
      description: 'Get requirements traceability matrix coverage summary: covered, partial, uncovered requirements.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/coverage?${params}`);
      },
    }),

    getRTMMatrix: tool({
      description: 'Get paginated requirements traceability matrix rows, with optional search and filters.',
      inputSchema: z.object({
        limit: z.number().optional().default(50),
        offset: z.number().optional().default(0),
        search: z.string().optional(),
        coverageStatus: z.enum(['covered', 'partial', 'uncovered']).optional(),
        category: z.string().optional(),
        priority: z.string().optional(),
      }),
      execute: async ({ limit, offset, search, coverageStatus, category, priority }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 50));
        params.set('offset', String(offset ?? 0));
        if (search) params.set('search', search);
        if (coverageStatus) params.set('coverage_status', coverageStatus);
        if (category) params.set('category', category);
        if (priority) params.set('priority', priority);
        return fetchTool(`/rtm?${params}`);
      },
    }),

    getRTMGenerateJob: tool({
      description: 'Get status for an RTM generation job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/rtm/generate-jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    listRTMSnapshots: tool({
      description: 'List saved RTM coverage snapshots.',
      inputSchema: z.object({
        limit: z.number().optional().default(20),
      }),
      execute: async ({ limit }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 20));
        return fetchTool(`/rtm/snapshots?${params}`);
      },
    }),

    getRTMSnapshotDetail: tool({
      description: 'Get one RTM snapshot by ID.',
      inputSchema: z.object({
        snapshotId: z.number(),
      }),
      execute: async ({ snapshotId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/snapshot/${snapshotId}?${params}`);
      },
    }),

    getRequirementTests: tool({
      description: 'List tests mapped to a requirement.',
      inputSchema: z.object({
        requirementId: z.number(),
      }),
      execute: async ({ requirementId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/requirement/${requirementId}/tests?${params}`);
      },
    }),

    getTestRequirements: tool({
      description: 'List requirements covered by a test spec.',
      inputSchema: z.object({
        testName: z.string(),
      }),
      execute: async ({ testName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/rtm/test/${encodeURIComponent(testName)}/requirements?${params}`);
      },
    }),

    generateRTM: tool({
      description: 'Generate or refresh the requirements traceability matrix. Requires approval.',
      inputSchema: z.object({
        specsPaths: z.array(z.string()).optional().describe('Optional spec paths to limit matching'),
        useAiMatching: z.boolean().optional().default(true),
      }),
    }),

    createRTMSnapshot: tool({
      description: 'Create a snapshot of current RTM coverage. Requires approval.',
      inputSchema: z.object({
        name: z.string().optional().describe('Optional snapshot name'),
      }),
    }),

    createRTMEntry: tool({
      description: 'Manually map a requirement to a test. Requires approval.',
      inputSchema: z.object({
        requirementId: z.number(),
        testSpecName: z.string(),
        testSpecPath: z.string().optional(),
        mappingType: z.enum(['full', 'partial']).optional().default('full'),
        confidence: z.number().optional().default(1),
        coverageNotes: z.string().optional(),
      }),
    }),

    deleteRTMEntry: tool({
      description: 'Delete a manual RTM mapping entry. Requires approval.',
      inputSchema: z.object({
        entryId: z.number(),
      }),
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

    getSecurityCapabilities: tool({
      description: 'Get available security scanner capabilities and configured engines.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/security-testing/capabilities'),
    }),

    getSecurityTargets: tool({
      description: 'List known security scan targets for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/security-testing/targets?${params}`);
      },
    }),

    listSecuritySpecs: tool({
      description: 'List security testing specs for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/security-testing/specs?${params}`);
      },
    }),

    getSecuritySpec: tool({
      description: 'Get markdown content for a security testing spec.',
      inputSchema: z.object({
        specName: z.string(),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/security-testing/specs/${encodeURIComponent(specName)}?${params}`);
      },
    }),

    getSecurityJobStatus: tool({
      description: 'Get status for a security testing background job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/security-testing/jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    listSecurityFindings: tool({
      description: 'List security findings across runs, optionally filtered by severity or status.',
      inputSchema: z.object({
        severity: z.string().optional(),
        status: z.string().optional(),
        limit: z.number().optional().default(50),
        offset: z.number().optional().default(0),
      }),
      execute: async ({ severity, status, limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 50));
        params.set('offset', String(offset ?? 0));
        if (severity) params.set('severity', severity);
        if (status) params.set('status', status);
        return fetchTool(`/security-testing/findings?${params}`);
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

    getSpecPerformance: tool({
      description: 'Get per-spec performance analytics including duration, pass rate, and flakiness signals.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/analytics/spec-performance?${params}`);
      },
    }),

    getCoverageOverview: tool({
      description: 'Get coverage overview across requirements, specs, and execution history.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/analytics/coverage-overview?${params}`);
      },
    }),

    quarantineSpec: tool({
      description: 'Quarantine a flaky or unsafe spec so it is excluded from normal runs. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
        reason: z.string().optional(),
      }),
    }),

    unquarantineSpec: tool({
      description: 'Remove a spec from quarantine. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
      }),
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

    listSpecFolders: tool({
      description: 'List spec folders with automated test counts.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/specs/folders?${params}`);
      },
    }),

    listAutomatedSpecs: tool({
      description: 'List specs that have generated automated Playwright tests, with optional tag/folder filters.',
      inputSchema: z.object({
        tags: z.string().optional().describe('Comma-separated tag filter'),
        folder: z.string().optional(),
        limit: z.number().optional().default(50),
        offset: z.number().optional().default(0),
      }),
      execute: async ({ tags, folder, limit, offset }): Promise<ToolResult> => {
        const params = projectParams();
        if (tags) params.set('tags', tags);
        if (folder) params.set('folder', folder);
        params.set('limit', String(limit ?? 50));
        params.set('offset', String(offset ?? 0));
        return fetchTool(`/specs/automated?${params}`);
      },
    }),

    getSpecMetadata: tool({
      description: 'Get metadata for one spec, including tags, description, author, and project assignment.',
      inputSchema: z.object({
        specName: z.string(),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/spec-metadata/${encodeURIComponent(specName)}?${params}`);
      },
    }),

    getSpecInfo: tool({
      description: 'Get parsed spec information, including type, test count, categories, and extracted test cases.',
      inputSchema: z.object({
        specName: z.string(),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        return fetchTool(`/specs/${encodeURIComponent(specName)}/info`);
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

    getExplorationHealth: tool({
      description: 'Get exploration subsystem health.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/exploration/health'),
    }),

    getExplorationQueueStatus: tool({
      description: 'Get queued/running exploration job status.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/exploration/queue/status'),
    }),

    getExplorationArtifacts: tool({
      description: 'List artifacts captured for an exploration session.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        return fetchTool(`/exploration/${encodeURIComponent(sessionId)}/artifacts`);
      },
    }),

    getExplorationResults: tool({
      description: 'Get structured exploration results for one session.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        return fetchTool(`/exploration/${encodeURIComponent(sessionId)}/results`);
      },
    }),

    getExplorationFlows: tool({
      description: 'Get discovered flows for one exploration session.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        return fetchTool(`/exploration/${encodeURIComponent(sessionId)}/flows`);
      },
    }),

    getExplorationApis: tool({
      description: 'Get API endpoints discovered during one exploration session.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        return fetchTool(`/exploration/${encodeURIComponent(sessionId)}/apis`);
      },
    }),

    getExplorationIssues: tool({
      description: 'Get issues discovered during one exploration session.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
      execute: async ({ sessionId }): Promise<ToolResult> => {
        return fetchTool(`/exploration/${encodeURIComponent(sessionId)}/issues`);
      },
    }),

    listAgentRuns: tool({
      description: 'List autonomous agent runs, including custom agents and Explorer Agent runs. Use this to find recent custom agent reports.',
      inputSchema: z.object({
        agentType: z.enum(['custom', 'exploratory', 'writer', 'spec-synthesis']).optional().describe('Optional agent type filter'),
        limit: z.number().optional().default(20).describe('Number of runs to fetch'),
      }),
      execute: async ({ agentType, limit }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 20));
        const data = await fetchTool(`/api/agents/runs?${params}`) as unknown;
        if (!Array.isArray(data)) return data as ToolResult;
        const runs = agentType ? data.filter((run: any) => run.agent_type === agentType) : data;
        return { runs, count: runs.length } as ToolResult;
      },
    }),

    getAgentRunReport: tool({
      description: 'Get the structured QA report for a custom agent run, including findings, pages checked, test ideas, evidence, and raw output.',
      inputSchema: z.object({
        runId: z.string().describe('The agent run ID'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api/agents/runs/${encodeURIComponent(runId)}/report?${params}`);
      },
    }),

    searchAgentReports: tool({
      description: 'Search custom agent structured reports for findings, test ideas, pages, evidence, or follow-up actions.',
      inputSchema: z.object({
        query: z.string().optional().describe('Text to search for'),
        severity: z.enum(['critical', 'high', 'medium', 'low', 'info']).optional().describe('Finding severity or test priority filter'),
        itemType: z.enum(['finding', 'test_idea', 'page', 'evidence', 'action']).optional().describe('Structured report item type'),
        limit: z.number().optional().default(30),
      }),
      execute: async ({ query, severity, itemType, limit }): Promise<ToolResult> => {
        const params = projectParams();
        if (query) params.set('query', query);
        if (severity) params.set('severity', severity);
        if (itemType) params.set('item_type', itemType);
        params.set('limit', String(limit ?? 30));
        return fetchTool(`/api/agents/reports/search?${params}`);
      },
    }),

    getAgentQueueStatus: tool({
      description: 'Get autonomous agent queue and slot status.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/api/agents/queue-status'),
    }),

    listAgentToolCatalog: tool({
      description: 'List tools available to custom and exploratory agents.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/api/agents/tools/catalog'),
    }),

    listAgentDefinitions: tool({
      description: 'List custom agent definitions for the current project.',
      inputSchema: z.object({
        includeArchived: z.boolean().optional().default(false),
      }),
      execute: async ({ includeArchived }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('include_archived', String(includeArchived ?? false));
        return fetchTool(`/api/agents/definitions?${params}`);
      },
    }),

    getAgentDefinition: tool({
      description: 'Get one custom agent definition.',
      inputSchema: z.object({
        definitionId: z.string(),
      }),
      execute: async ({ definitionId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api/agents/definitions/${encodeURIComponent(definitionId)}?${params}`);
      },
    }),

    getAgentRun: tool({
      description: 'Get raw status, progress, result, and artifacts for an agent run.',
      inputSchema: z.object({
        runId: z.string(),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api/agents/runs/${encodeURIComponent(runId)}?${params}`);
      },
    }),

    getExplorerGeneratedSpecs: tool({
      description: 'Get specs synthesized from an Explorer Agent run.',
      inputSchema: z.object({
        runId: z.string(),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api/agents/exploratory/${encodeURIComponent(runId)}/specs?${params}`);
      },
    }),

    getExplorerFlowDetails: tool({
      description: 'Get full details for a flow discovered by Explorer Agent.',
      inputSchema: z.object({
        runId: z.string(),
        flowId: z.string(),
      }),
      execute: async ({ runId, flowId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api/agents/exploratory/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowId)}?${params}`);
      },
    }),

    getExplorerFlowSpecJob: tool({
      description: 'Get status for an Explorer Agent flow spec/test generation job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/api/agents/exploratory/flow-spec-jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    listExplorerSessions: tool({
      description: 'List saved authentication sessions reusable by Explorer Agent.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/api/agents/sessions'),
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

    getRegressionBatchDetail: tool({
      description: 'Get detailed regression batch information including all runs.',
      inputSchema: z.object({
        batchId: z.string(),
      }),
      execute: async ({ batchId }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/regression/batches/${encodeURIComponent(batchId)}?${params}`);
      },
    }),

    getSpecHistory: tool({
      description: 'Get one spec history across regression batches.',
      inputSchema: z.object({
        specName: z.string(),
        limit: z.number().optional().default(10),
      }),
      execute: async ({ specName, limit }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('spec_name', specName);
        params.set('limit', String(limit ?? 10));
        return fetchTool(`/regression/spec-history?${params}`);
      },
    }),

    exportRegressionBatch: tool({
      description: 'Export a regression batch report in a supported format.',
      inputSchema: z.object({
        batchId: z.string(),
        format: z.enum(['json', 'csv', 'html']).optional().default('json'),
      }),
      execute: async ({ batchId, format }): Promise<ToolResult> => {
        return fetchTool(`/regression/batches/${encodeURIComponent(batchId)}/export?format=${format ?? 'json'}`);
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

    getSecurityRunFindings: tool({
      description: 'Get findings for one security scan run.',
      inputSchema: z.object({
        runId: z.string().describe('The security scan run ID'),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/security-testing/runs/${encodeURIComponent(runId)}/findings`);
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
        strategy: z.string().optional().default('goal_directed').describe('Exploration strategy'),
        maxDepth: z.number().optional().default(10).describe('Maximum navigation depth'),
        timeoutMinutes: z.number().optional().default(30).describe('Exploration timeout in minutes'),
        loginUrl: z.string().optional().describe('Optional login URL'),
        username: z.string().optional().describe('Optional login username'),
        password: z.string().optional().describe('Optional login password'),
        excludePatterns: z.array(z.string()).optional().describe('URL patterns to avoid'),
        focusAreas: z.array(z.string()).optional().describe('Specific features or areas to focus on'),
        instructions: z.string().optional().describe('Additional instructions for the exploration agent'),
      }),
    }),

    startDiscoveryExploration: tool({
      description: 'Start a Discovery "New Exploration" session for a web application URL. Use this for Discovery Sessions, New Exploration, or legacy exploration requests, not for the Explorer Agent tab.',
      inputSchema: z.object({
        url: z.string().describe('The URL to explore'),
        maxInteractions: z.number().optional().default(50).describe('Maximum interactions during exploration'),
        strategy: z.string().optional().default('goal_directed').describe('Exploration strategy'),
        maxDepth: z.number().optional().default(10).describe('Maximum navigation depth'),
        timeoutMinutes: z.number().optional().default(30).describe('Exploration timeout in minutes'),
        loginUrl: z.string().optional().describe('Optional login URL'),
        username: z.string().optional().describe('Optional login username'),
        password: z.string().optional().describe('Optional login password'),
        excludePatterns: z.array(z.string()).optional().describe('URL patterns to avoid'),
        focusAreas: z.array(z.string()).optional().describe('Specific features or areas to focus on'),
        instructions: z.string().optional().describe('Additional instructions for the discovery exploration'),
      }),
    }),

    startExplorerAgent: tool({
      description: 'Start the enhanced Discovery Explorer Agent tab run for deeper autonomous exploration, flow discovery, prerequisites analysis, and later spec generation. Use this when the user says Explorer Agent or asks to run the agent from Discovery.',
      inputSchema: z.object({
        url: z.string().describe('The URL to explore'),
        timeLimitMinutes: z.number().optional().default(15).describe('Explorer Agent time limit in minutes'),
        instructions: z.string().optional().describe('Additional instructions for the Explorer Agent'),
        loginUrl: z.string().optional().describe('Optional login URL for credential auth'),
        username: z.string().optional().describe('Optional login username'),
        password: z.string().optional().describe('Optional login password'),
        sessionId: z.string().optional().describe('Optional saved auth session ID'),
        authType: z.enum(['none', 'credentials', 'session']).optional().default('none').describe('Authentication mode'),
        testData: z.record(z.unknown()).optional().describe('Optional structured test data'),
        focusAreas: z.array(z.string()).optional().describe('Specific features or areas to focus on'),
        excludedPatterns: z.array(z.string()).optional().describe('URL patterns to avoid'),
      }),
    }),

    startAdhocCustomAgent: tool({
      description: 'Create an ad-hoc custom QA agent definition and start it on a target website to gather findings, evidence, and test ideas. Requires user approval.',
      inputSchema: z.object({
        url: z.string().describe('The website URL for the custom agent to inspect'),
        prompt: z.string().describe('The task prompt for the custom agent run'),
        focusAreas: z.array(z.string()).optional().describe('Specific features, pages, or behaviors to focus on'),
        runtime: z.enum(['claude_sdk', 'hermes']).optional().describe('Optional agent runtime. Use hermes when the user explicitly wants Hermes.'),
        timeoutSeconds: z.number().optional().default(1800).describe('Maximum custom agent runtime in seconds'),
      }),
    }),

    createCustomAgentDefinition: tool({
      description: 'Save a reusable custom QA agent definition from chatbot instructions without starting a run. Use when the user asks to create, define, save, or build a custom agent/template. Requires user approval.',
      inputSchema: z.object({
        url: z.string().describe('Default website URL or app area for the custom agent'),
        agentName: z.string().optional().describe('Agent display name'),
        description: z.string().optional().describe('Short description of the saved agent'),
        systemPrompt: z.string().describe('Reusable system prompt for the agent'),
        prompt: z.string().optional().describe('Default operating brief to append to the saved agent prompt'),
        toolIds: z.array(z.string()).optional().describe('Allowed custom-agent tool IDs'),
        focusAreas: z.array(z.string()).optional().describe('Specific features, pages, or behaviors to focus on'),
        runtime: z.enum(['claude_sdk', 'hermes']).optional().describe('Optional agent runtime. Use hermes when the user explicitly wants Hermes.'),
        timeoutSeconds: z.number().optional().default(1800).describe('Default custom agent runtime in seconds'),
      }),
    }),

    startCustomAgentFromReport: tool({
      description: 'Start a follow-up custom agent run from a structured agent report finding or test idea. Requires user approval.',
      inputSchema: z.object({
        definitionId: z.string().describe('Custom agent definition ID to run'),
        prompt: z.string().describe('Follow-up task prompt with the selected report context'),
        url: z.string().optional().describe('Optional target URL'),
        sourceRunId: z.string().optional().describe('Source custom agent run ID'),
        sourceItemId: z.string().optional().describe('Finding/test idea ID that triggered this follow-up'),
        runtime: z.enum(['claude_sdk', 'hermes']).optional().describe('Optional runtime override for this run'),
      }),
    }),

    synthesizeExplorerSpecs: tool({
      description: 'Synthesize markdown specs from a completed Explorer Agent run. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
      }),
    }),

    analyzeExplorerPrerequisites: tool({
      description: 'Analyze Explorer Agent flows for authentication, data, and dependency prerequisites. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
        forceReanalyze: z.boolean().optional().default(false),
      }),
    }),

    generateExplorerFlowSpec: tool({
      description: 'Generate a markdown spec for one Explorer Agent flow. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
        flowId: z.string(),
        forceRegenerate: z.boolean().optional().default(false),
      }),
    }),

    generateExplorerFlowTest: tool({
      description: 'Generate a runnable spec/test pipeline for one Explorer Agent flow. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
        flowId: z.string(),
        forceRegenerate: z.boolean().optional().default(false),
      }),
    }),

    updateExplorerFlow: tool({
      description: 'Update discovered Explorer Agent flow metadata before generating specs. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
        flowId: z.string(),
        updates: z.record(z.unknown()),
      }),
    }),

    deleteExplorerFlow: tool({
      description: 'Delete a discovered Explorer Agent flow. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
        flowId: z.string(),
      }),
    }),

    saveExplorerSession: tool({
      description: 'Save reusable Explorer Agent authentication session data. Requires approval.',
      inputSchema: z.object({
        sessionId: z.string(),
        cookies: z.array(z.record(z.unknown())).default([]),
        storage: z.record(z.unknown()).default({}),
      }),
    }),

    deleteExplorerSession: tool({
      description: 'Delete a saved Explorer Agent authentication session. Requires approval.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
    }),

    stopExploration: tool({
      description: 'Stop a running or queued exploration session.',
      inputSchema: z.object({
        sessionId: z.string().describe('The exploration session ID to stop'),
      }),
    }),

    generateApiSpecsFromExploration: tool({
      description: 'Generate API specs from an exploration session. Requires approval.',
      inputSchema: z.object({
        sessionId: z.string(),
      }),
    }),

    generateApiTestsFromExploration: tool({
      description: 'Generate API tests from an exploration session. Requires approval.',
      inputSchema: z.object({
        sessionId: z.string(),
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

    createTestSpecFromAgentReport: tool({
      description: 'Create a markdown test spec from a custom agent report finding or test idea. Use after reading getAgentRunReport; requires user approval.',
      inputSchema: z.object({
        specName: z.string().describe('Spec file name, e.g. agent-finding-login-error.md'),
        content: z.string().describe('Markdown spec content with concrete steps and expected outcomes'),
        sourceRunId: z.string().describe('Source custom agent run ID'),
        sourceItemId: z.string().describe('Source finding or test idea ID'),
      }),
    }),

    updateGeneratedCode: tool({
      description: 'Update generated Playwright code for a spec. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
        code: z.string(),
      }),
    }),

    updateSpecMetadata: tool({
      description: 'Update spec metadata such as tags, description, author, or project assignment. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
        tags: z.array(z.string()).optional(),
        description: z.string().optional(),
        author: z.string().optional(),
        projectId: z.string().optional(),
      }),
    }),

    moveSpec: tool({
      description: 'Move a spec file or folder. Requires approval.',
      inputSchema: z.object({
        sourcePath: z.string(),
        destinationFolder: z.string().optional().default(''),
        isFolder: z.boolean().optional().default(false),
      }),
    }),

    renameSpec: tool({
      description: 'Rename a spec file or folder. Requires approval.',
      inputSchema: z.object({
        oldPath: z.string(),
        newName: z.string(),
        isFolder: z.boolean().optional().default(false),
      }),
    }),

    splitSpec: tool({
      description: 'Split a multi-test spec into individual test specs. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
        outputDir: z.string().optional(),
        mode: z.enum(['individual', 'grouped']).optional().default('individual'),
      }),
    }),

    createSpecFolder: tool({
      description: 'Create a folder under specs. Requires approval.',
      inputSchema: z.object({
        folderName: z.string(),
        parentPath: z.string().optional(),
      }),
    }),

    runRegressionBatch: tool({
      description: 'Run multiple test specs as a regression batch.',
      inputSchema: z.object({
        specNames: z.array(z.string()).describe('Array of spec names to run as a batch'),
      }),
    }),

    executeUiTestCoveragePlan: tool({
      description: 'Execute a chat-created UI test coverage plan by running selected specs as a regression batch. Requires approval.',
      inputSchema: z.object({
        specNames: z.array(z.string()).min(1),
        reason: z.string().optional().describe('Short explanation of the coverage plan being executed'),
      }),
    }),

    triggerSecurityScan: tool({
      description: 'Run a quick security scan on a URL.',
      inputSchema: z.object({
        url: z.string().describe('The target URL to scan'),
      }),
    }),

    runSecurityScan: tool({
      description: 'Run a security scan using quick, nuclei, zap, or full mode. Requires approval.',
      inputSchema: z.object({
        scanType: z.enum(['quick', 'nuclei', 'zap', 'full']).optional().default('quick'),
        targetUrl: z.string().url(),
        loginUrl: z.string().url().optional(),
        authConfig: z.record(z.unknown()).optional(),
        usernameKey: z.string().optional(),
        passwordKey: z.string().optional(),
        scope: z.enum(['origin', 'domain']).optional().default('origin'),
        excludedPaths: z.array(z.string()).optional().default([]),
        activeScanLevel: z.enum(['safe', 'moderate', 'aggressive']).optional().default('safe'),
        severityFilter: z.array(z.string()).optional(),
        templates: z.array(z.string()).optional(),
        scanPolicy: z.string().optional(),
      }),
    }),

    stopSecurityScan: tool({
      description: 'Stop a running security scan. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
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

    stopRun: tool({
      description: 'Stop a queued or running test run.',
      inputSchema: z.object({
        runId: z.string().describe('The test run ID to stop'),
      }),
    }),

    stopAllJobs: tool({
      description: 'Emergency stop for all running test processes, Auto Pilot sessions, explorations, and queued work.',
      inputSchema: z.object({}),
    }),

    clearQueue: tool({
      description: 'Clear stuck queued and orphaned running entries from the test execution queue.',
      inputSchema: z.object({
        includeQueued: z.boolean().optional().default(true).describe('Clear queued entries'),
        includeRunning: z.boolean().optional().default(true).describe('Clear orphaned running entries'),
      }),
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

    getSchedule: tool({
      description: 'Get details for a test schedule.',
      inputSchema: z.object({
        scheduleId: z.string().describe('Schedule ID'),
      }),
      execute: async ({ scheduleId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/scheduling/${encodeURIComponent(pid)}/schedules/${encodeURIComponent(scheduleId)}`);
      },
    }),

    validateCronExpression: tool({
      description: 'Validate a cron expression and preview upcoming run times.',
      inputSchema: z.object({
        cronExpression: z.string().describe('5-field cron expression'),
        timezone: z.string().optional().default('UTC'),
      }),
      execute: async ({ cronExpression, timezone }): Promise<ToolResult> => {
        return fetchTool('/scheduling/validate-cron', 'POST', {
          cron_expression: cronExpression,
          timezone: timezone || 'UTC',
        });
      },
    }),

    listScheduleExecutions: tool({
      description: 'List execution history for one schedule.',
      inputSchema: z.object({
        scheduleId: z.string().describe('Schedule ID'),
        limit: z.number().optional().default(20),
        offset: z.number().optional().default(0),
      }),
      execute: async ({ scheduleId, limit, offset }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const params = new URLSearchParams({ limit: String(limit ?? 20), offset: String(offset ?? 0) });
        return fetchTool(`/scheduling/${encodeURIComponent(pid)}/schedules/${encodeURIComponent(scheduleId)}/executions?${params}`);
      },
    }),

    listProjectScheduleExecutions: tool({
      description: 'List recent execution history across all schedules in the current project.',
      inputSchema: z.object({
        limit: z.number().optional().default(15),
        offset: z.number().optional().default(0),
      }),
      execute: async ({ limit, offset }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const params = new URLSearchParams({ limit: String(limit ?? 15), offset: String(offset ?? 0) });
        return fetchTool(`/scheduling/${encodeURIComponent(pid)}/executions?${params}`);
      },
    }),

    getNextScheduleRuns: tool({
      description: 'Get upcoming run times for a schedule.',
      inputSchema: z.object({
        scheduleId: z.string().describe('Schedule ID'),
        count: z.number().optional().default(5),
      }),
      execute: async ({ scheduleId, count }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/scheduling/${encodeURIComponent(pid)}/schedules/${encodeURIComponent(scheduleId)}/next-runs?count=${count ?? 5}`);
      },
    }),

    triggerScheduleNow: tool({
      description: 'Trigger a scheduled test to run immediately.',
      inputSchema: z.object({
        scheduleId: z.string().describe('The schedule ID to trigger'),
      }),
    }),

    createSchedule: tool({
      description: 'Create a cron schedule for recurring test execution. Requires approval.',
      inputSchema: z.object({
        name: z.string(),
        cronExpression: z.string().describe('5-field cron expression'),
        description: z.string().optional(),
        timezone: z.string().optional().default('UTC'),
        tags: z.array(z.string()).optional(),
        automatedOnly: z.boolean().optional().default(true),
        browser: z.string().optional().default('chromium'),
        hybridMode: z.boolean().optional().default(false),
        maxIterations: z.number().optional().default(20),
        specNames: z.array(z.string()).optional(),
        enabled: z.boolean().optional().default(true),
      }),
    }),

    updateSchedule: tool({
      description: 'Update an existing cron schedule. Requires approval.',
      inputSchema: z.object({
        scheduleId: z.string(),
        name: z.string().optional(),
        cronExpression: z.string().optional(),
        description: z.string().optional(),
        timezone: z.string().optional(),
        tags: z.array(z.string()).optional(),
        automatedOnly: z.boolean().optional(),
        browser: z.string().optional(),
        hybridMode: z.boolean().optional(),
        maxIterations: z.number().optional(),
        specNames: z.array(z.string()).optional(),
        enabled: z.boolean().optional(),
      }),
    }),

    deleteSchedule: tool({
      description: 'Delete a schedule and its execution records. Requires approval.',
      inputSchema: z.object({
        scheduleId: z.string(),
      }),
    }),

    toggleSchedule: tool({
      description: 'Toggle a schedule enabled/disabled. Requires approval.',
      inputSchema: z.object({
        scheduleId: z.string(),
      }),
    }),

    // ===== PRD Workflow Tools =====

    listPrdProjects: tool({
      description: 'List uploaded PRD projects.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api/prd/projects${params.toString() ? `?${params.toString()}` : ''}`);
      },
    }),

    listPrdFeatures: tool({
      description: 'List features extracted from a PRD project.',
      inputSchema: z.object({
        prdProjectId: z.string().describe('PRD project ID'),
      }),
      execute: async ({ prdProjectId }): Promise<ToolResult> => {
        return fetchTool(`/api/prd/${encodeURIComponent(prdProjectId)}/features`);
      },
    }),

    listPrdGenerations: tool({
      description: 'List test plan generation history for a PRD project.',
      inputSchema: z.object({
        prdProjectId: z.string().describe('PRD project ID'),
        limit: z.number().optional().default(50),
      }),
      execute: async ({ prdProjectId, limit }): Promise<ToolResult> => {
        return fetchTool(`/api/prd/${encodeURIComponent(prdProjectId)}/generations?limit=${limit ?? 50}`);
      },
    }),

    getPrdGenerationStatus: tool({
      description: 'Get status for a PRD test-plan generation task.',
      inputSchema: z.object({
        generationId: z.number().describe('Generation ID'),
      }),
      execute: async ({ generationId }): Promise<ToolResult> => {
        return fetchTool(`/api/prd/generation/${generationId}`);
      },
    }),

    getPrdQueueStatus: tool({
      description: 'Get PRD/browser queue status.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/api/prd/queue/status'),
    }),

    generatePrdPlan: tool({
      description: 'Generate a test plan/spec for one PRD feature or all features. Requires approval.',
      inputSchema: z.object({
        prdProjectId: z.string().describe('PRD project ID'),
        feature: z.string().optional().describe('Feature name/slug. Omit to generate for all features.'),
        targetUrl: z.string().optional(),
        loginUrl: z.string().optional(),
        credentials: z.record(z.unknown()).optional(),
      }),
    }),

    stopPrdGeneration: tool({
      description: 'Stop a running PRD generation task. Requires approval.',
      inputSchema: z.object({
        generationId: z.number(),
      }),
    }),

    generatePrdTest: tool({
      description: 'Generate a Playwright test from a PRD-generated spec. Requires approval.',
      inputSchema: z.object({
        specPath: z.string(),
        targetUrl: z.string().optional(),
      }),
    }),

    healPrdTest: tool({
      description: 'Heal a generated PRD Playwright test from an error log. Requires approval.',
      inputSchema: z.object({
        testPath: z.string(),
        errorLog: z.string(),
      }),
    }),

    runPrdTest: tool({
      description: 'Run a generated PRD Playwright test with optional healing. Requires approval.',
      inputSchema: z.object({
        testPath: z.string(),
        heal: z.boolean().optional().default(true),
        maxAttempts: z.number().optional().default(3),
      }),
    }),

    // ===== CI/CD and PR Advisor Tools =====

    getCiControlOverview: tool({
      description: 'Get a chat-native CI/CD overview: provider readiness, workflows, synced runs, audit activity, PR analyses, and quality gates.',
      inputSchema: z.object({
        provider: z.enum(['all', 'github', 'gitlab']).optional().default('all'),
        includeAudit: z.boolean().optional().default(true),
        limit: z.number().optional().default(20),
      }),
      execute: async ({ provider, includeAudit, limit }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const encoded = encodeURIComponent(pid);
        const selected = provider || 'all';
        const runProvider = selected === 'all' ? 'all' : selected;
        const max = Math.max(1, Math.min(Number(limit ?? 20), 50));
        const providers = await fetchTool(`/projects/${encoded}/ci/providers`) as Record<string, unknown>[] | Record<string, unknown>;
        const providerList = Array.isArray(providers) ? providers : [];
        const shouldFetchGithub = selected !== 'gitlab' && providerList.some((item) => item.provider === 'github' && item.configured && item.setup_status !== 'needs_repository');
        const shouldFetchGitlab = selected !== 'github' && providerList.some((item) => item.provider === 'gitlab' && item.configured && item.setup_status !== 'needs_project');
        const [githubWorkflows, gitlabWorkflows, runs, auditEvents, prAnalyses, qualityGates, openPullRequests] = await Promise.all([
          shouldFetchGithub ? fetchTool(`/projects/${encoded}/ci/workflows?provider=github`) : Promise.resolve([]),
          shouldFetchGitlab ? fetchTool(`/projects/${encoded}/ci/workflows?provider=gitlab`) : Promise.resolve([]),
          fetchTool(`/projects/${encoded}/ci/runs?provider=${runProvider}`),
          includeAudit ? fetchTool(`/projects/${encoded}/ci/audit-events?limit=${max}`) : Promise.resolve([]),
          selected !== 'gitlab' ? fetchTool(`/github/${encoded}/pr-advisor/analyses?limit=${max}`) : Promise.resolve([]),
          selected !== 'gitlab' ? fetchTool(`/github/${encoded}/quality-gates/pr?limit=${max}`) : Promise.resolve([]),
          shouldFetchGithub ? fetchTool(`/github/${encoded}/pull-requests?state=open&limit=${max}`) : Promise.resolve([]),
        ]);
        const workflows = [
          ...(Array.isArray(githubWorkflows) ? githubWorkflows : []),
          ...(Array.isArray(gitlabWorkflows) ? gitlabWorkflows : []),
        ];
        const runList = Array.isArray(runs) ? runs : [];
        const activeRuns = runList.filter((run) => ['pending', 'running', 'queued', 'waiting', 'in_progress'].includes(String((run as Record<string, unknown>).status || '').toLowerCase()));
        const failedRuns = runList.filter((run) => ['failed', 'failure'].includes(String((run as Record<string, unknown>).status || '').toLowerCase()));
        return {
          status: failedRuns.length > 0 ? 'attention' : activeRuns.length > 0 ? 'running' : 'ready',
          provider: selected,
          providers: providerList,
          workflows,
          runs: runList,
          audit_events: Array.isArray(auditEvents) ? auditEvents : [],
          pr_analyses: Array.isArray(prAnalyses) ? prAnalyses : [],
          quality_gates: Array.isArray(qualityGates) ? qualityGates : [],
          open_pull_requests: Array.isArray(openPullRequests) ? openPullRequests : [],
          summary: {
            providers: providerList.length,
            workflows: workflows.length,
            runs: runList.length,
            active_runs: activeRuns.length,
            failed_runs: failedRuns.length,
            open_pull_requests: Array.isArray(openPullRequests) ? openPullRequests.length : 0,
          },
        } as ToolResult;
      },
    }),

    listOpenPullRequests: tool({
      description: 'List pull requests from the configured GitHub repository for the current project. Use this before PR Advisor when the user has not provided a PR number.',
      inputSchema: z.object({
        state: z.enum(['open', 'closed', 'all']).optional().default('open'),
        limit: z.number().optional().default(30),
      }),
      execute: async ({ state, limit }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const params = new URLSearchParams({
          state: state || 'open',
          limit: String(Math.max(1, Math.min(Number(limit ?? 30), 100))),
        });
        return fetchTool(`/github/${encodeURIComponent(pid)}/pull-requests?${params}`);
      },
    }),

    listCiProviders: tool({
      description: 'List configured CI providers and their capabilities for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/providers`);
      },
    }),

    listGeneratedCiTests: tool({
      description: 'List generated Playwright tests that can be selected into a chat-controlled GitHub Actions subset.',
      inputSchema: z.object({
        search: z.string().optional(),
        limit: z.number().optional().default(100),
        offset: z.number().optional().default(0),
      }),
      execute: async ({ search, limit, offset }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const params = new URLSearchParams({
          limit: String(Math.max(1, Math.min(Number(limit ?? 100), 500))),
          offset: String(Math.max(0, Number(offset ?? 0))),
        });
        if (search) params.set('search', search);
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/generated-tests?${params}`);
      },
    }),

    listCiTestSubsets: tool({
      description: 'List saved chat-controlled CI test subsets for generated Playwright tests.',
      inputSchema: z.object({
        includeItems: z.boolean().optional().default(true),
      }),
      execute: async ({ includeItems }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/test-subsets?include_items=${includeItems ?? true}`);
      },
    }),

    getCiTestSubset: tool({
      description: 'Get one saved CI test subset with selected generated test items.',
      inputSchema: z.object({
        subsetId: z.string(),
      }),
      execute: async ({ subsetId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/test-subsets/${encodeURIComponent(subsetId)}`);
      },
    }),

    previewCiTestSubset: tool({
      description: 'Preview files Quorvex will commit for a saved CI test subset.',
      inputSchema: z.object({
        subsetId: z.string(),
      }),
      execute: async ({ subsetId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/test-subsets/${encodeURIComponent(subsetId)}/preview`, 'POST');
      },
    }),

    listCiWorkflows: tool({
      description: 'List CI workflows for GitHub or GitLab.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']).optional().default('github'),
      }),
      execute: async ({ provider }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/workflows?provider=${provider || 'github'}`);
      },
    }),

    listCiRuns: tool({
      description: 'List CI runs synced into Quorvex for the current project.',
      inputSchema: z.object({
        provider: z.enum(['all', 'github', 'gitlab']).optional().default('all'),
      }),
      execute: async ({ provider }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/runs?provider=${provider || 'all'}`);
      },
    }),

    getCiRunDetail: tool({
      description: 'Get CI run detail, optionally refreshing from the provider.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']),
        mappingId: z.number().describe('Local CI pipeline mapping ID'),
        refresh: z.boolean().optional().default(false),
      }),
      execute: async ({ provider, mappingId, refresh }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/runs/${provider}/${mappingId}?refresh=${refresh ?? false}`);
      },
    }),

    getCiRunLogs: tool({
      description: 'Get CI run logs or log archive URL.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']),
        mappingId: z.number().describe('Local CI pipeline mapping ID'),
        jobId: z.string().optional().describe('Optional provider job ID, mainly for GitLab'),
      }),
      execute: async ({ provider, mappingId, jobId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const params = new URLSearchParams();
        if (jobId) params.set('job_id', jobId);
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/runs/${provider}/${mappingId}/logs?${params}`);
      },
    }),

    listCiAuditEvents: tool({
      description: 'List CI integration audit events for the current project.',
      inputSchema: z.object({
        limit: z.number().optional().default(50),
      }),
      execute: async ({ limit }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/projects/${encodeURIComponent(pid)}/ci/audit-events?limit=${limit ?? 50}`);
      },
    }),

    listPrAdvisorAnalyses: tool({
      description: 'List recent PR Advisor impact analyses.',
      inputSchema: z.object({
        limit: z.number().optional().default(20),
      }),
      execute: async ({ limit }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/github/${encodeURIComponent(pid)}/pr-advisor/analyses?limit=${limit ?? 20}`);
      },
    }),

    getPrAdvisorAnalysis: tool({
      description: 'Get detailed PR Advisor analysis with changed files and selected tests.',
      inputSchema: z.object({
        analysisId: z.string(),
      }),
      execute: async ({ analysisId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/github/${encodeURIComponent(pid)}/pr-advisor/analyses/${encodeURIComponent(analysisId)}`);
      },
    }),

    getQualityGateConfig: tool({
      description: 'Get GitHub PR quality gate defaults for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/github/${encodeURIComponent(pid)}/quality-gates/config`);
      },
    }),

    listPrQualityGates: tool({
      description: 'List recent GitHub PR quality gate runs.',
      inputSchema: z.object({
        limit: z.number().optional().default(20),
      }),
      execute: async ({ limit }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/github/${encodeURIComponent(pid)}/quality-gates/pr?limit=${limit ?? 20}`);
      },
    }),

    getPrQualityGate: tool({
      description: 'Get current state for a stored PR quality gate analysis.',
      inputSchema: z.object({
        analysisId: z.string(),
        refreshFeedback: z.boolean().optional().default(false),
      }),
      execute: async ({ analysisId, refreshFeedback }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/github/${encodeURIComponent(pid)}/quality-gates/pr/${encodeURIComponent(analysisId)}?refresh_feedback=${refreshFeedback ?? false}`);
      },
    }),

    getPrQualityGateStatus: tool({
      description: 'Get CI-friendly quality gate status for a PR number and head SHA.',
      inputSchema: z.object({
        prNumber: z.number(),
        headSha: z.string(),
      }),
      execute: async ({ prNumber, headSha }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        const params = new URLSearchParams({ pr_number: String(prNumber), head_sha: headSha });
        return fetchTool(`/github/${encodeURIComponent(pid)}/quality-gates/pr/status?${params}`);
      },
    }),

    syncCiRuns: tool({
      description: 'Sync CI runs from configured providers. Requires approval.',
      inputSchema: z.object({
        provider: z.enum(['all', 'github', 'gitlab']).optional().default('all'),
        workflowId: z.string().optional(),
        perPage: z.number().optional().default(20),
      }),
    }),

    dispatchCiWorkflow: tool({
      description: 'Dispatch a GitHub workflow or GitLab pipeline. Requires approval.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']).optional().default('github'),
        workflowId: z.string().optional().describe('GitHub workflow ID/path/name; optional for GitLab'),
        ref: z.string().optional().describe('Branch/ref'),
        inputs: z.record(z.string()).optional().describe('Workflow inputs or GitLab variables'),
        suite: z.enum(RUNNER_SUBSET_SUITES).optional().describe('Runner subset workflow input: test suite to run. Use with runner-subset-tests/quorvex-subset-tests.yml.'),
        browser: z.enum(RUNNER_SUBSET_BROWSERS).optional().describe('Runner subset workflow input: Playwright browser for generated/E2E suites.'),
        pytestMarker: z.enum(RUNNER_SUBSET_MARKERS).optional().describe('Runner subset workflow input: pytest marker expression for Python suites.'),
        testPath: z.string().optional().describe('Runner subset workflow input: specific pytest path or Playwright test path.'),
        playwrightGrep: z.string().optional().describe('Runner subset workflow input: grep expression for Playwright suites.'),
        baseUrl: z.string().optional().describe('Runner subset workflow input: app base URL override for Playwright suites.'),
      }),
    }),

    cancelCiRun: tool({
      description: 'Cancel a synced CI run. Requires approval.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']),
        mappingId: z.number().describe('Local CI pipeline mapping ID'),
      }),
    }),

    rerunCiRun: tool({
      description: 'Rerun a synced CI run. Requires approval.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']),
        mappingId: z.number().describe('Local CI pipeline mapping ID'),
        failedOnly: z.boolean().optional().default(false).describe('GitHub only: rerun failed jobs only'),
      }),
    }),

    generateCiWorkflowChange: tool({
      description: 'Generate a GitHub Actions workflow change request for Quorvex testing. Requires approval.',
      inputSchema: z.object({
        workflowName: z.string().optional().default('Quorvex Test Automation'),
        template: z.enum(['pr-quality-gate', 'playwright-smoke', 'nightly-regression', 'release-gate', 'runner-subset-tests']).optional().default('pr-quality-gate'),
        qualityGateMode: z.enum(['backend-async', 'backend-blocking']).optional().default('backend-async').describe('For PR quality gates: backend-async starts Quorvex and returns; backend-blocking waits in GitHub Actions until Quorvex passes or fails.'),
        prompt: z.string().optional(),
        ref: z.string().optional(),
        branches: z.array(z.string()).optional(),
        browsers: z.array(z.string()).optional(),
        artifactRetentionDays: z.number().optional().default(14),
        waitTimeoutMinutes: z.number().optional().default(120),
      }),
    }),

    openCiWorkflowPullRequest: tool({
      description: 'Open a GitHub pull request for a generated CI workflow change request. Requires approval.',
      inputSchema: z.object({
        changeId: z.string(),
        baseRef: z.string().optional(),
        branchName: z.string().optional(),
        title: z.string().optional(),
        body: z.string().optional(),
        commitMessage: z.string().optional(),
        draft: z.boolean().optional().default(true),
      }),
    }),

    updateCiProviderDefaults: tool({
      description: 'Update non-secret CI provider defaults such as repository/project selection, default ref, or default workflow. Requires approval. Tokens and webhook secrets must still be configured in Settings.',
      inputSchema: z.object({
        provider: z.enum(['github', 'gitlab']),
        repository: z.string().optional().describe('GitHub repository in owner/repo format'),
        owner: z.string().optional().describe('GitHub owner/org'),
        repo: z.string().optional().describe('GitHub repository name'),
        gitlabProjectId: z.number().optional().describe('GitLab project ID'),
        baseUrl: z.string().optional().describe('GitLab base URL, e.g. https://gitlab.com'),
        defaultRef: z.string().optional().describe('Default branch or ref'),
        defaultWorkflow: z.string().optional().describe('GitHub workflow ID/path/name to use by default'),
      }),
    }),

    createCiTestSubset: tool({
      description: 'Save a named subset of generated Playwright tests for GitHub Actions PR runs. Requires approval.',
      inputSchema: z.object({
        name: z.string(),
        description: z.string().optional(),
        mode: z.enum(CI_TEST_SUBSET_MODES).optional().default('both').describe('manual runs saved subset only; pr-impact asks PR Advisor; both falls back to saved subset when no PR-impact selection is available.'),
        defaultBrowser: z.enum(RUNNER_SUBSET_BROWSERS).optional().default('chromium'),
        baseUrlSecret: z.string().optional().default('APP_BASE_URL'),
        items: z.array(CI_TEST_SUBSET_ITEM_SCHEMA).min(1),
      }),
    }),

    updateCiTestSubset: tool({
      description: 'Update a saved generated-test CI subset. Requires approval.',
      inputSchema: z.object({
        subsetId: z.string(),
        name: z.string().optional(),
        description: z.string().optional(),
        mode: z.enum(CI_TEST_SUBSET_MODES).optional(),
        defaultBrowser: z.enum(RUNNER_SUBSET_BROWSERS).optional(),
        baseUrlSecret: z.string().optional(),
        items: z.array(CI_TEST_SUBSET_ITEM_SCHEMA).optional(),
      }),
    }),

    deleteCiTestSubset: tool({
      description: 'Delete a saved generated-test CI subset. Requires approval.',
      inputSchema: z.object({
        subsetId: z.string(),
      }),
    }),

    openCiTestSubsetPullRequest: tool({
      description: 'Open a draft GitHub PR that commits selected generated tests, subset manifest, Playwright scaffold when missing, and the GitHub Actions workflow. Requires approval.',
      inputSchema: z.object({
        subsetId: z.string(),
        baseRef: z.string().optional(),
        branchName: z.string().optional(),
        title: z.string().optional(),
        body: z.string().optional(),
        workflowName: z.string().optional(),
        commitMessage: z.string().optional(),
        draft: z.boolean().optional().default(true),
      }),
    }),

    dispatchCiTestSubset: tool({
      description: 'Dispatch the installed GitHub Actions workflow for a saved generated-test subset. Requires approval.',
      inputSchema: z.object({
        subsetId: z.string(),
        workflowId: z.string().optional(),
        ref: z.string().optional(),
        browser: z.enum(RUNNER_SUBSET_BROWSERS).optional(),
        baseUrl: z.string().optional(),
      }),
    }),

    analyzePullRequestTests: tool({
      description: 'Analyze a configured GitHub PR and recommend impacted Quorvex tests. Requires approval because it may index repository data.',
      inputSchema: z.object({
        prNumber: z.number(),
        ensureIndexed: z.boolean().optional().default(true),
        forceReindex: z.boolean().optional().default(false),
      }),
    }),

    runPrAdvisorRecommendedTests: tool({
      description: 'Run tests selected by a PR Advisor analysis as a regression batch. Optionally provide specNames to run only a subset of the selected tests. Requires approval.',
      inputSchema: z.object({
        analysisId: z.string(),
        specNames: z.array(z.string()).optional().describe('Optional subset of selected spec names to run. Must be part of the PR Advisor selected tests.'),
        browser: z.string().optional().default('chromium'),
        hybrid: z.boolean().optional().default(false),
        maxIterations: z.number().optional().default(20),
      }),
    }),

    startPrQualityGate: tool({
      description: 'Start a GitHub PR quality gate: analyze a PR, optionally run recommended tests, and optionally publish feedback. Requires approval.',
      inputSchema: z.object({
        prNumber: z.number(),
        headSha: z.string().optional(),
        ensureIndexed: z.boolean().optional(),
        runRecommended: z.boolean().optional(),
        postFeedback: z.boolean().optional(),
        createCommitStatus: z.boolean().optional(),
        browser: z.enum(['chromium', 'firefox', 'webkit']).optional(),
        hybrid: z.boolean().optional(),
        maxIterations: z.number().optional(),
        forceReindex: z.boolean().optional(),
      }),
    }),

    // ===== Jira and TestRail Integration Tools =====

    getJiraConfig: tool({
      description: 'Get masked Jira integration config for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/jira/${encodeURIComponent(pid)}/config`);
      },
    }),

    testJiraConnection: tool({
      description: 'Test the stored Jira connection for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/jira/${encodeURIComponent(pid)}/test-connection`, 'POST');
      },
    }),

    getJiraBugReportJob: tool({
      description: 'Get status for a Jira bug report generation job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/jira/${encodeURIComponent(pid)}/bug-report-jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    listJiraIssues: tool({
      description: 'List Jira issues created from Quorvex runs for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/jira/${encodeURIComponent(pid)}/issues`);
      },
    }),

    getJiraIssueForRun: tool({
      description: 'Check whether a Jira issue exists for a specific test run.',
      inputSchema: z.object({
        runId: z.string(),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/jira/${encodeURIComponent(pid)}/issues/${encodeURIComponent(runId)}`);
      },
    }),

    generateJiraBugReport: tool({
      description: 'Generate an AI Jira bug report draft from a failed run. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
      }),
    }),

    createJiraIssue: tool({
      description: 'Create a Jira issue from a reviewed bug report. Requires approval.',
      inputSchema: z.object({
        runId: z.string(),
        projectKey: z.string(),
        issueTypeId: z.string(),
        title: z.string(),
        description: z.string(),
        priorityName: z.string().optional(),
        labels: z.array(z.string()).optional(),
        attachScreenshots: z.boolean().optional().default(true),
      }),
    }),

    getTestRailConfig: tool({
      description: 'Get masked TestRail integration config for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/testrail/${encodeURIComponent(pid)}/config`);
      },
    }),

    testTestRailConnection: tool({
      description: 'Test the stored TestRail connection for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/testrail/${encodeURIComponent(pid)}/test-connection`, 'POST');
      },
    }),

    listTestRailMappings: tool({
      description: 'List spec-to-TestRail case mappings for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/testrail/${encodeURIComponent(pid)}/mappings`);
      },
    }),

    getTestRailSyncPreview: tool({
      description: 'Preview syncing a regression batch to TestRail.',
      inputSchema: z.object({
        batchId: z.string(),
      }),
      execute: async ({ batchId }): Promise<ToolResult> => {
        const pid = projectId || 'default';
        return fetchTool(`/testrail/${encodeURIComponent(pid)}/sync-preview/${encodeURIComponent(batchId)}`);
      },
    }),

    pushTestRailCases: tool({
      description: 'Push selected specs to TestRail as test cases. Requires approval.',
      inputSchema: z.object({
        specNames: z.array(z.string()).min(1),
        testrailProjectId: z.number(),
        testrailSuiteId: z.number(),
        sectionId: z.number().optional(),
      }),
    }),

    syncTestRailResults: tool({
      description: 'Sync a completed regression batch result to TestRail. Requires approval.',
      inputSchema: z.object({
        batchId: z.string(),
        testrailProjectId: z.number(),
        testrailSuiteId: z.number(),
        runName: z.string().optional(),
      }),
    }),

    deleteTestRailMapping: tool({
      description: 'Delete a spec-to-TestRail case mapping. Requires approval.',
      inputSchema: z.object({
        mappingId: z.number(),
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

    listApiSpecs: tool({
      description: 'List API test specifications with generation/run status. Supports pagination, search, sorting, and status filtering.',
      inputSchema: z.object({
        search: z.string().optional().describe('Search API specs by name'),
        limit: z.number().optional().default(20).describe('Max results to return'),
        offset: z.number().optional().default(0).describe('Pagination offset'),
        sort: z.enum(['name', 'status', 'last_run', 'test_count', 'modified']).optional().default('name'),
        statusFilter: z.enum(['passed', 'failed', 'not_run', 'no_tests']).optional().describe('Optional status filter'),
      }),
      execute: async ({ search, limit, offset, sort, statusFilter }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 20));
        params.set('offset', String(offset ?? 0));
        params.set('sort', sort ?? 'name');
        if (search) params.set('search', search);
        if (statusFilter) params.set('status_filter', statusFilter);
        return fetchTool(`/api-testing/specs?${params}`);
      },
    }),

    getApiSpec: tool({
      description: 'Get the markdown content for a specific API test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The API spec file name, e.g. users-api.md'),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/api-testing/specs/${encodeURIComponent(specName)}?${params}`);
      },
    }),

    getApiJobStatus: tool({
      description: 'Get the status of an API testing background job by job ID.',
      inputSchema: z.object({
        jobId: z.string().describe('The API job ID returned by generation/import/run actions'),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/api-testing/jobs/${encodeURIComponent(jobId)}`);
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

    listDatabaseConnections: tool({
      description: 'List configured database testing connections for the current project. Use this before generating database specs when the connection ID is unknown.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/database-testing/connections?${params}`);
      },
    }),

    listDatabaseSpecs: tool({
      description: 'List database testing specs for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/database-testing/specs?${params}`);
      },
    }),

    getDatabaseJobStatus: tool({
      description: 'Get the status of a database testing background job by job ID, including AI database spec generation jobs.',
      inputSchema: z.object({
        jobId: z.string().describe('The database testing job ID returned by generation or run actions'),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/database-testing/jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    saveGeneratedDatabaseSpec: tool({
      description: 'Save reviewed database checks returned by a database spec generation job as a database spec. Confirm before use.',
      inputSchema: z.object({
        specName: z.string().optional().describe('Optional database spec file name'),
        checks: z.array(z.record(z.string(), z.unknown())).min(1).describe('Generated check objects to save'),
      }),
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

    refreshRegressionBatch: tool({
      description: 'Recalculate regression batch statistics from associated runs. Requires approval.',
      inputSchema: z.object({
        batchId: z.string(),
      }),
    }),

    cancelRegressionBatch: tool({
      description: 'Cancel all queued or running runs in a regression batch. Requires approval.',
      inputSchema: z.object({
        batchId: z.string(),
      }),
    }),

    renameRegressionBatch: tool({
      description: 'Rename a regression batch. Requires approval.',
      inputSchema: z.object({
        batchId: z.string(),
        name: z.string(),
      }),
    }),

    deleteRegressionBatch: tool({
      description: 'Delete a regression batch while preserving associated runs. Requires approval.',
      inputSchema: z.object({
        batchId: z.string(),
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

    listLoadSpecs: tool({
      description: 'List load testing specs for the current project.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/specs?${params}`);
      },
    }),

    getLoadSpec: tool({
      description: 'Get markdown content for a load testing spec.',
      inputSchema: z.object({
        specName: z.string(),
      }),
      execute: async ({ specName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/specs/${encodeURIComponent(specName)}?${params}`);
      },
    }),

    listLoadScripts: tool({
      description: 'List generated K6 load testing scripts.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/scripts?${params}`);
      },
    }),

    getLoadScript: tool({
      description: 'Get one generated K6 load testing script.',
      inputSchema: z.object({
        scriptName: z.string(),
      }),
      execute: async ({ scriptName }): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/scripts/${encodeURIComponent(scriptName)}?${params}`);
      },
    }),

    listLoadTestJobs: tool({
      description: 'List load testing background jobs.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/jobs?${params}`);
      },
    }),

    getLoadTestJobStatus: tool({
      description: 'Get status for a load testing background job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/load-testing/jobs/${encodeURIComponent(jobId)}`);
      },
    }),

    getLoadTestJobLogs: tool({
      description: 'Get logs for a load testing background job.',
      inputSchema: z.object({
        jobId: z.string(),
      }),
      execute: async ({ jobId }): Promise<ToolResult> => {
        return fetchTool(`/load-testing/jobs/${encodeURIComponent(jobId)}/logs`);
      },
    }),

    getLatestLoadRunsBySpec: tool({
      description: 'Get latest load test runs grouped by spec.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/load-testing/runs/latest-by-spec?${params}`);
      },
    }),

    getLoadTestRunDetails: tool({
      description: 'Get one load test run with metrics and status.',
      inputSchema: z.object({
        runId: z.string(),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/load-testing/runs/${encodeURIComponent(runId)}`);
      },
    }),

    getLoadTestTimeseries: tool({
      description: 'Get timeseries metrics for a load test run.',
      inputSchema: z.object({
        runId: z.string(),
      }),
      execute: async ({ runId }): Promise<ToolResult> => {
        return fetchTool(`/load-testing/runs/${encodeURIComponent(runId)}/timeseries`);
      },
    }),

    getLoadTestingStatus: tool({
      description: 'Get current load testing worker/lock status.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => fetchTool('/load-testing/status'),
    }),

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

    stopLoadTestRun: tool({
      description: 'Stop a running load test and release its execution lock.',
      inputSchema: z.object({
        runId: z.string().describe('The load test run ID to stop'),
      }),
    }),

    forceUnlockLoadTesting: tool({
      description: 'Force-release a stuck load testing lock. Use only when no legitimate load test is still running.',
      inputSchema: z.object({}),
    }),

    createLoadSpec: tool({
      description: 'Create a new load test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The load spec name'),
        content: z.string().describe('Markdown load test spec content'),
      }),
    }),

    updateLoadSpec: tool({
      description: 'Update an existing load test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The load spec file name'),
        content: z.string().describe('New markdown content'),
      }),
    }),

    deleteLoadSpec: tool({
      description: 'Delete a load test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The load spec file name to delete'),
      }),
    }),

    generateLoadScript: tool({
      description: 'Generate a K6 load test script from a load test spec.',
      inputSchema: z.object({
        specName: z.string().describe('The load spec file name'),
      }),
    }),

    runLoadTest: tool({
      description: 'Run an existing K6 script.',
      inputSchema: z.object({
        scriptPath: z.string().describe('Relative K6 script path'),
        specName: z.string().optional().describe('Optional related load spec name'),
        vus: z.number().optional().describe('Virtual users'),
        duration: z.string().optional().describe('Run duration, e.g. 2m or 30s'),
      }),
    }),

    runLoadTestFromSpec: tool({
      description: 'Run a load test from a load spec that already has a generated script.',
      inputSchema: z.object({
        specName: z.string().describe('The load spec file name'),
        vus: z.number().optional().describe('Virtual users'),
        duration: z.string().optional().describe('Run duration, e.g. 2m or 30s'),
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

    createSecuritySpec: tool({
      description: 'Create a security testing spec. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
        content: z.string(),
      }),
    }),

    updateSecuritySpec: tool({
      description: 'Update a security testing spec. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
        content: z.string(),
      }),
    }),

    deleteSecuritySpec: tool({
      description: 'Delete a security testing spec. Requires approval.',
      inputSchema: z.object({
        specName: z.string(),
      }),
    }),

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

    generateSecuritySpecFromExploration: tool({
      description: 'Generate a security testing spec from an exploration session. Requires approval.',
      inputSchema: z.object({
        sessionId: z.string().describe('Exploration session ID'),
      }),
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
        format: z.enum(['markdown', 'csv', 'html']).describe('Export format'),
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

    generateDatabaseSpec: tool({
      description: 'Generate a database testing spec from a configured database connection and natural-language instructions. Requires user approval and always starts with auto_run=false.',
      inputSchema: z.object({
        connectionId: z.string().describe('The database connection ID to inspect'),
        instructions: z.string().describe('Natural-language instructions for what the generated database spec should cover'),
        specName: z.string().optional().describe('Optional generated spec name'),
      }),
    }),

    createApiSpec: tool({
      description: 'Create a new API test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The API spec name'),
        content: z.string().describe('Markdown API spec content'),
      }),
    }),

    createAndGenerateApiTest: tool({
      description: 'Create a new API test specification and immediately generate a Playwright API test from it. Use when the user asks to create/generate API tests from natural language or a demo idea.',
      inputSchema: z.object({
        specName: z.string().describe('The API spec name'),
        content: z.string().describe('Markdown API spec content'),
      }),
    }),

    updateApiSpec: tool({
      description: 'Update an existing API test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The API spec file name'),
        content: z.string().describe('New markdown content'),
      }),
    }),

    deleteApiSpec: tool({
      description: 'Delete an API test specification.',
      inputSchema: z.object({
        specName: z.string().describe('The API spec file name to delete'),
      }),
    }),

    importOpenApiSpec: tool({
      description: 'Import an OpenAPI or Swagger specification from a URL and generate API tests.',
      inputSchema: z.object({
        url: z.string().url().describe('The OpenAPI/Swagger document URL'),
        featureFilter: z.string().optional().describe('Optional feature or tag filter'),
      }),
    }),

    generateApiTest: tool({
      description: 'Generate a Playwright API test from an API spec.',
      inputSchema: z.object({
        specName: z.string().describe('The API spec file name'),
      }),
    }),

    runApiTest: tool({
      description: 'Run an API spec through the generate, run, and heal pipeline.',
      inputSchema: z.object({
        specPath: z.string().describe('Relative API spec path'),
      }),
    }),

    runApiTestDirect: tool({
      description: 'Run an already generated API test directly.',
      inputSchema: z.object({
        testPath: z.string().describe('Relative generated test path'),
        specName: z.string().describe('Related API spec name'),
      }),
    }),

    generateApiEdgeCases: tool({
      description: 'Generate API edge case and security tests from an API spec.',
      inputSchema: z.object({
        specPath: z.string().describe('Relative API spec path'),
      }),
    }),

    // ===== Custom Workflow Tools =====

    listWorkflows: tool({
      description: 'List custom workflow definitions and recent workflow runs for the current project. Use for /workflow status, custom workflow inventory, or recent custom workflow activity.',
      inputSchema: z.object({
        status: z.string().optional().describe('Optional run status filter, e.g. running, paused, completed, failed, cancelled'),
        limit: z.number().optional().default(20).describe('Maximum definitions/runs to return'),
        includeCatalog: z.boolean().optional().default(false).describe('Include workflow catalog/templates in the response'),
      }),
      execute: async ({ status, limit, includeCatalog }): Promise<ToolResult> => {
        const params = projectParams();
        params.set('limit', String(limit ?? 20));
        if (status) params.set('status', status);
        const [overview, definitions, runs, catalog] = await Promise.all([
          fetchTool(`/workflows?${params}`),
          fetchTool(`/workflows/definitions?${params}`),
          fetchTool(`/workflows/runs?${params}`),
          includeCatalog ? fetchTool(`/workflows/catalog?${params}`) : Promise.resolve(null),
        ]);
        return {
          overview,
          definitions,
          runs,
          catalog: includeCatalog ? catalog : undefined,
        } as ToolResult;
      },
    }),

    listWorkflowCatalog: tool({
      description: 'List available custom workflow catalog templates and capabilities.',
      inputSchema: z.object({}),
      execute: async (): Promise<ToolResult> => {
        const params = projectParams();
        return fetchTool(`/workflows/catalog?${params}`);
      },
    }),

    getWorkflow: tool({
      description: 'Get one custom workflow definition and optionally its recent runs.',
      inputSchema: z.object({
        workflowId: z.string().describe('Custom workflow definition ID'),
        includeRuns: z.boolean().optional().default(true),
      }),
      execute: async ({ workflowId, includeRuns }): Promise<ToolResult> => {
        const params = projectParams();
        const [definition, runs] = await Promise.all([
          fetchTool(`/workflows/definitions/${encodeURIComponent(workflowId)}?${params}`),
          includeRuns ? fetchTool(`/workflows/definitions/${encodeURIComponent(workflowId)}/runs?${params}`) : Promise.resolve(null),
        ]);
        return { definition, runs: includeRuns ? runs : undefined } as ToolResult;
      },
    }),

    createWorkflow: tool({
      description: 'Create a reusable custom workflow definition. For chatbot-created QA workflows, prefer steps that run a saved custom agent, wait for it, review the report, then use materialize_agent_report to create requirements/specs. Requires approval.',
      inputSchema: z.object({
        name: z.string().describe('Workflow name'),
        description: z.string().optional(),
        definition: z.record(z.unknown()).optional().describe('Structured workflow definition/configuration'),
        steps: z.array(z.record(z.unknown())).optional().describe('Workflow steps if the backend accepts step arrays'),
        trigger: z.record(z.unknown()).optional().describe('Optional trigger configuration'),
        config: z.record(z.unknown()).optional().describe('Optional execution/configuration settings'),
        tags: z.array(z.string()).optional(),
        isEnabled: z.boolean().optional().default(true),
      }),
    }),

    updateWorkflow: tool({
      description: 'Update a custom workflow definition. Requires approval.',
      inputSchema: z.object({
        workflowId: z.string().describe('Custom workflow definition ID'),
        name: z.string().optional(),
        description: z.string().optional(),
        definition: z.record(z.unknown()).optional(),
        steps: z.array(z.record(z.unknown())).optional(),
        trigger: z.record(z.unknown()).optional(),
        config: z.record(z.unknown()).optional(),
        tags: z.array(z.string()).optional(),
        isEnabled: z.boolean().optional(),
      }),
    }),

    duplicateWorkflow: tool({
      description: 'Duplicate a custom workflow definition. Requires approval.',
      inputSchema: z.object({
        workflowId: z.string().describe('Custom workflow definition ID to duplicate'),
      }),
    }),

    archiveWorkflow: tool({
      description: 'Archive a custom workflow definition for the current project. Requires approval.',
      inputSchema: z.object({
        workflowId: z.string().describe('Custom workflow definition ID to archive'),
      }),
    }),

    startWorkflow: tool({
      description: 'Start a custom workflow run from a saved workflow definition. Requires approval.',
      inputSchema: z.object({
        workflowId: z.string().describe('Custom workflow definition ID'),
        inputs: z.record(z.unknown()).optional().describe('Workflow input values'),
        parameters: z.record(z.unknown()).optional().describe('Optional run parameters'),
        context: z.record(z.unknown()).optional().describe('Optional execution context'),
        startStepKey: z.string().optional().describe('Optional workflow step key to start from'),
        idempotencyKey: z.string().optional().describe('Optional client idempotency key'),
      }),
    }),

    startWorkflowFromStep: tool({
      description: 'Start a custom workflow run from a specific step key. Requires approval.',
      inputSchema: z.object({
        workflowId: z.string().describe('Custom workflow definition ID'),
        startStepKey: z.string().describe('Workflow step key to start from'),
        inputs: z.record(z.unknown()).optional().describe('Workflow input values'),
        parameters: z.record(z.unknown()).optional().describe('Optional run parameters'),
      }),
    }),

    getWorkflowStatus: tool({
      description: 'Get status for a custom workflow run, including its step list.',
      inputSchema: z.object({
        runId: z.string().describe('Custom workflow run ID'),
        includeSteps: z.boolean().optional().default(true),
      }),
      execute: async ({ runId, includeSteps }): Promise<ToolResult> => {
        const params = projectParams();
        const [run, steps] = await Promise.all([
          fetchTool(`/workflows/runs/${encodeURIComponent(runId)}?${params}`),
          includeSteps ? fetchTool(`/workflows/runs/${encodeURIComponent(runId)}/steps?${params}`) : Promise.resolve(null),
        ]);
        return { run, steps: includeSteps ? steps : undefined } as ToolResult;
      },
    }),

    retryWorkflowFailedStep: tool({
      description: 'Retry a failed step within a custom workflow run. Requires approval.',
      inputSchema: z.object({
        runId: z.string().describe('Custom workflow run ID'),
        stepId: z.string().describe('Failed workflow run step ID to retry'),
      }),
    }),

    pauseWorkflowRun: tool({
      description: 'Pause a running custom workflow run. Requires approval.',
      inputSchema: z.object({
        runId: z.string().describe('Custom workflow run ID to pause'),
      }),
    }),

    resumeWorkflowRun: tool({
      description: 'Resume a paused custom workflow run. Requires approval.',
      inputSchema: z.object({
        runId: z.string().describe('Custom workflow run ID to resume'),
      }),
    }),

    cancelWorkflowRun: tool({
      description: 'Cancel a running or queued custom workflow run. Requires approval.',
      inputSchema: z.object({
        runId: z.string().describe('Custom workflow run ID to cancel'),
        reason: z.string().optional().describe('Optional cancellation reason'),
      }),
    }),

    // ===== Auto Pilot Tools =====

    startAutoPilot: tool({
      description: 'Start an Auto Pilot session that autonomously explores a web app, generates requirements, creates test specs, generates and validates Playwright tests, and produces coverage reports. This is a long-running pipeline (10-60 min). Use for broad "test everything" requests.',
      inputSchema: z.object({
        urls: z.array(z.string()).min(1).describe('Entry URLs to explore'),
        instructions: z.string().optional().describe('Optional instructions to guide the pipeline (e.g., focus areas, login credentials)'),
        maxInteractions: z.number().optional().default(50).describe('Max browser interactions during exploration (1-200)'),
        loginUrl: z.string().optional().describe('Optional login URL'),
        username: z.string().optional().describe('Optional login username'),
        password: z.string().optional().describe('Optional login password'),
        strategy: z.string().optional().default('goal_directed').describe('Pipeline exploration strategy'),
        maxDepth: z.number().optional().default(10).describe('Maximum exploration depth'),
        timeoutMinutes: z.number().optional().default(30).describe('Pipeline timeout in minutes'),
        reactiveMode: z.boolean().optional().default(true).describe('Ask checkpoint questions during the run'),
        autoContinueHours: z.number().optional().default(24).describe('Hours before checkpoint auto-continue'),
        priorityThreshold: z.enum(['low', 'medium', 'high', 'critical']).optional().default('low').describe('Minimum requirement priority to generate specs for'),
        maxSpecs: z.number().optional().default(50).describe('Maximum specs to generate'),
        parallelGeneration: z.number().optional().default(2).describe('Parallel test generation workers'),
        hybridHealing: z.boolean().optional().default(false).describe('Use hybrid healing during test generation'),
      }),
    }),

    getAutoPilotStatus: tool({
      description: 'Get the current status of an Auto Pilot session including phase progress, stats, questions, generated spec tasks, and test generation tasks.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID'),
        includeTasks: z.boolean().optional().default(true).describe('Include spec and test task details'),
      }),
      execute: async ({ sessionId, includeTasks }): Promise<ToolResult> => {
        const baseCalls: Promise<ToolResult>[] = [
          fetchTool(`/autopilot/${sessionId}`),
          fetchTool(`/autopilot/${sessionId}/phases`),
          fetchTool(`/autopilot/${sessionId}/questions`),
        ];
        if (includeTasks ?? true) {
          baseCalls.push(fetchTool(`/autopilot/${sessionId}/spec-tasks`));
          baseCalls.push(fetchTool(`/autopilot/${sessionId}/test-tasks`));
        }
        const [session, phases, questions, specTasks, testTasks] = await Promise.all(baseCalls);
        const questionList = Array.isArray(questions) ? questions : [];
        return {
          session,
          phases,
          questions,
          pendingQuestions: questionList.filter((q: any) => q.status === 'pending'),
          specTasks: specTasks || [],
          testTasks: testTasks || [],
        } as ToolResult;
      },
    }),

    pauseAutoPilot: tool({
      description: 'Pause a running Auto Pilot session. The pipeline finishes its current atomic operation and waits.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID to pause'),
      }),
    }),

    resumeAutoPilot: tool({
      description: 'Resume or retry a resumable Auto Pilot session.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID to resume'),
      }),
    }),

    answerAutoPilotQuestion: tool({
      description: 'Answer a checkpoint question from the Auto Pilot pipeline. The pipeline pauses at key decision points and waits for user input before continuing.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID'),
        questionId: z.number().describe('The question ID to answer'),
        answer: z.string().describe('The answer text'),
      }),
    }),

    stopAutoPilotTestTask: tool({
      description: 'Stop an individual test generation task within an Auto Pilot session.',
      inputSchema: z.object({
        sessionId: z.string().describe('The Auto Pilot session ID'),
        taskId: z.number().describe('The Auto Pilot test task ID to stop'),
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
