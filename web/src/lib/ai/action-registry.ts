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
  getBody?: (args: Record<string, unknown>, projectId?: string) => unknown;
}

export const ASSISTANT_ACTION_CONFIGS: Record<string, AssistantActionConfig> = {
  runTestSpec: {
    label: 'Run Test Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid, ...buildBrowserAuthControls(args) }),
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
      ...buildBrowserAuthControls(args),
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
      ...buildBrowserAuthControls(args),
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
      ...buildBrowserAuthControls(args),
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
      name: customAgentName(args),
      description: customAgentDescription(args),
      system_prompt: customAgentSystemPrompt(args),
      timeout_seconds: clampTimeoutSeconds(args.timeoutSeconds),
      tool_ids: customAgentToolIds(args),
      runtime: typeof args.runtime === 'string' ? args.runtime : undefined,
      model: typeof args.model === 'string' && args.model.trim() ? args.model.trim() : undefined,
      project_id: pid || 'default',
    }),
  },
  startCodingAgent: {
    label: 'Start Coding Agent',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/agents/runs',
    getBody: (args, pid) => buildCodingAgentRunBody(args, pid),
  },
  createCustomAgentDefinition: {
    label: 'Save Custom Agent',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/agents/definitions',
    getBody: (args, pid) => ({
      name: customAgentName(args),
      description: customAgentDescription(args),
      system_prompt: customAgentDefinitionSystemPrompt(args),
      timeout_seconds: clampTimeoutSeconds(args.timeoutSeconds),
      tool_ids: customAgentToolIds(args),
      runtime: typeof args.runtime === 'string' ? args.runtime : undefined,
      model: typeof args.model === 'string' && args.model.trim() ? args.model.trim() : undefined,
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
      runtime: typeof args.runtime === 'string' ? args.runtime : undefined,
      project_id: pid || 'default',
      config: {
        source_run_id: args.sourceRunId,
        source_item_id: args.sourceItemId,
      },
    }),
  },
  synthesizeExplorerSpecs: {
    label: 'Synthesize Explorer Specs',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/api/agents/exploratory/${encodeURIComponent(String(args.runId))}/synthesize`,
  },
  analyzeExplorerPrerequisites: {
    label: 'Analyze Explorer Prerequisites',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => {
      const params = new URLSearchParams({ project_id: pid || 'default' });
      if (args.forceReanalyze !== undefined) params.set('force_reanalyze', String(args.forceReanalyze));
      return `/api/agents/exploratory/${encodeURIComponent(String(args.runId))}/analyze-prerequisites?${params}`;
    },
  },
  generateExplorerFlowSpec: {
    label: 'Generate Explorer Flow Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => {
      const params = new URLSearchParams({ project_id: pid || 'default' });
      if (args.forceRegenerate !== undefined) params.set('force_regenerate', String(args.forceRegenerate));
      return `/api/agents/exploratory/${encodeURIComponent(String(args.runId))}/flows/${encodeURIComponent(String(args.flowId))}/spec?${params}`;
    },
  },
  generateExplorerFlowTest: {
    label: 'Generate Explorer Flow Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => {
      const params = new URLSearchParams({ project_id: pid || 'default' });
      if (args.forceRegenerate !== undefined) params.set('force_regenerate', String(args.forceRegenerate));
      return `/api/agents/exploratory/${encodeURIComponent(String(args.runId))}/flows/${encodeURIComponent(String(args.flowId))}/generate?${params}`;
    },
    getBody: (args) => buildBrowserAuthControls(args),
  },
  updateExplorerFlow: {
    label: 'Update Explorer Flow',
    method: 'PUT',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/api/agents/exploratory/${encodeURIComponent(String(args.runId))}/flows/${encodeURIComponent(String(args.flowId))}?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => args.updates || {},
  },
  deleteExplorerFlow: {
    label: 'Delete Explorer Flow',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/api/agents/exploratory/${encodeURIComponent(String(args.runId))}/flows/${encodeURIComponent(String(args.flowId))}?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  saveExplorerSession: {
    label: 'Save Explorer Session',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/api/agents/sessions/${encodeURIComponent(String(args.sessionId))}`,
    getBody: (args) => ({
      cookies: args.cookies || [],
      storage: args.storage || {},
    }),
  },
  deleteExplorerSession: {
    label: 'Delete Explorer Session',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/api/agents/sessions/${encodeURIComponent(String(args.sessionId))}`,
  },
  stopExploration: {
    label: 'Stop Exploration',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/exploration/${args.sessionId}/stop?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  generateApiSpecsFromExploration: {
    label: 'Generate API Specs From Exploration',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/exploration/${encodeURIComponent(String(args.sessionId))}/generate-api-specs?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  generateApiTestsFromExploration: {
    label: 'Generate API Tests From Exploration',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/exploration/${encodeURIComponent(String(args.sessionId))}/generate-api-tests?project_id=${encodeURIComponent(pid || 'default')}`,
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
  createRequirement: {
    label: 'Create Requirement',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/requirements?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => requirementBody(args),
  },
  bulkCreateRequirements: {
    label: 'Bulk Create Requirements',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/requirements/bulk?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      items: Array.isArray(args.items) ? args.items.map((item) => requirementBody(item as Record<string, unknown>)) : [],
    }),
  },
  updateRequirement: {
    label: 'Update Requirement',
    method: 'PUT',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/requirements/${args.requirementId}?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => requirementBody(args, true),
  },
  deleteRequirement: {
    label: 'Delete Requirement',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args, pid) => `/requirements/${args.requirementId}?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  generateSpecFromRequirement: {
    label: 'Generate Spec From Requirement',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/requirements/${args.requirementId}/generate-spec?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      target_url: args.targetUrl,
      login_url: args.loginUrl || undefined,
      credentials: args.credentials || undefined,
      ...buildBrowserAuthControls(args),
      test_data_refs: Array.isArray(args.testDataRefs)
        ? args.testDataRefs
        : (Array.isArray(args.test_data_refs) ? args.test_data_refs : undefined),
      force_regenerate: args.forceRegenerate ?? false,
    }),
  },
  bulkGenerateRequirementSpecs: {
    label: 'Bulk Generate Requirement Specs',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/requirements/bulk-generate-specs?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      target_url: args.targetUrl,
      login_url: args.loginUrl || undefined,
      credentials: args.credentials || undefined,
    }),
  },
  mergeRequirements: {
    label: 'Merge Requirements',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/requirements/merge?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      canonical_id: args.canonicalId,
      duplicate_ids: args.duplicateIds,
      merge_acceptance_criteria: args.mergeAcceptanceCriteria ?? true,
    }),
  },
  generateRTM: {
    label: 'Generate RTM',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/rtm/generate?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      specs_paths: args.specsPaths || undefined,
      use_ai_matching: args.useAiMatching ?? true,
    }),
  },
  createRTMSnapshot: {
    label: 'Create RTM Snapshot',
    method: 'POST',
    risk: 'low',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => {
      const params = new URLSearchParams({ project_id: pid || 'default' });
      if (args.name) params.set('name', String(args.name));
      return `/rtm/snapshot?${params}`;
    },
  },
  createRTMEntry: {
    label: 'Create RTM Entry',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/rtm/entry?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      requirement_id: args.requirementId,
      test_spec_name: args.testSpecName,
      test_spec_path: args.testSpecPath || undefined,
      mapping_type: args.mappingType || 'full',
      confidence: args.confidence ?? 1,
      coverage_notes: args.coverageNotes || undefined,
    }),
  },
  deleteRTMEntry: {
    label: 'Delete RTM Entry',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/rtm/entry/${args.entryId}?project_id=${encodeURIComponent(pid || 'default')}`,
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
  updateGeneratedCode: {
    label: 'Update Generated Code',
    method: 'PUT',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/specs/${encodeURIComponent(String(args.specName))}/generated-code`,
    getBody: (args) => ({ content: args.code }),
  },
  updateSpecMetadata: {
    label: 'Update Spec Metadata',
    method: 'PUT',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/spec-metadata/${encodeURIComponent(String(args.specName))}`,
    getBody: (args, pid) => ({
      tags: args.tags || undefined,
      description: args.description || undefined,
      author: args.author || undefined,
      project_id: args.projectId || pid || undefined,
    }),
  },
  moveSpec: {
    label: 'Move Spec',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/specs/move',
    getBody: (args, pid) => ({
      source_path: args.sourcePath,
      destination_folder: args.destinationFolder || '',
      is_folder: args.isFolder ?? false,
      project_id: pid || 'default',
    }),
  },
  renameSpec: {
    label: 'Rename Spec',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/specs/rename',
    getBody: (args, pid) => ({
      old_path: args.oldPath,
      new_name: args.newName,
      is_folder: args.isFolder ?? false,
      project_id: pid || 'default',
    }),
  },
  splitSpec: {
    label: 'Split Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/specs/split-jobs',
    getBody: (args, pid) => ({
      spec_name: args.specName,
      output_dir: args.outputDir || undefined,
      project_id: pid || 'default',
      mode: args.mode || 'individual',
    }),
  },
  createSpecFolder: {
    label: 'Create Spec Folder',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/specs/create-folder',
    getBody: (args, pid) => ({
      folder_name: args.folderName,
      parent_path: args.parentPath || '',
      project_id: pid || 'default',
    }),
  },
  runRegressionBatch: {
    label: 'Run Regression Batch',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs/bulk',
    getBody: (args, pid) => ({ spec_names: args.specNames, project_id: pid, ...buildBrowserAuthControls(args) }),
  },
  executeUiTestCoveragePlan: {
    label: 'Execute UI Test Coverage Plan',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs/bulk',
    getBody: (args, pid) => ({
      spec_names: args.specNames,
      project_id: pid,
      reason: args.reason || undefined,
      ...buildBrowserAuthControls(args),
    }),
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
  quarantineSpec: {
    label: 'Quarantine Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => {
      const params = new URLSearchParams({ project_id: pid || 'default' });
      if (args.reason) params.set('reason', String(args.reason));
      return `/analytics/quarantine/${encodeURIComponent(String(args.specName))}?${params}`;
    },
  },
  unquarantineSpec: {
    label: 'Unquarantine Spec',
    method: 'DELETE',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/analytics/quarantine/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
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
  runSecurityScan: {
    label: 'Run Security Scan',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/security-testing/scan/${args.scanType || 'quick'}`,
    getBody: (args, pid) => securityScanBody(args, pid),
  },
  stopSecurityScan: {
    label: 'Stop Security Scan',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/security-testing/runs/${encodeURIComponent(String(args.runId))}/stop?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  createSecuritySpec: {
    label: 'Create Security Spec',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/security-testing/specs',
    getBody: (args, pid) => ({ name: args.specName, content: args.content, project_id: pid || 'default' }),
  },
  updateSecuritySpec: {
    label: 'Update Security Spec',
    method: 'PUT',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/security-testing/specs/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({ content: args.content }),
  },
  deleteSecuritySpec: {
    label: 'Delete Security Spec',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args, pid) => `/security-testing/specs/${encodeURIComponent(String(args.specName))}?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  generateSecuritySpecFromExploration: {
    label: 'Generate Security Spec From Exploration',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/security-testing/generate-spec',
    getBody: (args, pid) => ({
      session_id: args.sessionId,
      project_id: pid || 'default',
    }),
  },
  retryFailedRun: {
    label: 'Retry Failed Run',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs',
    getBody: (args, pid) => ({ spec_name: args.specName, project_id: pid, ...buildBrowserAuthControls(args) }),
  },
  healFailedRun: {
    label: 'Heal Failed Run',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/runs',
    getBody: (args, pid) => ({
      spec_name: args.specName,
      project_id: pid,
      hybrid: args.useHybridHealing,
      ...buildBrowserAuthControls(args),
    }),
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
  refreshRegressionBatch: {
    label: 'Refresh Regression Batch',
    method: 'PATCH',
    risk: 'low',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/regression/batches/${encodeURIComponent(String(args.batchId))}/refresh`,
  },
  cancelRegressionBatch: {
    label: 'Cancel Regression Batch',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/regression/batches/${encodeURIComponent(String(args.batchId))}/cancel?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  renameRegressionBatch: {
    label: 'Rename Regression Batch',
    method: 'PATCH',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/regression/batches/${encodeURIComponent(String(args.batchId))}`,
    getBody: (args) => ({ name: args.name }),
  },
  deleteRegressionBatch: {
    label: 'Delete Regression Batch',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args) => `/regression/batches/${encodeURIComponent(String(args.batchId))}`,
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
    getBody: (_args, pid) => ({ project_id: pid || 'default' }),
  },
  triageSecurityFinding: {
    label: 'Triage Security Finding',
    method: 'PATCH',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/security-testing/findings/${args.findingId}/status?project_id=${encodeURIComponent(pid || 'default')}`,
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
    getBody: (args, pid) => ({
      url: args.url,
      base_url: args.baseUrl || args.serverUrl || undefined,
      feature_filter: args.featureFilter || undefined,
      method_filter: Array.isArray(args.methodFilter) ? args.methodFilter : undefined,
      mode: args.mode || 'plan_and_tests',
      project_id: pid || 'default',
    }),
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
    getPath: (args) => `/autopilot/${encodeURIComponent(String(args.sessionId))}/pause`,
  },
  resumeAutoPilot: {
    label: 'Resume Auto Pilot',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${encodeURIComponent(String(args.sessionId))}/resume`,
  },
  answerAutoPilotQuestion: {
    label: 'Answer Auto Pilot Question',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${encodeURIComponent(String(args.sessionId))}/answer`,
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
    getPath: (args) => `/autopilot/${encodeURIComponent(String(args.sessionId))}/test-tasks/${encodeURIComponent(String(args.taskId))}/stop`,
  },
  cancelAutoPilot: {
    label: 'Cancel Auto Pilot',
    method: 'POST',
    risk: 'destructive',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/autopilot/${encodeURIComponent(String(args.sessionId))}/cancel`,
  },
  createWorkflow: {
    label: 'Create Custom Workflow',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/workflows/definitions',
    getBody: (args, pid) => ({
      name: args.name,
      description: args.description || '',
      project_id: pid || 'default',
      steps: workflowSteps(args),
    }),
  },
  updateWorkflow: {
    label: 'Update Custom Workflow',
    method: 'PUT',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/definitions/${encodeURIComponent(String(args.workflowId))}?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      name: args.name || undefined,
      description: args.description || undefined,
      steps: args.steps ? workflowSteps(args) : undefined,
      status: args.isEnabled === false ? 'archived' : undefined,
    }),
  },
  duplicateWorkflow: {
    label: 'Duplicate Custom Workflow',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/definitions/${encodeURIComponent(String(args.workflowId))}/duplicate?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  archiveWorkflow: {
    label: 'Archive Custom Workflow',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/definitions/${encodeURIComponent(String(args.workflowId))}?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  startWorkflow: {
    label: 'Start Custom Workflow',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/definitions/${encodeURIComponent(String(args.workflowId))}/runs?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      inputs: args.inputs || args.parameters || {},
      triggered_by: 'chat',
      start_step_key: args.startStepKey || undefined,
    }),
  },
  startWorkflowFromStep: {
    label: 'Start Custom Workflow From Step',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/definitions/${encodeURIComponent(String(args.workflowId))}/runs?project_id=${encodeURIComponent(pid || 'default')}`,
    getBody: (args) => ({
      inputs: args.inputs || args.parameters || {},
      triggered_by: 'chat',
      start_step_key: args.startStepKey,
    }),
  },
  retryWorkflowFailedStep: {
    label: 'Retry Custom Workflow Failed Step',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/runs/${encodeURIComponent(String(args.runId))}/steps/${encodeURIComponent(String(args.stepId))}/retry?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  pauseWorkflowRun: {
    label: 'Pause Custom Workflow Run',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/runs/${encodeURIComponent(String(args.runId))}/pause?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  resumeWorkflowRun: {
    label: 'Resume Custom Workflow Run',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/runs/${encodeURIComponent(String(args.runId))}/resume?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  cancelWorkflowRun: {
    label: 'Cancel Custom Workflow Run',
    method: 'POST',
    risk: 'destructive',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/workflows/runs/${encodeURIComponent(String(args.runId))}/cancel?project_id=${encodeURIComponent(pid || 'default')}`,
  },
  createProject: {
    label: 'Create Project',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/projects',
    getBody: (args) => ({
      name: args.name,
      base_url: args.baseUrl || undefined,
      description: args.description || undefined,
    }),
  },
  updateProject: {
    label: 'Update Project',
    method: 'PUT',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(String(args.projectId || pid || 'default'))}`,
    getBody: (args) => ({
      name: args.name || undefined,
      base_url: args.baseUrl || undefined,
      description: args.description || undefined,
    }),
  },
  deleteProject: {
    label: 'Delete Project',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args) => {
      const params = new URLSearchParams();
      if (args.reassignTo) params.set('reassign_to', String(args.reassignTo));
      const suffix = params.toString() ? `?${params}` : '';
      return `/projects/${encodeURIComponent(String(args.projectId))}${suffix}`;
    },
  },
  assignSpecToProject: {
    label: 'Assign Spec to Project',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => {
      const targetProjectId = String(args.projectId || pid || 'default');
      const params = new URLSearchParams({ spec_name: String(args.specName || '') });
      return `/projects/${encodeURIComponent(targetProjectId)}/assign-spec?${params}`;
    },
  },
  bulkAssignSpecsToProject: {
    label: 'Bulk Assign Specs to Project',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(String(args.projectId || pid || 'default'))}/bulk-assign-specs`,
    getBody: (args) => args.specNames,
  },
  setProjectCredential: {
    label: 'Set Project Credential',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(String(args.projectId || pid || 'default'))}/credentials`,
    getBody: (args) => ({ key: args.key, value: args.value }),
  },
  removeProjectCredential: {
    label: 'Remove Project Credential',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(String(args.projectId || pid || 'default'))}/credentials/${encodeURIComponent(String(args.key))}`,
  },
  startRecording: {
    label: 'Start Recording',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/recordings/start',
    getBody: (args, pid) => ({
      target_url: args.targetUrl,
      project_id: pid || 'default',
      name: args.name || undefined,
      viewport_size: args.viewportSize || undefined,
      device: args.device || undefined,
      load_storage_path: args.loadStoragePath || undefined,
      save_storage: args.saveStorage ?? false,
      save_har: args.saveHar ?? false,
    }),
  },
  stopRecording: {
    label: 'Stop Recording',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/recordings/${encodeURIComponent(String(args.recordingId))}/stop`,
  },
  importRecording: {
    label: 'Import Recording',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/recordings/${encodeURIComponent(String(args.recordingId))}/import`,
    getBody: (args) => ({ name: args.name || undefined }),
  },
  createSchedule: {
    label: 'Create Schedule',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/scheduling/${encodeURIComponent(pid || 'default')}/schedules`,
    getBody: (args) => scheduleBody(args),
  },
  updateSchedule: {
    label: 'Update Schedule',
    method: 'PUT',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/scheduling/${encodeURIComponent(pid || 'default')}/schedules/${encodeURIComponent(String(args.scheduleId))}`,
    getBody: (args) => scheduleBody(args),
  },
  deleteSchedule: {
    label: 'Delete Schedule',
    method: 'DELETE',
    risk: 'destructive',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: (args, pid) => `/scheduling/${encodeURIComponent(pid || 'default')}/schedules/${encodeURIComponent(String(args.scheduleId))}`,
  },
  toggleSchedule: {
    label: 'Toggle Schedule',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/scheduling/${encodeURIComponent(pid || 'default')}/schedules/${encodeURIComponent(String(args.scheduleId))}/toggle`,
  },
  updateAssistantSettings: {
    label: 'Update Assistant Settings',
    method: 'POST',
    risk: 'high',
    requiredRole: 'admin',
    confirmationRequired: true,
    getPath: () => '/settings',
    getBody: (args) => ({
      llm_provider: args.llmProvider,
      api_key: args.apiKey || undefined,
      base_url: args.baseUrl || undefined,
      model_name: args.modelName || undefined,
      light_model: args.lightModel || undefined,
      standard_model: args.standardModel || undefined,
      deep_model: args.deepModel || undefined,
      tool_deep_model: args.toolDeepModel || undefined,
      chat_model: args.chatModel || undefined,
      embedding_model: args.embeddingModel || undefined,
      agent_runtime: args.agentRuntime || undefined,
      assistant_runtime: args.assistantRuntime || undefined,
    }),
  },
  generatePrdPlan: {
    label: 'Generate PRD Test Plan',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/api/prd/${encodeURIComponent(String(args.prdProjectId))}/generate-plan`,
    getBody: (args) => ({
      feature: args.feature || undefined,
      target_url: args.targetUrl || undefined,
      login_url: args.loginUrl || undefined,
      credentials: args.credentials || undefined,
    }),
  },
  stopPrdGeneration: {
    label: 'Stop PRD Generation',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args) => `/api/prd/generation/${args.generationId}/stop`,
  },
  generatePrdTest: {
    label: 'Generate PRD Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/prd/generate-test',
    getBody: (args) => ({ spec_path: args.specPath, target_url: args.targetUrl || undefined }),
  },
  healPrdTest: {
    label: 'Heal PRD Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/prd/heal-test',
    getBody: (args) => ({ test_path: args.testPath, error_log: args.errorLog }),
  },
  runPrdTest: {
    label: 'Run PRD Test',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: () => '/api/prd/run-test',
    getBody: (args) => ({
      test_path: args.testPath,
      heal: args.heal ?? true,
      max_attempts: args.maxAttempts ?? 3,
    }),
  },
  syncCiRuns: {
    label: 'Sync CI Runs',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/runs/sync`,
    getBody: (args) => ({
      provider: args.provider || 'all',
      workflow_id: args.workflowId || undefined,
      per_page: args.perPage ?? 20,
    }),
  },
  dispatchCiWorkflow: {
    label: 'Dispatch CI Workflow',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/workflows/dispatch`,
    getBody: (args) => ({
      provider: args.provider || 'github',
      workflow_id: args.workflowId || undefined,
      ref: args.ref || undefined,
      inputs: buildCiWorkflowInputs(args),
    }),
  },
  cancelCiRun: {
    label: 'Cancel CI Run',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/runs/${args.provider}/${args.mappingId}/cancel`,
  },
  rerunCiRun: {
    label: 'Rerun CI Run',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/runs/${args.provider}/${args.mappingId}/rerun`,
    getBody: (args) => ({ failed_only: args.failedOnly ?? false }),
  },
  generateCiWorkflowChange: {
    label: 'Generate CI Workflow Change',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/workflow-change-requests`,
    getBody: (args) => ({
      provider: 'github',
      workflow_name: args.workflowName || 'Quorvex Test Automation',
      template: args.template || 'pr-quality-gate',
      quality_gate_mode: args.qualityGateMode || 'backend-async',
      prompt: args.prompt || undefined,
      ref: args.ref || undefined,
      branches: args.branches || undefined,
      browsers: args.browsers || undefined,
      artifact_retention_days: args.artifactRetentionDays ?? 14,
      wait_timeout_minutes: args.waitTimeoutMinutes ?? 120,
    }),
  },
  openCiWorkflowPullRequest: {
    label: 'Open CI Workflow Pull Request',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/workflow-change-requests/${encodeURIComponent(String(args.changeId))}/pull-request`,
    getBody: (args) => ({
      base_ref: args.baseRef || undefined,
      branch_name: args.branchName || undefined,
      title: args.title || undefined,
      body: args.body || undefined,
      commit_message: args.commitMessage || undefined,
      draft: args.draft ?? true,
    }),
  },
  updateCiProviderDefaults: {
    label: 'Update CI Provider Defaults',
    method: 'PATCH',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/providers/defaults`,
    getBody: (args) => ({
      provider: args.provider,
      repository: args.repository || undefined,
      owner: args.owner || undefined,
      repo: args.repo || undefined,
      gitlab_project_id: args.gitlabProjectId || undefined,
      base_url: args.baseUrl || undefined,
      default_ref: args.defaultRef || undefined,
      default_workflow: args.defaultWorkflow || undefined,
    }),
  },
  createCiTestSubset: {
    label: 'Create CI Test Subset',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/test-subsets`,
    getBody: (args) => ({
      name: args.name,
      description: args.description || undefined,
      mode: args.mode || 'both',
      default_browser: args.defaultBrowser || 'chromium',
      base_url_secret: args.baseUrlSecret || 'APP_BASE_URL',
      items: buildCiTestSubsetItems(args.items),
    }),
  },
  updateCiTestSubset: {
    label: 'Update CI Test Subset',
    method: 'PATCH',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/test-subsets/${encodeURIComponent(String(args.subsetId))}`,
    getBody: (args) => ({
      name: args.name || undefined,
      description: args.description || undefined,
      mode: args.mode || undefined,
      default_browser: args.defaultBrowser || undefined,
      base_url_secret: args.baseUrlSecret || undefined,
      items: Array.isArray(args.items) ? buildCiTestSubsetItems(args.items) : undefined,
    }),
  },
  deleteCiTestSubset: {
    label: 'Delete CI Test Subset',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/test-subsets/${encodeURIComponent(String(args.subsetId))}`,
  },
  openCiTestSubsetPullRequest: {
    label: 'Open CI Test Subset Pull Request',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/test-subsets/${encodeURIComponent(String(args.subsetId))}/pull-request`,
    getBody: (args) => ({
      base_ref: args.baseRef || undefined,
      branch_name: args.branchName || undefined,
      title: args.title || undefined,
      body: args.body || undefined,
      workflow_name: args.workflowName || undefined,
      commit_message: args.commitMessage || undefined,
      draft: args.draft ?? true,
    }),
  },
  dispatchCiTestSubset: {
    label: 'Dispatch CI Test Subset',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/projects/${encodeURIComponent(pid || 'default')}/ci/test-subsets/${encodeURIComponent(String(args.subsetId))}/dispatch`,
    getBody: (args) => ({
      workflow_id: args.workflowId || undefined,
      ref: args.ref || undefined,
      browser: args.browser || undefined,
      base_url: args.baseUrl || undefined,
    }),
  },
  analyzePullRequestTests: {
    label: 'Analyze Pull Request Tests',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/github/${encodeURIComponent(pid || 'default')}/pr-advisor/analyze`,
    getBody: (args) => ({
      pr_number: args.prNumber,
      ensure_indexed: args.ensureIndexed ?? true,
      force_reindex: args.forceReindex ?? false,
    }),
  },
  runPrAdvisorRecommendedTests: {
    label: 'Run PR Advisor Recommended Tests',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/github/${encodeURIComponent(pid || 'default')}/pr-advisor/analyses/${encodeURIComponent(String(args.analysisId))}/run`,
    getBody: (args) => ({
      browser: args.browser || 'chromium',
      hybrid: args.hybrid ?? false,
      max_iterations: args.maxIterations ?? 20,
      spec_names: Array.isArray(args.specNames) ? args.specNames : undefined,
    }),
  },
  startPrQualityGate: {
    label: 'Start PR Quality Gate',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/github/${encodeURIComponent(pid || 'default')}/quality-gates/pr/start`,
    getBody: (args) => ({
      pr_number: args.prNumber,
      head_sha: args.headSha || undefined,
      ensure_indexed: args.ensureIndexed,
      force_reindex: args.forceReindex,
      run_recommended: args.runRecommended,
      post_feedback: args.postFeedback,
      create_commit_status: args.createCommitStatus,
      browser: args.browser || undefined,
      hybrid: args.hybrid,
      max_iterations: args.maxIterations,
    }),
  },
  generateJiraBugReport: {
    label: 'Generate Jira Bug Report',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/jira/${encodeURIComponent(pid || 'default')}/generate-bug-report/${encodeURIComponent(String(args.runId))}`,
  },
  createJiraIssue: {
    label: 'Create Jira Issue',
    method: 'POST',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/jira/${encodeURIComponent(pid || 'default')}/create-issue`,
    getBody: (args) => ({
      run_id: args.runId,
      project_key: args.projectKey,
      issue_type_id: args.issueTypeId,
      title: args.title,
      description: args.description,
      priority_name: args.priorityName || undefined,
      labels: args.labels || undefined,
      attach_screenshots: args.attachScreenshots ?? true,
    }),
  },
  pushTestRailCases: {
    label: 'Push TestRail Cases',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/testrail/${encodeURIComponent(pid || 'default')}/push-cases`,
    getBody: (args) => ({
      spec_names: args.specNames,
      testrail_project_id: args.testrailProjectId,
      testrail_suite_id: args.testrailSuiteId,
    }),
  },
  syncTestRailResults: {
    label: 'Sync TestRail Results',
    method: 'POST',
    risk: 'medium',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (_args, pid) => `/testrail/${encodeURIComponent(pid || 'default')}/sync-results`,
    getBody: (args) => ({
      batch_id: args.batchId,
      testrail_project_id: args.testrailProjectId,
      testrail_suite_id: args.testrailSuiteId,
    }),
  },
  deleteTestRailMapping: {
    label: 'Delete TestRail Mapping',
    method: 'DELETE',
    risk: 'high',
    requiredRole: 'editor',
    confirmationRequired: true,
    getPath: (args, pid) => `/testrail/${encodeURIComponent(pid || 'default')}/mappings/${encodeURIComponent(String(args.mappingId))}`,
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

export const ALL_CUSTOM_AGENT_TOOL_IDS = [
  'read_file',
  'list_files',
  'glob_files',
  'grep_files',
  'write_file',
  'edit_file',
  'multi_edit_file',
  'bash',
  ...ADHOC_CUSTOM_AGENT_TOOL_IDS,
  'browser_drag',
  'browser_evaluate',
  'browser_upload',
  'browser_dialog',
  'browser_generate_locator',
  'browser_verify_element',
  'browser_verify_list',
  'browser_verify_text',
  'browser_verify_value',
  'browser_resume',
  'browser_start_tracing',
  'browser_stop_tracing',
  'test_list',
  'test_run',
  'planner_setup_page',
  'planner_save_plan',
  'generator_setup_page',
  'generator_read_log',
  'generator_write_test',
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

function scheduleBody(args: Record<string, unknown>) {
  return {
    name: args.name || undefined,
    description: args.description || undefined,
    cron_expression: args.cronExpression || undefined,
    timezone: args.timezone || undefined,
    tags: args.tags || undefined,
    automated_only: args.automatedOnly,
    browser: args.browser || undefined,
    hybrid_mode: args.hybridMode,
    max_iterations: args.maxIterations,
    spec_names: args.specNames || undefined,
    enabled: args.enabled,
  };
}

function requirementBody(args: Record<string, unknown>, partial = false) {
  const body: Record<string, unknown> = {
    title: args.title,
    description: args.description || undefined,
    category: args.category || (partial ? undefined : 'other'),
    priority: args.priority || (partial ? undefined : 'medium'),
    status: args.status || undefined,
    acceptance_criteria: args.acceptanceCriteria || undefined,
  };
  return Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined));
}

