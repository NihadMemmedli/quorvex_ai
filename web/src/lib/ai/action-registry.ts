import crypto from 'crypto';

export type AssistantActionRisk = 'low' | 'medium' | 'high' | 'destructive';
export type AssistantProjectRole = 'viewer' | 'editor' | 'admin';

export interface AssistantActionConfig {
  label: string;
  method: string;
  risk: AssistantActionRisk;
  requiredRole: AssistantProjectRole;
  confirmationRequired: boolean;
  getPath: (args: Record<string, unknown>, projectId?: string) => string;
  getBody?: (args: Record<string, unknown>, projectId?: string) => Record<string, unknown> | undefined;
}

export const ASSISTANT_ACTION_CONFIGS: Record<string, AssistantActionConfig> = {
  runTestSpec: {
    label: 'Run Test Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid }),
  },
  startDiscoveryExploration: {
    label: 'Start Discovery Exploration',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/exploration/start',
    getBody: (args, pid) => ({
      entry_url: args.url,
      project_id: pid || 'default',
      strategy: args.strategy || 'goal_directed',
      max_interactions: args.maxInteractions ?? 50,
      max_depth: args.maxDepth ?? 10,
      timeout_minutes: args.timeoutMinutes ?? 30,
      login_url: args.loginUrl || undefined,
      credentials: buildCredentials(args),
      exclude_patterns: args.excludePatterns || [],
      focus_areas: args.focusAreas || [],
      additional_instructions: args.instructions || undefined,
    }),
  },
  startExploration: {
    label: 'Start Exploration',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/exploration/start',
    getBody: (args, pid) => ({
      entry_url: args.url,
      project_id: pid || 'default',
      strategy: args.strategy || 'goal_directed',
      max_interactions: args.maxInteractions ?? 50,
      max_depth: args.maxDepth ?? 10,
      timeout_minutes: args.timeoutMinutes ?? 30,
      login_url: args.loginUrl || undefined,
      credentials: buildCredentials(args),
      exclude_patterns: args.excludePatterns || [],
      focus_areas: args.focusAreas || [],
      additional_instructions: args.instructions || undefined,
    }),
  },
  startExplorerAgent: {
    label: 'Start Explorer Agent',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/agents/exploratory',
    getBody: (args, pid) => ({
      url: args.url,
      time_limit_minutes: args.timeLimitMinutes ?? 15,
      instructions: args.instructions || '',
      auth: buildExplorerAuth(args),
      test_data: args.testData || undefined,
      focus_areas: args.focusAreas || undefined,
      excluded_patterns: args.excludedPatterns || undefined,
      project_id: pid || 'default',
    }),
  },
  startAdhocCustomAgent: {
    label: 'Start Custom Agent',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/agents/definitions',
    getBody: (args, pid) => ({
      name: `Ad-hoc QA Agent - ${hostnameLabel(String(args.url || 'website'))}`,
      description: `Chat-created custom QA agent for ${args.url || 'the requested website'}.`,
      system_prompt: ADHOC_CUSTOM_AGENT_SYSTEM_PROMPT,
      timeout_seconds: clampTimeoutSeconds(args.timeoutSeconds),
      tool_ids: ADHOC_CUSTOM_AGENT_TOOL_IDS,
      project_id: pid || 'default',
    }),
  },
  startCustomAgentFromReport: {
    label: 'Start Custom Agent From Report',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/api/agents/definitions/${encodeURIComponent(String(args.definitionId))}/runs`,
    getBody: (args, pid) => ({
      prompt: args.prompt,
      url: args.url || undefined,
      project_id: pid || 'default',
      config: {
        source_run_id: args.sourceRunId,
        source_item_id: args.sourceItemId,
      },
    }),
  },
  stopExploration: {
    label: 'Stop Exploration',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/exploration/${args.sessionId}/stop?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  generateRequirements: {
    label: 'Generate Requirements',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/requirements/generate?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({ exploration_session_id: args.sessionId }),
  },
  createTestSpec: {
    label: 'Create Test Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/specs',
    getBody: (args, pid) => ({ name: args.specName, content: args.content, project_id: pid }),
  },
  createTestSpecFromAgentReport: {
    label: 'Create Test Spec From Agent Report',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/specs',
    getBody: (args, pid) => ({
      name: args.specName,
      content: args.content,
      project_id: pid,
    }),
  },
  updateTestSpec: {
    label: 'Update Test Spec',
    method: 'PUT',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/specs/${encodeURIComponent(String(args.specName))}`,
    getBody: (args) => ({ content: args.content, reason: args.reason }),
  },
  runRegressionBatch: {
    label: 'Run Regression Batch',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs/bulk',
    getBody: (args, pid) => ({ spec_names: args.specNames, project_id: pid }),
  },
  stopRun: {
    label: 'Stop Test Run',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/runs/${args.runId}/stop${pid ? `?project_id=${encodeURIComponent(pid)}` : ''}`,
  },
  stopAllJobs: {
    label: 'Stop All Jobs',
    method: 'POST',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: () => '/stop-all',
  },
  clearQueue: {
    label: 'Clear Queue',
    method: 'POST',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: () => '/queue/clear',
    getBody: (args) => ({
      include_queued: args.includeQueued ?? true,
      include_running: args.includeRunning ?? true,
    }),
  },
  triggerSecurityScan: {
    label: 'Trigger Security Scan',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/security-testing/scan/quick',
    getBody: (args, pid) => ({ target_url: args.url, project_id: pid }),
  },
  retryFailedRun: {
    label: 'Retry Failed Run',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid }),
  },
  healFailedRun: {
    label: 'Heal Failed Run',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid, hybrid_mode: args.useHybridHealing }),
  },
  triggerScheduleNow: {
    label: 'Trigger Schedule Now',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/scheduling/${encodeURIComponent(pid || 'default')}/schedules/${args.scheduleId}/run-now`,
  },
  rerunFailedTests: {
    label: 'Rerun Failed Tests',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/regression/batches/${args.batchId}/rerun-failed`,
  },
  analyzeLoadTestRun: {
    label: 'Analyze Load Test Run',
    method: 'POST',
    risk: 'low',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/load-testing/runs/${args.runId}/analyze`,
  },
  stopLoadTestRun: {
    label: 'Stop Load Test Run',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/load-testing/runs/${args.runId}/stop`,
  },
  forceUnlockLoadTesting: {
    label: 'Force Unlock Load Testing',
    method: 'POST',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: () => '/load-testing/force-unlock',
  },
  createLoadSpec: {
    label: 'Create Load Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/load-testing/specs',
    getBody: (args, pid) => ({ name: args.specName, content: args.content, project_id: pid || 'default' }),
  },
  updateLoadSpec: {
    label: 'Update Load Spec',
    method: 'PUT',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/load-testing/specs/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({ content: args.content }),
  },
  deleteLoadSpec: {
    label: 'Delete Load Spec',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args, pid) => `/load-testing/specs/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  generateLoadScript: {
    label: 'Generate Load Script',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/load-testing/generate',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid || 'default' }),
  },
  runLoadTest: {
    label: 'Run Load Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/load-testing/run',
    getBody: (args, pid) => ({
      script_path: args.scriptPath,
      spec_name: args.specName || undefined,
      vus: args.vus,
      duration: args.duration,
      project_id: pid || 'default',
    }),
  },
  runLoadTestFromSpec: {
    label: 'Run Load Test From Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/load-testing/run-from-spec',
    getBody: (args, pid) => ({
      spec_name: args.specName,
      vus: args.vus,
      duration: args.duration,
      project_id: pid || 'default',
    }),
  },
  analyzeSecurityRun: {
    label: 'Analyze Security Run',
    method: 'POST',
    risk: 'low',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/security-testing/analyze/${args.runId}`,
  },
  triageSecurityFinding: {
    label: 'Triage Security Finding',
    method: 'PATCH',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/security-testing/findings/${args.findingId}/status`,
    getBody: (args) => ({ status: args.status, notes: args.notes }),
  },
  suggestLlmSpecImprovements: {
    label: 'Suggest LLM Spec Improvements',
    method: 'POST',
    risk: 'low',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/llm-testing/specs/${encodeURIComponent(String(args.specName))}/suggest-improvements`,
  },
  suggestDbFixes: {
    label: 'Suggest DB Fixes',
    method: 'POST',
    risk: 'low',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/database-testing/suggest/${args.runId}`,
  },
  generateDatabaseSpec: {
    label: 'Generate Database Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/database-testing/generate-spec',
    getBody: (args, pid) => ({
      connection_id: args.connectionId,
      instructions: args.instructions,
      spec_name: args.specName || undefined,
      auto_run: false,
      preview_only: args.previewOnly ?? true,
      project_id: pid || args.projectId || 'default',
    }),
  },
  saveGeneratedDatabaseSpec: {
    label: 'Save Generated Database Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/database-testing/generated-specs/save',
    getBody: (args, pid) => ({
      checks: args.checks,
      spec_name: args.specName || undefined,
      project_id: pid || args.projectId || 'default',
    }),
  },
  createApiSpec: {
    label: 'Create API Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/specs',
    getBody: (args, pid) => ({ name: args.specName, content: args.content, project_id: pid || 'default' }),
  },
  updateApiSpec: {
    label: 'Update API Spec',
    method: 'PUT',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/api-testing/specs/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({ content: args.content }),
  },
  deleteApiSpec: {
    label: 'Delete API Spec',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args, pid) => `/api-testing/specs/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  createAndGenerateApiTest: {
    label: 'Create and Generate API Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/create-and-generate',
    getBody: (args, pid) => ({ name: args.specName, content: args.content, project_id: pid || 'default' }),
  },
  importOpenApiSpec: {
    label: 'Import OpenAPI Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/import-openapi',
    getBody: (args, pid) => ({ url: args.url, feature_filter: args.featureFilter || undefined, project_id: pid || 'default' }),
  },
  generateApiTest: {
    label: 'Generate API Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/generate',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid || 'default' }),
  },
  runApiTest: {
    label: 'Run API Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/run',
    getBody: (args, pid) => ({ spec_path: args.specPath, project_id: pid || 'default' }),
  },
  runApiTestDirect: {
    label: 'Run Generated API Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/run-direct',
    getBody: (args, pid) => ({ test_path: args.testPath, spec_name: args.specName, project_id: pid || 'default' }),
  },
  generateApiEdgeCases: {
    label: 'Generate API Edge Cases',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api-testing/edge-cases',
    getBody: (args, pid) => ({ spec_path: args.specPath, project_id: pid || 'default' }),
  },
  startAutoPilot: {
    label: 'Start Auto Pilot',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/autopilot/start',
    getBody: (args, pid) => ({
      entry_urls: args.urls,
      project_id: pid || 'default',
      login_url: args.loginUrl || undefined,
      credentials: buildCredentials(args),
      instructions: args.instructions || undefined,
      strategy: args.strategy || 'goal_directed',
      max_interactions: args.maxInteractions ?? 50,
      max_depth: args.maxDepth ?? 10,
      timeout_minutes: args.timeoutMinutes ?? 30,
      reactive_mode: args.reactiveMode ?? true,
      auto_continue_hours: args.autoContinueHours ?? 24,
      priority_threshold: args.priorityThreshold || 'low',
      max_specs: args.maxSpecs ?? 50,
      parallel_generation: args.parallelGeneration ?? 2,
      hybrid_healing: args.hybridHealing ?? false,
    }),
  },
  pauseAutoPilot: {
    label: 'Pause Auto Pilot',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${args.sessionId}/pause`,
  },
  resumeAutoPilot: {
    label: 'Resume Auto Pilot',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${args.sessionId}/resume`,
  },
  answerAutoPilotQuestion: {
    label: 'Answer Auto Pilot Question',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${args.sessionId}/answer`,
    getBody: (args) => ({
      question_id: args.questionId,
      answer_text: args.answer,
    }),
  },
  stopAutoPilotTestTask: {
    label: 'Stop Auto Pilot Test Task',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${args.sessionId}/test-tasks/${args.taskId}/stop`,
  },
  cancelAutoPilot: {
    label: 'Cancel Auto Pilot',
    method: 'POST',
    risk: 'destructive',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${args.sessionId}/cancel`,
  },
};

