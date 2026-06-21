export type AssistantArtifactDomain = 'load' | 'database' | 'security' | 'exploration' | 'requirements' | 'specs';

const LOAD_TESTING_TOOLS = new Set([
  'compareLoadTestRuns',
  'getLoadTestResults',
  'listLoadSpecs',
  'getLoadSpec',
  'listLoadScripts',
  'getLoadScript',
  'listLoadTestJobs',
  'getLoadTestJobStatus',
  'getLoadTestJobLogs',
  'getLatestLoadRunsBySpec',
  'getLoadTestRunDetails',
  'getLoadTestTimeseries',
  'getLoadTestingStatus',
  'getLoadTestDashboard',
  'getLoadTestTrends',
  'analyzeLoadTestRun',
  'stopLoadTestRun',
  'forceUnlockLoadTesting',
  'createLoadSpec',
  'updateLoadSpec',
  'deleteLoadSpec',
  'generateLoadScript',
  'runLoadTest',
  'runLoadTestFromSpec',
  'getLoadTestSystemLimits',
]);

const DATABASE_TESTING_TOOLS = new Set([
  'getDatabaseTestSummary',
  'listDatabaseConnections',
  'listDatabaseSpecs',
  'getDatabaseJobStatus',
  'saveGeneratedDatabaseSpec',
  'getDbSchemaAnalysis',
  'getDbChecks',
  'suggestDbFixes',
  'generateDatabaseSpec',
]);

const SECURITY_TESTING_TOOLS = new Set([
  'getSecurityFindings',
  'getSecurityCapabilities',
  'getSecurityTargets',
  'listSecuritySpecs',
  'getSecuritySpec',
  'getSecurityJobStatus',
  'listSecurityFindings',
  'getSecurityRunFindings',
  'getSecurityRunDetails',
  'triggerSecurityScan',
  'runSecurityScan',
  'stopSecurityScan',
  'createSecuritySpec',
  'updateSecuritySpec',
  'deleteSecuritySpec',
  'analyzeSecurityRun',
  'triageSecurityFinding',
  'compareSecurityScans',
  'generateSecuritySpecFromExploration',
]);

const EXPLORATION_TOOLS = new Set([
  'startDiscoveryExploration',
  'startExploration',
  'stopExploration',
  'getExplorationHealth',
  'getExplorationQueueStatus',
  'getExplorationArtifacts',
  'getExplorationResults',
  'getExplorationFlows',
  'getExplorationApis',
  'getExplorationIssues',
  'getExplorerGeneratedSpecs',
  'getExplorerFlowDetails',
  'getExplorerFlowSpecJob',
  'listExplorerSessions',
  'synthesizeExplorerSpecs',
  'analyzeExplorerPrerequisites',
  'generateExplorerFlowSpec',
  'generateExplorerFlowTest',
  'updateExplorerFlow',
  'deleteExplorerFlow',
  'saveExplorerSession',
  'deleteExplorerSession',
  'generateApiSpecsFromExploration',
  'generateApiTestsFromExploration',
]);

const REQUIREMENTS_TOOLS = new Set([
  'getRequirements',
  'generateRequirements',
  'getRequirementDetails',
  'getRequirementStats',
  'getRequirementHealth',
  'listRequirementCategories',
  'findDuplicateRequirements',
  'checkRequirementDuplicate',
  'getRequirementsGenerateJob',
  'getBulkSpecGenerationJob',
  'getRequirementSpecStatus',
  'createRequirement',
  'bulkCreateRequirements',
  'updateRequirement',
  'deleteRequirement',
  'generateSpecFromRequirement',
  'bulkGenerateRequirementSpecs',
  'mergeRequirements',
]);

const SPEC_TOOLS = new Set([
  'createTestSpec',
  'createTestSpecFromAgentReport',
  'updateGeneratedCode',
  'updateSpecMetadata',
  'moveSpec',
  'renameSpec',
  'splitSpec',
  'createSpecFolder',
]);

export interface AssistantArtifactContext {
  projectId?: string;
  jobId?: string;
  runId?: string;
  specName?: string;
  specPath?: string;
  scriptPath?: string;
  findingId?: string;
  sessionId?: string;
  flowId?: string;
  requirementId?: string;
  compareIds?: string[];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number') return String(value);
  return undefined;
}

function firstString(values: unknown[]): string | undefined {
  for (const value of values) {
    const text = stringValue(value);
    if (text) return text;
    if (Array.isArray(value)) {
      const nested = firstString(value);
      if (nested) return nested;
    }
  }
  return undefined;
}

function firstStringArray(values: unknown[]): string[] | undefined {
  for (const value of values) {
    if (Array.isArray(value)) {
      const strings = value.map(stringValue).filter((item): item is string => Boolean(item));
      if (strings.length > 0) return strings;
    }
    const text = stringValue(value);
    if (text?.includes(',')) return text.split(',').map(item => item.trim()).filter(Boolean);
  }
  return undefined;
}