function securityScanBody(args: Record<string, unknown>, projectId?: string) {
  const body: Record<string, unknown> = {
    target_url: args.targetUrl || args.url,
    project_id: projectId || 'default',
    auth_config: args.authConfig || undefined,
    login_url: args.loginUrl || undefined,
    username_key: args.usernameKey || undefined,
    password_key: args.passwordKey || undefined,
    scope: args.scope || 'origin',
    excluded_paths: args.excludedPaths || [],
    active_scan_level: args.activeScanLevel || 'safe',
  };
  if (args.severityFilter) body.severity_filter = args.severityFilter;
  if (args.templates) body.templates = args.templates;
  if (args.scanPolicy) body.scan_policy = args.scanPolicy;
  return body;
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
      agent_name: typeof args.agentName === 'string' ? args.agentName.trim() || undefined : undefined,
      focus_areas: focusAreas.length > 0 ? focusAreas : undefined,
      target_service_count: typeof args.targetServiceCount === 'number' ? args.targetServiceCount : undefined,
      require_observed_evidence: args.requireObservedEvidence ?? true,
      public_only: args.publicOnly ?? true,
      requested_tools: customAgentToolIds(args),
      chat_draft: {
        description: typeof args.description === 'string' ? args.description : undefined,
        output_goals: Array.isArray(args.outputGoals) ? args.outputGoals : undefined,
      },
    },
  };
}