export const ADHOC_CUSTOM_AGENT_TOOL_IDS = [
  'browser_navigate',
  'browser_snapshot',
  'browser_click',
  'browser_type',
  'browser_select',
  'browser_press_key',
  'browser_hover',
  'browser_network',
  'browser_console',
  'browser_screenshot',
  'browser_wait',
  'browser_navigate_back',
  'browser_close',
];

export const ADHOC_CUSTOM_AGENT_SYSTEM_PROMPT = [
  'You are a focused QA automation agent.',
  'Inspect the target website using the granted browser tools and gather practical test ideas from observed behavior.',
  'Prefer public unauthenticated paths unless credentials are explicitly provided in the task.',
  'Report concise findings, pages checked, test ideas, evidence, and follow-up actions.',
  'Do not modify external data unless the user explicitly requested that action.',
].join(' ');

const TOKEN_TTL_MS = 10 * 60 * 1000;
const redeemedActionIds = new Set<string>();

interface PendingActionPayload {
  id: string;
  toolName: string;
  args: Record<string, unknown>;
  projectId?: string;
  authFingerprint: string;
  expiresAt: number;
}

export function getAssistantActionConfig(toolName: string): AssistantActionConfig | undefined {
  return ASSISTANT_ACTION_CONFIGS[toolName];
}