function fileNameFromPath(path?: string): string | undefined {
  if (!path) return undefined;
  const normalized = path.split(/[?#]/)[0];
  const parts = normalized.split('/').filter(Boolean);
  return parts[parts.length - 1] || undefined;
}

function encodeSpecPath(specName: string): string {
  return specName
    .replace(/^specs\//, '')
    .split('/')
    .filter(Boolean)
    .map(segment => encodeURIComponent(segment))
    .join('/');
}

function projectParam(params: URLSearchParams, projectId?: string) {
  if (projectId) params.set('project_id', projectId);
}

export function getAssistantArtifactDomain(toolName: string): AssistantArtifactDomain | undefined {
  if (LOAD_TESTING_TOOLS.has(toolName)) return 'load';
  if (DATABASE_TESTING_TOOLS.has(toolName)) return 'database';
  if (SECURITY_TESTING_TOOLS.has(toolName)) return 'security';
  if (EXPLORATION_TOOLS.has(toolName)) return 'exploration';
  if (REQUIREMENTS_TOOLS.has(toolName)) return 'requirements';
  if (SPEC_TOOLS.has(toolName)) return 'specs';
  return undefined;
}

export function isAssistantArtifactTool(toolName: string): boolean {
  return Boolean(getAssistantArtifactDomain(toolName));
}

export function getAssistantArtifactContext(
  toolName: string,
  result?: unknown,
  args?: Record<string, unknown>,
  fallbackProjectId?: string,
): AssistantArtifactContext {
  if (!isAssistantArtifactTool(toolName)) return {};
  const domain = getAssistantArtifactDomain(toolName);

  const data = asRecord(result);
  const resultData = asRecord(data.result);
  const assistantAction = asRecord(data._assistantAction);
  const actionArgs = asRecord(assistantAction.args);
  const sourceArgs = args || actionArgs;

  const specPath = firstString([
    data.path,
    data.spec_path,
    data.spec_file,
    data.specPath,
    resultData.path,
    resultData.spec_path,
    resultData.spec_file,
    firstStringArray([resultData.spec_files, resultData.spec_paths, resultData.files]),
    sourceArgs.specPath,
  ]);
  const specName = firstString([
    data.spec_name,
    data.specName,
    data.name,
    resultData.spec_name,
    resultData.specName,
    resultData.name,
    firstStringArray([resultData.spec_names, resultData.generated_specs, resultData.specs]),
    sourceArgs.specName,
    fileNameFromPath(specPath),
  ]);
  const scriptPath = firstString([
    data.script_path,
    data.scriptPath,
    data.test_file,
    resultData.script_path,
    resultData.scriptPath,
    resultData.test_file,
    firstStringArray([resultData.script_paths, resultData.test_files]),
    sourceArgs.scriptPath,
    sourceArgs.testPath,
  ]);

  return {
    projectId: firstString([
      assistantAction.projectId,
      data.project_id,
      data.projectId,
      resultData.project_id,
      resultData.projectId,
      sourceArgs._projectId,
      sourceArgs.projectId,
      fallbackProjectId,
    ]),
    jobId: firstString([data.job_id, data.jobId, resultData.job_id, resultData.jobId, sourceArgs.jobId]),
    runId: firstString([data.run_id, data.runId, data.scan_id, resultData.run_id, resultData.runId, resultData.scan_id, sourceArgs.runId]),
    specName,
    specPath,
    scriptPath,
    findingId: domain === 'security'
      ? firstString([data.finding_id, data.findingId, data.id, resultData.finding_id, resultData.findingId, sourceArgs.findingId])
      : firstString([data.finding_id, data.findingId, resultData.finding_id, resultData.findingId, sourceArgs.findingId]),
    sessionId: firstString([
      data.session_id,
      data.sessionId,
      resultData.session_id,
      resultData.sessionId,
      sourceArgs.sessionId,
      sourceArgs.sourceSessionId,
      sourceArgs.exploration_session_id,
    ]),
    flowId: firstString([data.flow_id, data.flowId, resultData.flow_id, resultData.flowId, sourceArgs.flowId]),
    requirementId: domain === 'requirements'
      ? firstString([data.requirement_id, data.requirementId, data.id, resultData.requirement_id, resultData.requirementId, sourceArgs.requirementId])
      : firstString([data.requirement_id, data.requirementId, resultData.requirement_id, resultData.requirementId, sourceArgs.requirementId]),
    compareIds: firstStringArray([sourceArgs.runIds, data.run_ids, resultData.run_ids]),
  };
}

export function buildLoadTestingPageLink(context: AssistantArtifactContext = {}): string {
  const params = new URLSearchParams();
  projectParam(params, context.projectId);
  if (context.jobId) params.set('job_id', context.jobId);
  if (context.compareIds && context.compareIds.length >= 2) {
    params.set('tab', 'history');
    params.set('compare', context.compareIds.slice(0, 2).join(','));
  } else if (context.runId) {
    params.set('tab', 'history');
    params.set('run_id', context.runId);
  } else if (context.scriptPath) {
    params.set('tab', 'scripts');
    params.set('script', context.scriptPath);
  } else if (context.specName) {
    params.set('tab', 'scenarios');
    params.set('spec', context.specName);
  }
  const query = params.toString();
  return query ? `/load-testing?${query}` : '/load-testing';
}

export function buildDatabaseTestingPageLink(context: AssistantArtifactContext = {}, toolName?: string): string {
  const params = new URLSearchParams();
  projectParam(params, context.projectId);
  if (context.jobId) params.set('jobId', context.jobId);
  if (context.specName) {
    params.set('tab', 'specs');
    params.set('specName', context.specName);
  } else if (context.runId && (toolName === 'getDbSchemaAnalysis' || toolName === 'suggestDbFixes')) {
    params.set('tab', 'analyzer');
    params.set('runId', context.runId);
  } else if (context.runId) {
    params.set('tab', 'history');
    params.set('runId', context.runId);
  }
  const query = params.toString();
  return query ? `/database-testing?${query}` : '/database-testing';
}

export function buildSecurityTestingPageLink(context: AssistantArtifactContext = {}, toolName?: string): string {
  const params = new URLSearchParams();
  projectParam(params, context.projectId);
  if (context.jobId) params.set('jobId', context.jobId);
  if (context.specName) {
    params.set('tab', 'specs');
    params.set('specName', context.specName);
  } else if (context.findingId) {
    params.set('tab', 'findings');
    params.set('findingId', context.findingId);
    if (context.runId) params.set('runId', context.runId);
  } else if (context.runId && (toolName === 'getSecurityRunFindings' || toolName === 'listSecurityFindings' || toolName === 'analyzeSecurityRun')) {
    params.set('tab', 'findings');
    params.set('runId', context.runId);
  } else if (context.jobId || toolName === 'triggerSecurityScan' || toolName === 'runSecurityScan') {
    params.set('tab', 'scanner');
    if (context.runId) params.set('runId', context.runId);
  } else if (context.runId) {
    params.set('tab', 'history');
    params.set('runId', context.runId);
  }
  const query = params.toString();
  return query ? `/security-testing?${query}` : '/security-testing';
}

export function buildExplorationPageLink(context: AssistantArtifactContext = {}): string {
  const params = new URLSearchParams();
  projectParam(params, context.projectId);
  if (context.runId) {
    params.set('tab', 'explorer');
    params.set('runId', context.runId);
    if (context.flowId) params.set('flowId', context.flowId);
    if (context.jobId) params.set('jobId', context.jobId);
  } else {
    params.set('tab', 'sessions');
    if (context.sessionId) params.set('sessionId', context.sessionId);
    if (context.jobId) params.set('jobId', context.jobId);
  }
  const query = params.toString();
  return query ? `/exploration?${query}` : '/exploration';
}

export function buildRequirementsPageLink(context: AssistantArtifactContext = {}, toolName?: string): string {
  if ((toolName === 'generateSpecFromRequirement' || toolName === 'bulkGenerateRequirementSpecs') && (context.specName || context.specPath)) {
    return buildSpecPageLink(context, true);
  }

  const params = new URLSearchParams();
  projectParam(params, context.projectId);
  if (context.jobId) params.set('jobId', context.jobId);
  if (context.sessionId) params.set('sourceSessionId', context.sessionId);
  if (context.requirementId) params.set('requirementId', context.requirementId);
  const query = params.toString();
  return query ? `/requirements?${query}` : '/requirements';
}

export function buildSpecPageLink(context: AssistantArtifactContext = {}, generated = false): string {
  const specName = context.specPath?.replace(/^specs\//, '') || context.specName || fileNameFromPath(context.specPath);
  if (!specName) return '/specs';
  const query = new URLSearchParams();
  projectParam(query, context.projectId);
  if (generated) query.set('tab', 'generated');
  const queryString = query.toString();
  return `/specs/${encodeSpecPath(specName)}${queryString ? `?${queryString}` : ''}`;
}

export function buildAssistantArtifactPageLink(toolName: string, context: AssistantArtifactContext = {}): string | undefined {
  const domain = getAssistantArtifactDomain(toolName);
  if (domain === 'load') return buildLoadTestingPageLink(context);
  if (domain === 'database') return buildDatabaseTestingPageLink(context, toolName);
  if (domain === 'security') return buildSecurityTestingPageLink(context, toolName);
  if (domain === 'exploration') return buildExplorationPageLink(context);
  if (domain === 'requirements') return buildRequirementsPageLink(context, toolName);
  if (domain === 'specs') return buildSpecPageLink(context, toolName === 'updateGeneratedCode');
  return undefined;
}

export function buildAssistantArtifactPageLinkForTool(
  toolName: string,
  result?: unknown,
  args?: Record<string, unknown>,
  fallbackProjectId?: string,
): string | undefined {
  const context = getAssistantArtifactContext(toolName, result, args, fallbackProjectId);
  return buildAssistantArtifactPageLink(toolName, context);
}
