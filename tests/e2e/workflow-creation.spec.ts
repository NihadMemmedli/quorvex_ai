import { expect, type APIRequestContext, type Page, test } from '@playwright/test';

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
  }>;
};

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

async function assertStackIsReady(request: APIRequestContext) {
  const [frontend, backend] = await Promise.all([
    request.get(APP_BASE),
    request.get(`${API_BASE}/docs`),
  ]);

  expect(frontend.ok(), `Frontend is not reachable at ${APP_BASE}`).toBeTruthy();
  expect(backend.ok(), `Backend is not reachable at ${API_BASE}`).toBeTruthy();
}

async function getAccessToken(request: APIRequestContext) {
  const response = await request.post(`${API_BASE}/auth/login`, {
    data: {
      email: ADMIN_EMAIL,
      password: ADMIN_PASSWORD,
    },
  });

  expect(
    response.ok(),
    `Default admin login failed. Seed it with: python orchestrator/scripts/create_admin.py --email ${ADMIN_EMAIL} --password '${ADMIN_PASSWORD}' --force-password`,
  ).toBeTruthy();

  const body = await response.json() as TokenResponse;
  return body.access_token;
}

async function loginThroughUi(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.removeItem('refresh_token');
    window.localStorage.setItem('we-test-current-project-id', 'default');
  });

  await page.goto('/login?returnTo=/workflow');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await page.locator('#email').fill(ADMIN_EMAIL);
  await page.locator('#password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();

  await page.waitForURL('**/workflow');
  await expect(page.getByRole('heading', { name: 'Custom Workflows' })).toBeVisible();
}