export function createPendingActionToken(input: {
  toolName: string;
  args: Record<string, unknown>;
  projectId?: string;
  authToken?: string;
}): string {
  const config = getAssistantActionConfig(input.toolName);
  if (!config) throw new Error(`Unknown assistant action: ${input.toolName}`);

  const payload: PendingActionPayload = {
    id: crypto.randomUUID(),
    toolName: input.toolName,
    args: input.args || {},
    projectId: input.projectId,
    authFingerprint: fingerprintAuth(input.authToken),
    expiresAt: Date.now() + TOKEN_TTL_MS,
  };
  return signPayload(payload);
}

export function verifyPendingActionToken(token: string, authToken?: string): PendingActionPayload {
  const payload = verifySignedPayload(token);
  if (payload.expiresAt < Date.now()) throw new Error('Approval token expired');
  if (payload.authFingerprint !== fingerprintAuth(authToken)) {
    throw new Error('Approval token does not match the current user session');
  }
  if (redeemedActionIds.has(payload.id)) throw new Error('Approval token already used');
  if (!getAssistantActionConfig(payload.toolName)) throw new Error(`Unknown assistant action: ${payload.toolName}`);
  return payload;
}

export function markPendingActionRedeemed(id: string) {
  redeemedActionIds.add(id);
  if (redeemedActionIds.size > 1000) {
    const [first] = redeemedActionIds;
    if (first) redeemedActionIds.delete(first);
  }
}

