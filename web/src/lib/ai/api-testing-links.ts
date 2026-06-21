const API_TESTING_TOOLS = new Set([
  'createApiSpec',
  'createAndGenerateApiTest',
  'generateApiTest',
  'importOpenApiSpec',
  'updateApiSpec',
  'deleteApiSpec',
  'runApiTest',
  'runApiTestDirect',
  'generateApiEdgeCases',
  'getApiJobStatus',
  'getApiSpec',
  'listApiSpecs',
  'getApiTestRuns',
]);

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

function firstStringFromArray(value: unknown): string | undefined {
  return Array.isArray(value) ? firstString(value) : undefined;
}

function fileNameFromPath(path?: string): string | undefined {
  if (!path) return undefined;
  const normalized = path.split(/[?#]/)[0];
  const parts = normalized.split('/').filter(Boolean);
  return parts[parts.length - 1] || undefined;
}

export interface ApiTestingArtifactContext {
  projectId?: string;
  specName?: string;
  specPath?: string;
  testPath?: string;
  jobId?: string;
}

export function isApiTestingTool(toolName: string): boolean {
  return API_TESTING_TOOLS.has(toolName);
}

export function getApiTestingArtifactContext(
  toolName: string,
  result?: unknown,
  args?: Record<string, unknown>,
  fallbackProjectId?: string,
): ApiTestingArtifactContext {
  if (!isApiTestingTool(toolName)) return {};

  const data = asRecord(result);
  const resultData = asRecord(data.result);
  const assistantAction = asRecord(data._assistantAction);
  const actionArgs = asRecord(assistantAction.args);
  const sourceArgs = args || actionArgs;
  const specPath = firstString([
    data.path,
    data.spec_path,
    resultData.spec_path,
    firstStringFromArray(resultData.spec_paths),
    sourceArgs.specPath,
  ]);
  const specName = firstString([
    data.name,
    data.spec_name,
    resultData.spec_name,
    sourceArgs.specName,
    fileNameFromPath(specPath),
  ]);
  const testPath = firstString([
    data.test_path,
    data.generated_test_path,
    resultData.test_path,
    firstStringFromArray(resultData.test_paths),
    firstStringFromArray(resultData.files),
    sourceArgs.testPath,
  ]);

  return {
    projectId: firstString([
      assistantAction.projectId,
      data.project_id,
      resultData.project_id,
      sourceArgs._projectId,
      sourceArgs.projectId,
      fallbackProjectId,
    ]),
    specName,
    specPath,
    testPath,
    jobId: firstString([data.job_id, data.jobId, resultData.job_id, sourceArgs.jobId]),
  };
}

export function buildApiTestingPageLink(context: ApiTestingArtifactContext = {}): string {
  const params = new URLSearchParams();
  if (context.projectId) params.set('project_id', context.projectId);
  if (context.specName) {
    params.set('tab', 'specs');
    params.set('spec', context.specName);
  } else if (context.testPath) {
    params.set('tab', 'generated');
    params.set('test', fileNameFromPath(context.testPath) || context.testPath);
  }
  if (context.jobId) params.set('job_id', context.jobId);
  const query = params.toString();
  return query ? `/api-testing?${query}` : '/api-testing';
}

export function buildApiTestingPageLinkForTool(
  toolName: string,
  result?: unknown,
  args?: Record<string, unknown>,
  fallbackProjectId?: string,
): string | undefined {
  if (!isApiTestingTool(toolName)) return undefined;
  return buildApiTestingPageLink(getApiTestingArtifactContext(toolName, result, args, fallbackProjectId));
}