export function buildCodingAgentRunBody(args: Record<string, unknown>, projectId?: string) {
  const prompt = typeof args.prompt === 'string' && args.prompt.trim()
    ? args.prompt.trim()
    : typeof args.task === 'string' && args.task.trim()
      ? args.task.trim()
      : 'Inspect the current Quorvex repository and propose a safe code diff.';
  return {
    agent_type: 'coding',
    runtime: typeof args.runtime === 'string' ? args.runtime : 'claude_sdk',
    model_tier: typeof args.modelTier === 'string' ? args.modelTier : 'tool_deep',
    project_id: projectId || 'default',
    config: {
      prompt,
      task: prompt,
      source: 'chat_coding_agent',
      autonomy_mode: 'propose_diff_only',
      repo_scope: '/Users/nihadmammadli/Documents/projects/quorvex_ai',
      timeout_seconds: typeof args.timeoutSeconds === 'number' ? args.timeoutSeconds : 1800,
      runtime: typeof args.runtime === 'string' ? args.runtime : 'claude_sdk',
      model_tier: typeof args.modelTier === 'string' ? args.modelTier : 'tool_deep',
    },
  };
}

function customAgentName(args: Record<string, unknown>) {
  if (typeof args.agentName === 'string' && args.agentName.trim()) {
    return args.agentName.trim().slice(0, 120);
  }
  return `Ad-hoc QA Agent - ${hostnameLabel(String(args.url || 'website'))}`;
}

