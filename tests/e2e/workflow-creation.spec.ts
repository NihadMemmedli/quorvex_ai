import { expect, request as playwrightRequest, type APIRequestContext, type Page, test } from '@playwright/test';

const APP_BASE = process.env.BASE_URL || 'http://localhost:3000';
const API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin123!@#';

type WorkflowDefinition = {
  id: string;
  name: string;
  description: string;
  steps: Array<{
    key: string;
    type: string;
    label?: string;
    input?: Record<string, unknown>;
    continue_on_error?: boolean;
  }>;
};

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

let cachedTokens: TokenResponse | undefined;

async function assertStackIsReady(request: APIRequestContext) {
  const [frontend, backend] = await Promise.all([
    request.get(APP_BASE),
    request.get(`${API_BASE}/docs`),
  ]);

  expect(frontend.ok(), `Frontend is not reachable at ${APP_BASE}`).toBeTruthy();
  expect(backend.ok(), `Backend is not reachable at ${API_BASE}`).toBeTruthy();
}

async function getAuthTokens(request: APIRequestContext) {
  if (cachedTokens) return cachedTokens;

  let response;
  let lastError: unknown;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      response = await request.post(`${API_BASE}/auth/login`, {
        data: {
          email: ADMIN_EMAIL,
          password: ADMIN_PASSWORD,
        },
      });
    } catch (error) {
      lastError = error;
      response = undefined;
    }
    if (response?.ok()) {
      cachedTokens = await response.json() as TokenResponse;
      return cachedTokens;
    }
    if (response && response.status() !== 429 && response.status() < 500) break;
    if (attempt === 5) break;
    await new Promise(resolve => setTimeout(resolve, 5_000));
  }

  expect(
    response?.ok(),
    `Default admin login failed (${lastError || response?.status()}). Seed it with: python orchestrator/scripts/create_admin.py --email ${ADMIN_EMAIL} --password '${ADMIN_PASSWORD}' --force-password`,
  ).toBeTruthy();

  throw new Error('Default admin login failed');
}

async function getAccessToken(request: APIRequestContext) {
  const tokens = await getAuthTokens(request);
  return tokens.access_token;
}

async function refreshAuthTokens(request: APIRequestContext) {
  if (cachedTokens) {
    const response = await request.post(`${API_BASE}/auth/refresh`, {
      data: { refresh_token: cachedTokens.refresh_token },
    });
    if (response.ok()) {
      cachedTokens = await response.json() as TokenResponse;
      return cachedTokens;
    }
    cachedTokens = undefined;
  }

  return getAuthTokens(request);
}

async function withCleanupRequest<T>(callback: (request: APIRequestContext, token: string) => Promise<T>) {
  const request = await playwrightRequest.newContext({ timeout: 5_000 });
  try {
    const token = await getAccessToken(request);
    return await callback(request, token);
  } finally {
    await request.dispose();
  }
}

async function bestEffortCleanup(callback: (request: APIRequestContext, token: string) => Promise<void>) {
  try {
    await withCleanupRequest(callback);
  } catch (error) {
    console.warn('Workflow E2E cleanup failed:', error);
  }
}

function workflowDefinitionResponse(definitionId: string, method: string, suffix = '') {
  return (response: { url(): string; request(): { method(): string } }) =>
    response.url().includes(`/workflows/definitions/${definitionId}${suffix}`) &&
    response.request().method() === method;
}

async function loginThroughUi(page: Page) {
  const body = await refreshAuthTokens(page.request);

  await page.goto('/login');
  await page.evaluate(({ refreshToken }) => {
    window.localStorage.setItem('refresh_token', refreshToken);
    window.localStorage.setItem('we-test-current-project-id', 'default');
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith('workflow-builder-draft:')) window.localStorage.removeItem(key);
    }
  }, { refreshToken: body.refresh_token });

  await page.goto('/workflow');
  await expect(page.getByRole('heading', { name: 'Custom Workflows' })).toBeVisible();
  await expect(page.locator('button').filter({ hasText: /\d+ templates · \d+ saved/ }).first()).toBeVisible({ timeout: 20_000 });
}