test.describe('Workflow creation dashboard', () => {
  test.use({ baseURL: APP_BASE });

  test.beforeAll(async ({ request }) => {
    await assertStackIsReady(request);
    await getAccessToken(request);
  });

  test('creates a custom workflow from the UI, persists it, and starts it from a safe step', async ({ page, request }) => {
    const workflowName = `E2E Workflow ${Date.now()}`;
    const workflowDescription = 'Created by the workflow creation E2E smoke test.';
    let createdDefinitionId: string | undefined;
    let startedRunId: string | undefined;

    try {
      await loginThroughUi(page);

      await page.getByRole('button', { name: 'New workflow' }).click();
      await expect(page.getByRole('heading', { name: 'Create workflow' })).toBeVisible();

      const builder = page.locator('main');
      await builder.getByRole('textbox').nth(0).fill(workflowName);
      await builder.getByRole('textbox').nth(1).fill(workflowDescription);

      const autopilotStep = page.locator('article').filter({ hasText: 'Run AutoPilot' }).first();
      await autopilotStep.getByPlaceholder('https://example.com').fill('https://example.com');
      await autopilotStep.getByRole('spinbutton').nth(0).fill('1');
      await autopilotStep.getByRole('spinbutton').nth(1).fill('1');

      const createResponsePromise = page.waitForResponse(response =>
        response.url() === `${API_BASE}/workflows/definitions` &&
        response.request().method() === 'POST',
      );
      await page.getByRole('button', { name: 'Create Workflow' }).click();
      const createResponse = await createResponsePromise;
      expect(createResponse.ok()).toBeTruthy();

      const createPayload = createResponse.request().postDataJSON() as {
        name: string;
        description: string;
        project_id: string;
        steps: WorkflowDefinition['steps'];
      };
      expect(createPayload).toMatchObject({
        name: workflowName,
        description: workflowDescription,
        project_id: 'default',
      });
      expect(createPayload.steps.map(step => step.key)).toEqual(['autopilot', 'wait_autopilot', 'review']);
      expect(createPayload.steps.map(step => step.type)).toEqual(['start_autopilot', 'wait_for_status', 'review_gate']);

      const createdDefinition = await createResponse.json() as WorkflowDefinition;
      createdDefinitionId = createdDefinition.id;

      await expect(page.getByRole('heading', { name: 'Workflow library' })).toBeVisible();
      const workflowCard = page.locator('article').filter({ hasText: workflowName }).first();
      await expect(workflowCard).toBeVisible();
      await expect(workflowCard).toContainText(workflowDescription);
      await expect(workflowCard).toContainText('3 steps');

      const definitionsResponse = await request.get(`${API_BASE}/workflows/definitions?project_id=default`);
      expect(definitionsResponse.ok()).toBeTruthy();
      const definitions = await definitionsResponse.json() as WorkflowDefinition[];
      const persistedDefinition = definitions.find(definition => definition.id === createdDefinitionId);
      expect(persistedDefinition).toBeTruthy();
      expect(persistedDefinition).toMatchObject({
        id: createdDefinitionId,
        name: workflowName,
        description: workflowDescription,
      });
      expect(persistedDefinition?.steps.map(step => step.type)).toEqual(['start_autopilot', 'wait_for_status', 'review_gate']);

      await workflowCard.getByRole('button', { name: /run from a specific step/i }).click();
      const startResponsePromise = page.waitForResponse(response =>
        response.url() === `${API_BASE}/workflows/definitions/${createdDefinitionId}/runs?project_id=default` &&
        response.request().method() === 'POST',
      );
      await page.getByRole('menuitem', { name: /3\.\s*Review Results/i }).click();
      const startResponse = await startResponsePromise;
      expect(startResponse.ok()).toBeTruthy();

      const startPayload = startResponse.request().postDataJSON() as { triggered_by: string; start_step_key?: string };
      expect(startPayload).toMatchObject({
        triggered_by: 'ui',
        start_step_key: 'review',
      });

      const startBody = await startResponse.json() as { run_id: string; definition_id: string; status: string };
      startedRunId = startBody.run_id;
      expect(startBody).toMatchObject({
        definition_id: createdDefinitionId,
        status: 'queued',
      });

      await expect(page.getByRole('heading', { name: 'Recent runs' })).toBeVisible();
      await expect(page.getByText(startedRunId)).toBeVisible();
      await expect(page.getByText(workflowName).first()).toBeVisible();
    } finally {
      const token = await getAccessToken(request);
      const headers = { Authorization: `Bearer ${token}` };

      if (startedRunId) {
        await request.post(`${API_BASE}/workflows/runs/${startedRunId}/cancel`, {
          headers,
          failOnStatusCode: false,
        });
      }

      if (createdDefinitionId) {
        await request.delete(`${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default`, {
          headers,
          failOnStatusCode: false,
        });
      } else {
        const definitionsResponse = await request.get(`${API_BASE}/workflows/definitions?project_id=default`, {
          failOnStatusCode: false,
        });
        if (definitionsResponse.ok()) {
          const definitions = await definitionsResponse.json() as WorkflowDefinition[];
          const leftovers = definitions.filter(definition => definition.name === workflowName);
          for (const definition of leftovers) {
            await request.delete(`${API_BASE}/workflows/definitions/${definition.id}?project_id=default`, {
              headers,
              failOnStatusCode: false,
            });
          }
        }
      }
    }
  });

  test('creates a workflow from a QA template with guided fields', async ({ page, request }) => {
    const workflowName = `Template Workflow ${Date.now()}`;
    let createdDefinitionId: string | undefined;

    try {
      await loginThroughUi(page);

      await page.getByRole('button', { name: /Templates \(/ }).click();
      await expect(page.getByRole('heading', { name: 'Workflow templates' })).toBeVisible();

      const templateCard = page.locator('article').filter({ hasText: 'Explore To Requirements' }).first();
      await templateCard.getByRole('button', { name: 'Use template' }).click();
      await expect(page.getByRole('heading', { name: 'Create workflow' })).toBeVisible();

      const builder = page.locator('main');
      await builder.getByRole('textbox').nth(0).fill(workflowName);

      const explorationStep = page.locator('article').filter({ hasText: 'Explore Application' }).first();
      await explorationStep.getByLabel('Entry URL').fill('https://example.com');
      await explorationStep.getByRole('spinbutton').fill('1');

      const requirementsStep = page.locator('article').filter({ hasText: 'Generate Requirements' }).first();
      await expect(requirementsStep.getByDisplayValue('{{steps.explore.external_id}}')).toBeVisible();

      const createResponsePromise = page.waitForResponse(response =>
        response.url() === `${API_BASE}/workflows/definitions` &&
        response.request().method() === 'POST',
      );
      await page.getByRole('button', { name: 'Create Workflow' }).click();
      const createResponse = await createResponsePromise;
      expect(createResponse.ok()).toBeTruthy();

      const createPayload = createResponse.request().postDataJSON() as {
        name: string;
        steps: WorkflowDefinition['steps'];
      };
      expect(createPayload.name).toBe(workflowName);
      expect(createPayload.steps.map(step => step.key)).toEqual(['explore', 'wait_explore', 'requirements', 'wait_requirements', 'review']);
      expect(createPayload.steps.map(step => step.type)).toEqual([
        'start_exploration',
        'wait_for_status',
        'generate_requirements',
        'wait_for_status',
        'review_gate',
      ]);
      expect(createPayload.steps[2].input).toMatchObject({
        exploration_session_id: '{{steps.explore.external_id}}',
      });

      const createdDefinition = await createResponse.json() as WorkflowDefinition;
      createdDefinitionId = createdDefinition.id;

      await expect(page.getByRole('heading', { name: 'Workflow library' })).toBeVisible();
      await expect(page.locator('article').filter({ hasText: workflowName }).first()).toBeVisible();
    } finally {
      const token = await getAccessToken(request);
      const headers = { Authorization: `Bearer ${token}` };

      if (createdDefinitionId) {
        await request.delete(`${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default`, {
          headers,
          failOnStatusCode: false,
        });
      }
    }
  });
});