function customAgentDescription(args: Record<string, unknown>) {
  if (typeof args.description === 'string' && args.description.trim()) {
    return args.description.trim().slice(0, 500);
  }
  return `Chat-created custom QA agent for ${args.url || 'the requested website'}.`;
}

function customAgentSystemPrompt(args: Record<string, unknown>) {
  if (typeof args.systemPrompt === 'string' && args.systemPrompt.trim()) {
    return args.systemPrompt.trim();
  }
  return ADHOC_CUSTOM_AGENT_SYSTEM_PROMPT;
}

function customAgentDefinitionSystemPrompt(args: Record<string, unknown>) {
  const base = customAgentSystemPrompt(args);
  if (typeof args.prompt !== 'string' || !args.prompt.trim()) return base;
  return [
    base,
    '',
    'Default operating brief for this saved agent:',
    args.prompt.trim(),
  ].join('\n');
}

function customAgentToolIds(args: Record<string, unknown>) {
  const requested = Array.isArray(args.toolIds) ? args.toolIds : ADHOC_CUSTOM_AGENT_TOOL_IDS;
  const valid = requested
    .filter((toolId): toolId is string => typeof toolId === 'string' && ALL_CUSTOM_AGENT_TOOL_IDS.includes(toolId));
  return Array.from(new Set(valid.length > 0 ? valid : ADHOC_CUSTOM_AGENT_TOOL_IDS));
}

