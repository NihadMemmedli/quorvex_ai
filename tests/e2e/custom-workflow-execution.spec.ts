import { expect, type APIRequestContext, test } from '@playwright/test';

const API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin123!@#';
const PROJECT_ID = process.env.E2E_PROJECT_ID || 'default';

type WorkflowStepSpec = {
  key: string;
  type: string;
  label?: string;
  input?: Record<string, unknown>;
  continue_on_error?: boolean;
  recovery_policy?: Record<string, unknown>;
};

type WorkflowDefinition = {
  id: string;
  name: string;
  description: string;
  version?: number;
  steps: WorkflowStepSpec[];
};

type WorkflowRunStep = {
  id: number;
  step_key: string;
  step_type: string;
  status: string;
  output?: Record<string, unknown> | null;
  rendered_input?: Record<string, unknown> | null;
  context_snapshot?: Record<string, unknown> | null;
  input_resolution?: Record<string, unknown> | null;
  external_kind?: string | null;
  external_id?: string | null;
  skipped_reason?: string | null;
  error_message?: string | null;
  attempt_count: number;
};

type WorkflowRun = {
  id: string;
  definition_id: string;
  revision_id?: string | null;
  definition_version?: number;
  status: string;
  progress: number;
  current_step_index: number;
  temporal_workflow_id?: string | null;
  temporal_run_id?: string | null;
  result?: Record<string, unknown> | null;
  steps: WorkflowRunStep[];
};

type WorkflowEvent = {
  id: string;
  event_type: string;
  severity: string;
  message: string;
  run_id?: string | null;
  definition_id?: string | null;
};

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

function authHeaders(token: string) {
  return { Authorization: `Bearer ${token}` };
}

async function assertStackIsReady(request: APIRequestContext) {
  const [docs, temporalHealth] = await Promise.all([
    request.get(`${API_BASE}/docs`),
    request.get(`${API_BASE}/workflows/temporal/health`),
  ]);

  expect(docs.ok(), `Backend docs are not reachable at ${API_BASE}/docs`).toBeTruthy();
  expect(temporalHealth.ok(), 'Workflow Temporal health endpoint failed').toBeTruthy();

  const temporal = await temporalHealth.json() as { available: boolean; task_queue?: string };
  expect(temporal.available, `Temporal is not available: ${JSON.stringify(temporal)}`).toBe(true);
  expect(temporal.task_queue).toBeTruthy();
}