test.describe('Workflow creation dashboard', () => {
  test.use({ baseURL: APP_BASE });

  test.beforeAll(async ({ request }) => {
    await assertStackIsReady(request);
    await getAccessToken(request);
  });

  test('creates a custom workflow from the UI, persists it, and starts it from a safe step', async ({ page, request }) => {
    test.setTimeout(90_000);
    let createdDefinitionId: string | undefined;
    let startedRunId: string | undefined;

    try {
      const workflowName = `E2E Workflow ${Date.now()}`;
      const token = await getAccessToken(request);
      const headers = { Authorization: `Bearer ${token}` };
      const createResponse = await request.post(`${API_BASE}/workflows/definitions`, {
        headers,
        data: {
          name: workflowName,
          description: 'Created by the workflow creation E2E smoke test.',
          project_id: 'default',
          steps: [
            {
              key: 'autopilot',
              type: 'start_autopilot',
              label: 'Run AutoPilot',
              input: { entry_urls: ['https://example.com'], max_interactions: 1, max_specs: 1 },
            },
            {
              key: 'wait_autopilot',
              type: 'wait_for_status',
              label: 'Wait for AutoPilot',
              input: { source_step: 'autopilot', timeout_seconds: 30, poll_seconds: 5 },
            },
            {
              key: 'review',
              type: 'review_gate',
              label: 'Review Results',
              input: { question: 'Review the current workflow state before continuing.' },
            },
          ],
        },
      });
      expect(createResponse.ok()).toBeTruthy();

      const createdDefinition = await createResponse.json() as WorkflowDefinition;
      createdDefinitionId = createdDefinition.id;
      const reviewStepKey = 'review';
      const reviewStepLabel = 'Review Results';

      await loginThroughUi(page);
      await page.getByRole('button', { name: /^Discover Find/ }).click();
      await page.getByRole('button', { name: /^Library/ }).click();

      await expect(page.getByRole('heading', { name: 'Workflow library' })).toBeVisible();
      const workflowCard = page.locator('article').filter({ hasText: createdDefinition.name }).first();
      await expect(workflowCard).toBeVisible();
      await expect(workflowCard).toContainText('3 steps');

      const definitionsResponse = await request.get(`${API_BASE}/workflows/definitions?project_id=default`);
      expect(definitionsResponse.ok()).toBeTruthy();
      const definitions = await definitionsResponse.json() as WorkflowDefinition[];
      const persistedDefinition = definitions.find(definition => definition.id === createdDefinitionId);
      expect(persistedDefinition).toBeTruthy();
      expect(persistedDefinition).toMatchObject({
        id: createdDefinitionId,
      });
      expect(persistedDefinition?.steps.map(step => step.type)).toEqual(['start_autopilot', 'wait_for_status', 'review_gate']);

      await page.evaluate(() => {
        for (const key of Object.keys(window.localStorage)) {
          if (key.startsWith('workflow-builder-draft:')) window.localStorage.removeItem(key);
        }
      });
      await page.goto('/workflow');
      await expect(page.getByRole('heading', { name: 'Custom Workflows' })).toBeVisible();
      await page.getByRole('button', { name: /^Discover Find/ }).click();
      await page.getByRole('button', { name: /^Library/ }).click();
      await expect(page.getByRole('heading', { name: 'Workflow library' })).toBeVisible();

      await page.getByRole('textbox', { name: 'Search workflows' }).fill(createdDefinition.name);
      await expect(workflowCard).toBeVisible();
      const startResponsePromise = page.waitForResponse(workflowDefinitionResponse(createdDefinitionId, 'POST', '/runs'));
      await workflowCard.getByRole('button', { name: /run from a specific step/i }).click();
      await page.getByRole('menuitem', { name: new RegExp(`3\\s*${reviewStepLabel}`, 'i') }).click();
      const startResponse = await startResponsePromise;
      expect(startResponse.ok()).toBeTruthy();

      const startPayload = startResponse.request().postDataJSON() as { triggered_by: string; start_step_key?: string };
      expect(startPayload).toMatchObject({
        triggered_by: 'ui',
        start_step_key: reviewStepKey,
      });

      const startBody = await startResponse.json() as { run_id: string; definition_id: string; status: string };
      startedRunId = startBody.run_id;
      expect(startBody).toMatchObject({
        definition_id: createdDefinitionId,
        status: 'queued',
      });

      await expect(page.getByRole('heading', { name: 'Recent runs' })).toBeVisible();
      await expect(page.getByText(startedRunId).first()).toBeVisible();
      await expect(page.getByText(createdDefinition.name).first()).toBeVisible();
    } finally {
      await bestEffortCleanup(async (cleanupRequest, token) => {
        const headers = { Authorization: `Bearer ${token}` };

        if (startedRunId) {
          await cleanupRequest.post(`${API_BASE}/workflows/runs/${startedRunId}/cancel?project_id=default`, {
            headers,
            failOnStatusCode: false,
          });
        }

        if (createdDefinitionId) {
          await cleanupRequest.delete(`${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default`, {
            headers,
            failOnStatusCode: false,
          });
        }
      });
    }
  });

  test('guides users through missing custom agent setup', async ({ page }) => {
    await page.route(`${API_BASE}/api/agents/definitions**`, async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '[]',
      });
    });

    await loginThroughUi(page);

    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByRole('heading', { name: 'Create workflow' })).toBeVisible();

    const stepCards = page.locator('main .workflow-step-list').first().locator('.workflow-step-card');
    let customAgentStep = stepCards.filter({ hasText: 'Start Custom Agent' }).first();
    for (let attempt = 0; attempt < 2 && await customAgentStep.count() === 0; attempt += 1) {
      await page.getByRole('button', { name: /Start Custom Agent.*Adds wait step/ }).click();
      customAgentStep = stepCards.filter({ hasText: 'Start Custom Agent' }).first();
    }
    await expect(customAgentStep).toBeVisible({ timeout: 20_000 });
    await expect(customAgentStep.getByText('No agents available')).toBeVisible();
    await expect(customAgentStep.getByText('Create or activate an agent definition before using this step.')).toBeVisible();
    await expect(customAgentStep.getByRole('link', { name: 'Manage agents' })).toHaveAttribute('href', '/agents');
    await expect(customAgentStep.getByText('Type: start custom agent')).toHaveCount(0);
    await expect(customAgentStep.getByRole('button', { name: 'Advanced' })).toBeVisible();

    await customAgentStep.getByRole('button', { name: 'Advanced' }).click();
    await expect(customAgentStep.getByRole('button', { name: 'Hide advanced' })).toBeVisible();
    await expect(customAgentStep.getByText('Edit raw step input JSON.')).toBeVisible();

    const waitStep = page.locator('main .workflow-step-list').first().locator('.workflow-step-card').filter({ hasText: 'Wait for Start Custom Agent' }).first();
    await expect(waitStep.getByText(/Depends on: Start Custom Agent|Depends on: Run Custom Agent/)).toBeVisible();
    await expect(waitStep.getByText(/Waits for: Start Custom Agent|Waits for: Run Custom Agent/)).toBeVisible();

    await expect(page.getByRole('button', { name: 'Create Workflow' })).toBeDisabled();
  });

  test('auto-connects generation steps to matching earlier async outputs', async ({ page }) => {
    await loginThroughUi(page);

    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByRole('heading', { name: 'Create workflow' })).toBeVisible();

    const stepCards = page.locator('main .workflow-step-list').first().locator('.workflow-step-card');
    let explorationStep = stepCards.filter({ hasText: /Start Exploration|Explore Application/ }).first();
    for (let attempt = 0; attempt < 2 && await explorationStep.count() === 0; attempt += 1) {
      await page.getByRole('button', { name: /Start Exploration.*Adds wait step/ }).click();
      explorationStep = stepCards.filter({ hasText: /Start Exploration|Explore Application/ }).first();
    }
    await expect(explorationStep).toBeVisible({ timeout: 20_000 });

    const waitStep = stepCards.filter({ hasText: /Wait for Start Exploration|Wait for Explore Application|Wait for Exploration/ }).first();
    await expect(waitStep).toBeVisible();
    await waitStep.getByRole('button', { name: /Add Generate Requirements/i }).click();

    const requirementsStep = stepCards.filter({ hasText: 'Generate Requirements' }).first();
    await expect(requirementsStep).toBeVisible();
    await expect.poll(async () => page.locator('input, textarea').evaluateAll(
      (fields, value) => fields.filter(field => (field as HTMLInputElement | HTMLTextAreaElement).value === value).length,
      '{{steps.exploration_1.external_id}}',
    )).toBe(0);
    await expect(requirementsStep.getByText('Add Start Exploration before Generate Requirements')).toHaveCount(0);
  });

  test('archives a workflow from the library menu and hides it from the active list', async ({ page, request }) => {
    const workflowName = `Archive Workflow ${Date.now()}`;
    const token = await getAccessToken(request);
    const headers = { Authorization: `Bearer ${token}` };
    let createdDefinitionId: string | undefined;

    try {
      const createResponse = await request.post(`${API_BASE}/workflows/definitions`, {
        headers,
        data: {
          name: workflowName,
          description: 'Created by the workflow archive E2E test.',
          project_id: 'default',
          steps: [
            {
              key: 'autopilot',
              type: 'start_autopilot',
              label: 'Run AutoPilot',
              input: { entry_urls: ['https://example.com'], max_interactions: 1, max_specs: 1 },
            },
            {
              key: 'wait_autopilot',
              type: 'wait_for_status',
              label: 'Wait for AutoPilot',
              input: { source_step: 'autopilot', timeout_seconds: 30, poll_seconds: 5 },
            },
            {
              key: 'review',
              type: 'review_gate',
              label: 'Review Results',
              input: { question: 'Review the current workflow state before continuing.' },
            },
          ],
        },
      });
      expect(createResponse.ok()).toBeTruthy();

      const createdDefinition = await createResponse.json() as WorkflowDefinition;
      createdDefinitionId = createdDefinition.id;

      await loginThroughUi(page);
      await page.getByRole('button', { name: /^Discover Find/ }).click();
      await page.getByRole('button', { name: /^Library/ }).click();
      await expect(page.getByRole('heading', { name: 'Workflow library' })).toBeVisible();

      const workflowCard = page.locator('article').filter({ hasText: workflowName }).first();
      await expect(workflowCard).toBeVisible();

      const archiveResponsePromise = page.waitForResponse(workflowDefinitionResponse(createdDefinitionId, 'DELETE'));
      await workflowCard.getByRole('button', { name: /run from a specific step/i }).click();
      await page.getByRole('menuitem', { name: 'Archive workflow' }).click();
      const archiveResponse = await archiveResponsePromise;
      expect(archiveResponse.ok()).toBeTruthy();

      await expect(workflowCard).toBeHidden();

      const definitionsResponse = await request.get(`${API_BASE}/workflows/definitions?project_id=default`, {
        headers,
      });
      expect(definitionsResponse.ok()).toBeTruthy();
      const definitions = await definitionsResponse.json() as WorkflowDefinition[];
      expect(definitions.some(definition => definition.id === createdDefinitionId)).toBeFalsy();
    } finally {
      await bestEffortCleanup(async (cleanupRequest, cleanupToken) => {
        const cleanupHeaders = { Authorization: `Bearer ${cleanupToken}` };

        if (createdDefinitionId) {
          await cleanupRequest.delete(`${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default`, {
            headers: cleanupHeaders,
            failOnStatusCode: false,
          });
        }
      });
    }
  });

  test('creates a workflow from a QA template with guided fields', async ({ page, request }) => {
    test.setTimeout(60_000);
    let createdDefinitionId: string | undefined;

    try {
      await loginThroughUi(page);

      await page.getByRole('button', { name: 'Templates', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Workflow templates', exact: true })).toBeVisible();

      const templateCard = page.locator('article.workflow-template-card').filter({ hasText: 'Explore Requirements Review' }).first();
      await expect(templateCard).toBeVisible();
      const token = await getAccessToken(request);
      const headers = { Authorization: `Bearer ${token}` };
      const createResponse = await request.post(`${API_BASE}/workflows/definitions`, {
        headers,
        data: {
          name: `Template Workflow ${Date.now()}`,
          description: 'Created by the workflow template E2E test.',
          project_id: 'default',
          steps: [
            { key: 'explore', type: 'start_exploration', label: 'Explore Application', input: { entry_url: 'https://example.com', max_interactions: 1 } },
            { key: 'wait_explore', type: 'wait_for_status', label: 'Wait for Exploration', input: { source_step: 'explore', timeout_seconds: 30, poll_seconds: 5 } },
            { key: 'requirements', type: 'generate_requirements', label: 'Generate Requirements', input: { exploration_session_id: '{{steps.explore.external_id}}' } },
            { key: 'wait_requirements', type: 'wait_for_status', label: 'Wait for Requirements', input: { source_step: 'requirements', timeout_seconds: 30, poll_seconds: 5 } },
            { key: 'review', type: 'review_gate', label: 'Review Requirements', input: { question: 'Review requirements before continuing.' } },
          ],
        },
      });
      expect(createResponse.ok()).toBeTruthy();

      const createdDefinition = await createResponse.json() as WorkflowDefinition;
      createdDefinitionId = createdDefinition.id;
      expect(createdDefinition.steps.map(step => step.type)).toEqual([
        'start_exploration',
        'wait_for_status',
        'generate_requirements',
        'wait_for_status',
        'review_gate',
      ]);
      const explorationStepKey = createdDefinition.steps.find(step => step.type === 'start_exploration')?.key;
      const requirementsStepPayload = createdDefinition.steps.find(step => step.type === 'generate_requirements');
      expect(explorationStepKey).toBeTruthy();
      expect(requirementsStepPayload?.input?.exploration_session_id).toBe(`{{steps.${explorationStepKey}.external_id}}`);

      const definitionsResponse = await request.get(`${API_BASE}/workflows/definitions?project_id=default`);
      expect(definitionsResponse.ok()).toBeTruthy();
      const definitions = await definitionsResponse.json() as WorkflowDefinition[];
      expect(definitions.some(definition => definition.id === createdDefinitionId)).toBeTruthy();
    } finally {
      await bestEffortCleanup(async (cleanupRequest, token) => {
        const headers = { Authorization: `Bearer ${token}` };

        if (createdDefinitionId) {
          await cleanupRequest.delete(`${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default`, {
            headers,
            failOnStatusCode: false,
          });
        }
      });
    }
  });
});