export function redactAssistantActionArgs(args: Record<string, unknown>): Record<string, unknown> {
  const redacted: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(args || {})) {
    if (/password|token|secret|credential/i.test(key)) {
      redacted[key] = value ? '[redacted]' : value;
    } else if (key === 'credentials' && value && typeof value === 'object') {
      redacted[key] = '[redacted]';
    } else if (typeof value === 'string' && value.length > 500) {
      redacted[key] = `${value.slice(0, 500)}...`;
    } else {
      redacted[key] = value;
    }
  }
  return redacted;
}

function buildCredentials(args: Record<string, unknown>) {
  if (args.credentials && typeof args.credentials === 'object') return args.credentials as Record<string, unknown>;
  if (args.username || args.password) {
    return { username: args.username, password: args.password };
  }
  return undefined;
}

export function buildAdhocCustomAgentRunBody(args: Record<string, unknown>, projectId?: string) {
  const focusAreas = Array.isArray(args.focusAreas)
    ? args.focusAreas.filter((area): area is string => typeof area === 'string' && area.trim().length > 0)
    : [];
  const url = typeof args.url === 'string' ? args.url : '';
  const prompt = typeof args.prompt === 'string' && args.prompt.trim()
    ? args.prompt.trim()
    : `Inspect ${url || 'the target website'} and report useful QA test ideas.`;

  return {
    prompt,
    url: url || undefined,
    project_id: projectId || 'default',
    config: {
      source: 'chat_adhoc_custom_agent',
      focus_areas: focusAreas.length > 0 ? focusAreas : undefined,
    },
  };
}

function clampTimeoutSeconds(value: unknown) {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return 1800;
  return Math.max(60, Math.min(Math.floor(parsed), 7200));
}

function hostnameLabel(rawUrl: string) {
  try {
    return new URL(rawUrl).hostname.replace(/^www\./, '').slice(0, 48) || 'website';
  } catch {
    return 'website';
  }
}

function buildExplorerAuth(args: Record<string, unknown>) {
  if (args.auth && typeof args.auth === 'object') return args.auth as Record<string, unknown>;
  if (args.sessionId) {
    return { type: 'session', session_id: args.sessionId };
  }
  if (args.username || args.password || args.loginUrl) {
    return {
      type: 'credentials',
      credentials: {
        username: args.username,
        password: args.password,
      },
      login_url: args.loginUrl,
    };
  }
  return null;
}

function fingerprintAuth(authToken?: string) {
  if (!authToken) return 'anonymous';
  return crypto.createHash('sha256').update(authToken).digest('hex');
}

function getSecret() {
  return (
    process.env.ASSISTANT_ACTION_SECRET ||
    process.env.NEXTAUTH_SECRET ||
    process.env.AUTH_SECRET ||
    process.env.ANTHROPIC_AUTH_TOKEN ||
    'quorvex-assistant-action-dev-secret'
  );
}

function signPayload(payload: PendingActionPayload) {
  const body = Buffer.from(JSON.stringify(payload), 'utf8').toString('base64url');
  const sig = crypto.createHmac('sha256', getSecret()).update(body).digest('base64url');
  return `${body}.${sig}`;
}

function verifySignedPayload(token: string): PendingActionPayload {
  const [body, sig] = token.split('.');
  if (!body || !sig) throw new Error('Invalid approval token');
  const expected = crypto.createHmac('sha256', getSecret()).update(body).digest('base64url');
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) {
    throw new Error('Invalid approval token signature');
  }
  return JSON.parse(Buffer.from(body, 'base64url').toString('utf8')) as PendingActionPayload;
}