function buildCiWorkflowInputs(args: Record<string, unknown>) {
  const inputs: Record<string, string> = {};
  if (args.inputs && typeof args.inputs === 'object' && !Array.isArray(args.inputs)) {
    for (const [key, value] of Object.entries(args.inputs as Record<string, unknown>)) {
      if (typeof value === 'string') inputs[key] = value;
    }
  }

  const subsetInputs: Array<[string, unknown]> = [
    ['suite', args.suite],
    ['browser', args.browser],
    ['pytest_marker', args.pytestMarker],
    ['test_path', args.testPath],
    ['playwright_grep', args.playwrightGrep],
    ['base_url', args.baseUrl],
  ];
  for (const [key, value] of subsetInputs) {
    if (typeof value === 'string' && value.trim()) inputs[key] = value.trim();
  }

  return Object.keys(inputs).length > 0 ? inputs : undefined;
}

function buildCiTestSubsetItems(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const record = item as Record<string, unknown>;
      const specName = typeof record.specName === 'string' ? record.specName.trim() : '';
      if (!specName) return null;
      return {
        spec_name: specName,
        target_path: typeof record.targetPath === 'string' && record.targetPath.trim() ? record.targetPath.trim() : undefined,
      };
    })
    .filter(Boolean);
}

function workflowSteps(args: Record<string, unknown>) {
  const steps = Array.isArray(args.steps) ? args.steps : undefined;
  if (steps) return steps;
  const definition = args.definition;
  if (definition && typeof definition === 'object' && Array.isArray((definition as Record<string, unknown>).steps)) {
    return (definition as Record<string, unknown>).steps;
  }
  return [];
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

function buildBrowserAuthControls(args: Record<string, unknown>) {
  if (args.skipBrowserAuth === true) {
    return { skip_browser_auth: true };
  }
  const explicitSession = typeof args.browserAuthSessionId === 'string' ? args.browserAuthSessionId.trim() : '';
  const explorerSession = typeof args.sessionId === 'string' && args.authType === 'session' ? args.sessionId.trim() : '';
  const sessionId = explicitSession || explorerSession;
  if (sessionId) {
    return { browser_auth_session_id: sessionId };
  }
  if (args.useProjectDefaultBrowserAuth === true) {
    return { use_project_default_browser_auth: true };
  }
  return {};
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