async function getAccessToken(request: APIRequestContext) {
  const response = await request.post(`${API_BASE}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });

  if (!response.ok()) {
    throw new Error(
      `Admin login failed with ${response.status()}: ${await response.text()}. Seed it with: python orchestrator/scripts/create_admin.py --email ${ADMIN_EMAIL} --password '${ADMIN_PASSWORD}' --force-password`,
    );
  }

  const body = await response.json() as TokenResponse;
  return body.access_token;
}

async function createDefinition(
  request: APIRequestContext,
  token: string,
  name: string,
  steps: WorkflowStepSpec[],
) {
  const response = await request.post(`${API_BASE}/workflows/definitions`, {
    headers: authHeaders(token),
    data: {
      name,
      description: 'Created by deterministic custom workflow execution e2e tests.',
      project_id: PROJECT_ID,
      steps,
    },
  });

  expect(response.ok(), `Definition creation failed: ${await response.text()}`).toBeTruthy();
  return await response.json() as WorkflowDefinition;
}

async function startRun(
  request: APIRequestContext,
  token: string,
  definitionId: string,
  data: Record<string, unknown> = {},
) {
  const response = await request.post(`${API_BASE}/workflows/definitions/${definitionId}/runs?project_id=${PROJECT_ID}`, {
    headers: authHeaders(token),
    data: { triggered_by: 'e2e-api', ...data },
  });

  expect(response.ok(), `Workflow start failed: ${await response.text()}`).toBeTruthy();
  return await response.json() as { run_id: string; definition_id: string; status: string };
}

async function readRun(request: APIRequestContext, token: string, runId: string) {
  const response = await request.get(`${API_BASE}/workflows/runs/${runId}`, {
    headers: authHeaders(token),
  });

  expect(response.ok(), `Workflow run ${runId} was not readable: ${await response.text()}`).toBeTruthy();
  return await response.json() as WorkflowRun;
}

async function pollRunStatus(
  request: APIRequestContext,
  token: string,
  runId: string,
  expectedStatuses: string[],
  timeoutMs = 30_000,
) {
  const expected = new Set(expectedStatuses);
  const startedAt = Date.now();
  let lastRun: WorkflowRun | undefined;

  while (Date.now() - startedAt < timeoutMs) {
    lastRun = await readRun(request, token, runId);
    if (expected.has(lastRun.status)) {
      return lastRun;
    }
    await new Promise(resolve => setTimeout(resolve, 1_000));
  }

  throw new Error(
    `Timed out waiting for workflow run ${runId} to reach ${expectedStatuses.join(', ')}. Last state: ${JSON.stringify(lastRun)}`,
  );
}

async function listRunEvents(request: APIRequestContext, token: string, runId: string) {
  const response = await request.get(
    `${API_BASE}/workflows/events?project_id=${PROJECT_ID}&run_id=${runId}&order=asc&limit=100`,
    { headers: authHeaders(token) },
  );

  expect(response.ok(), `Workflow events for ${runId} were not readable: ${await response.text()}`).toBeTruthy();
  return await response.json() as WorkflowEvent[];
}

async function cancelRunIfActive(request: APIRequestContext, token: string, runId?: string) {
  if (!runId) {
    return;
  }
  const run = await request.get(`${API_BASE}/workflows/runs/${runId}`, {
    headers: authHeaders(token),
    failOnStatusCode: false,
  });
  if (!run.ok()) {
    return;
  }
  const body = await run.json() as WorkflowRun;
  if (['completed', 'failed', 'cancelled'].includes(body.status)) {
    return;
  }
  await request.post(`${API_BASE}/workflows/runs/${runId}/cancel`, {
    headers: authHeaders(token),
    failOnStatusCode: false,
  });
}

async function archiveDefinition(request: APIRequestContext, token: string, definitionId?: string) {
  if (!definitionId) {
    return;
  }
  await request.delete(`${API_BASE}/workflows/definitions/${definitionId}?project_id=${PROJECT_ID}`, {
    headers: authHeaders(token),
    failOnStatusCode: false,
  });
}

test.describe('Custom workflow execution e2e', () => {
  test.describe.configure({ mode: 'serial' });

  let token: string;

  test.beforeAll(async ({ request }) => {
    await assertStackIsReady(request);
    token = await getAccessToken(request);
  });

  test('executes a user review workflow through Temporal and resumes it to completion', async ({ request }) => {
    test.setTimeout(60_000);

    let definitionId: string | undefined;
    let runId: string | undefined;

    try {
      const definition = await createDefinition(request, token, `E2E Review Execution ${Date.now()}`, [
        {
          key: 'review',
          type: 'review_gate',
          label: 'Review Value',
          input: {
            question: 'Confirm this workflow reached the user review checkpoint.',
            suggested_answers: ['Approve', 'Needs changes'],
          },
        },
      ]);
      definitionId = definition.id;

      expect(definition.steps.map(step => step.type)).toEqual(['review_gate']);
      expect(definition.version).toBeGreaterThanOrEqual(1);

      const started = await startRun(request, token, definition.id);
      runId = started.run_id;
      expect(started).toMatchObject({
        definition_id: definition.id,
        status: 'queued',
      });

      const awaitingReview = await pollRunStatus(request, token, runId, ['awaiting_input']);
      expect(awaitingReview.revision_id).toBeTruthy();
      expect(awaitingReview.definition_version).toBeGreaterThanOrEqual(1);
      expect(awaitingReview.temporal_workflow_id).toMatch(new RegExp(`^custom-workflow-run-${runId}$`));
      expect(awaitingReview.temporal_run_id).toBeTruthy();
      expect(awaitingReview.progress).toBe(1);
      expect(awaitingReview.steps).toHaveLength(1);

      const [reviewStep] = awaitingReview.steps;
      expect(reviewStep).toMatchObject({
        step_key: 'review',
        step_type: 'review_gate',
        status: 'awaiting_input',
        attempt_count: 1,
      });
      expect(reviewStep.external_kind).toBeNull();
      expect(reviewStep.rendered_input).toMatchObject({
        question: 'Confirm this workflow reached the user review checkpoint.',
      });
      expect(reviewStep.context_snapshot).toMatchObject({
        run: { id: runId, project_id: PROJECT_ID },
      });
      expect(reviewStep.output).toMatchObject({
        awaiting_input: true,
        status: 'awaiting_input',
        question: 'Confirm this workflow reached the user review checkpoint.',
        external_kind: 'review_gate',
        contract_version: 1,
      });

      const reviewEvents = await listRunEvents(request, token, runId);
      expect(reviewEvents.map(event => event.event_type)).toEqual(
        expect.arrayContaining(['workflow.run_created', 'workflow.started', 'workflow.review_needed']),
      );

      const resume = await request.post(`${API_BASE}/workflows/runs/${runId}/resume`, {
        headers: authHeaders(token),
      });
      expect(resume.ok(), `Workflow resume failed: ${await resume.text()}`).toBeTruthy();

      const completed = await pollRunStatus(request, token, runId, ['completed']);
      expect(completed.progress).toBe(1);
      expect(completed.steps[0].status).toBe('completed');
      expect(completed.result).toMatchObject({
        steps: {
          review: expect.objectContaining({ awaiting_input: true, external_kind: 'review_gate' }),
        },
      });

      const completionEvents = await listRunEvents(request, token, runId);
      expect(completionEvents.map(event => event.event_type)).toEqual(
        expect.arrayContaining(['workflow.resumed', 'workflow.completed']),
      );
    } finally {
      await cancelRunIfActive(request, token, runId);
      await archiveDefinition(request, token, definitionId);
    }
  });

  test('starts a workflow from a later step and records skipped upstream work', async ({ request }) => {
    test.setTimeout(60_000);

    let definitionId: string | undefined;
    let runId: string | undefined;

    try {
      const definition = await createDefinition(request, token, `E2E Start From Step ${Date.now()}`, [
        {
          key: 'triage',
          type: 'review_gate',
          label: 'Triage Findings',
          input: { question: 'Review generated findings before remediation.' },
        },
        {
          key: 'final_review',
          type: 'review_gate',
          label: 'Final Review',
          input: { question: 'Confirm the final workflow output is useful.' },
        },
      ]);
      definitionId = definition.id;

      const started = await startRun(request, token, definition.id, { start_step_key: 'final_review' });
      runId = started.run_id;

      const awaitingReview = await pollRunStatus(request, token, runId, ['awaiting_input']);
      expect(awaitingReview.current_step_index).toBe(1);
      expect(awaitingReview.steps).toHaveLength(2);
      expect(awaitingReview.steps[0]).toMatchObject({
        step_key: 'triage',
        status: 'skipped',
        output: {
          skipped: true,
          reason: 'run_started_from_later_step',
        },
      });
      expect(awaitingReview.steps[1]).toMatchObject({
        step_key: 'final_review',
        step_type: 'review_gate',
        status: 'awaiting_input',
      });
      expect(awaitingReview.steps[1].context_snapshot).toMatchObject({
        steps: {
          triage: {
            skipped: true,
            reason: 'run_started_from_later_step',
          },
        },
      });

      const events = await listRunEvents(request, token, runId);
      expect(events.map(event => event.event_type)).toEqual(
        expect.arrayContaining(['workflow.run_created', 'workflow.run_started_from_step', 'workflow.review_needed']),
      );
    } finally {
      await cancelRunIfActive(request, token, runId);
      await archiveDefinition(request, token, definitionId);
    }
  });

  test('cancels an active review workflow and marks awaiting steps cancelled', async ({ request }) => {
    test.setTimeout(60_000);

    let definitionId: string | undefined;
    let runId: string | undefined;

    try {
      const definition = await createDefinition(request, token, `E2E Cancel Review ${Date.now()}`, [
        {
          key: 'review',
          type: 'review_gate',
          label: 'Review Before Cancel',
          input: { question: 'This run should be cancellable while awaiting review.' },
        },
      ]);
      definitionId = definition.id;

      const started = await startRun(request, token, definition.id);
      runId = started.run_id;
      await pollRunStatus(request, token, runId, ['awaiting_input']);

      const cancel = await request.post(`${API_BASE}/workflows/runs/${runId}/cancel`, {
        headers: authHeaders(token),
      });
      expect(cancel.ok(), `Workflow cancel failed: ${await cancel.text()}`).toBeTruthy();
      expect(await cancel.json()).toMatchObject({ run_id: runId, status: 'cancelled' });

      const cancelled = await pollRunStatus(request, token, runId, ['cancelled']);
      expect(cancelled.steps).toHaveLength(1);
      expect(cancelled.steps[0]).toMatchObject({
        step_key: 'review',
        status: 'cancelled',
      });

      const events = await listRunEvents(request, token, runId);
      expect(events.map(event => event.event_type)).toEqual(expect.arrayContaining(['workflow.cancelled']));
    } finally {
      await archiveDefinition(request, token, definitionId);
    }
  });
});
