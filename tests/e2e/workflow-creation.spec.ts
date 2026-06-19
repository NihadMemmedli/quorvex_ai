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
    continue_on_error?: boolean;
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
      const continueOnErrorSwitch = autopilotStep.getByRole('switch', { name: 'Continue if this step fails' });
      await expect(continueOnErrorSwitch).toHaveAttribute('aria-checked', 'false');
      await continueOnErrorSwitch.click();
      await expect(continueOnErrorSwitch).toHaveAttribute('aria-checked', 'true');
      await expect(continueOnErrorSwitch).toHaveCSS('background-color', 'rgb(59, 130, 246)');

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
      expect(createPayload.steps[0].continue_on_error).toBe(true);

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
      expect(persistedDefinition?.steps[0].continue_on_error).toBe(true);

      await workflowCard.getByRole('button', { name: /run from a specific step/i }).click();
      await page.getByRole('menuitem', { name: 'Edit workflow' }).click();
      await expect(page.getByRole('heading', { name: 'Edit workflow' })).toBeVisible();
      const reloadedAutopilotStep = page.locator('article').filter({ hasText: 'Run AutoPilot' }).first();
      await expect(reloadedAutopilotStep.getByRole('switch', { name: 'Continue if this step fails' })).toHaveAttribute('aria-checked', 'true');

      await page.getByRole('button', { name: /Library/ }).click();
      await expect(page.getByRole('heading', { name: 'Workflow library' })).toBeVisible();

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
        await request.post(`${API_BASE}/workflows/runs/${startedRunId}/cancel?project_id=default`, {
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

    const builder = page.locator('main');
    await builder.getByRole('textbox').nth(0).fill(`Custom Agent UX ${Date.now()}`);
    await page.getByRole('button', { name: /Start Custom Agent/i }).click();

    const customAgentStep = page.locator('article').filter({ hasText: 'Start Custom Agent' }).first();
    await expect(customAgentStep.getByText('No agents available')).toBeVisible();
    await expect(customAgentStep.getByText('Create or activate an agent definition before using this step.')).toBeVisible();
    await expect(customAgentStep.getByRole('link', { name: 'Manage agents' })).toHaveAttribute('href', '/agents');
    await expect(customAgentStep.getByText('Type: start custom agent')).toHaveCount(0);
    await expect(customAgentStep.getByRole('button', { name: 'Advanced' })).toBeVisible();

    await customAgentStep.getByRole('button', { name: 'Advanced' }).click();
    await expect(customAgentStep.getByRole('button', { name: 'Hide advanced' })).toBeVisible();
    await expect(customAgentStep.getByText('Edit raw step input JSON.')).toBeVisible();

    const waitStep = page.locator('article').filter({ hasText: 'Wait for Start Custom Agent' }).first();
    await expect(waitStep.getByText(/Depends on: Start Custom Agent|Depends on: Run Custom Agent/)).toBeVisible();
    await expect(waitStep.getByText(/Waits for: Start Custom Agent|Waits for: Run Custom Agent/)).toBeVisible();

    await page.getByRole('button', { name: 'Create Workflow' }).click();
    await expect(page.getByText('Choose an agent before creating this workflow.').first()).toBeVisible();
  });

  test('auto-connects generation steps to matching earlier async outputs', async ({ page }) => {
    await loginThroughUi(page);

    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByRole('heading', { name: 'Create workflow' })).toBeVisible();

    await page.getByRole('button', { name: 'Start Exploration' }).click();
    const waitStep = page.locator('article').filter({ hasText: 'Wait for Start Exploration' }).first();
    await waitStep.getByRole('button', { name: /Add Generate Requirements/i }).click();

    const requirementsStep = page.locator('article').filter({ hasText: 'Generate Requirements' }).first();
    await expect(requirementsStep.getByText('Use Start Exploration output')).toBeVisible();
    await expect(requirementsStep.getByText('Connected to Start Exploration.')).toBeVisible();
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

      const workflowCard = page.locator('article').filter({ hasText: workflowName }).first();
      await expect(workflowCard).toBeVisible();

      await workflowCard.getByRole('button', { name: /run from a specific step/i }).click();
      const archiveResponsePromise = page.waitForResponse(response =>
        response.url() === `${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default` &&
        response.request().method() === 'DELETE',
      );
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
      if (createdDefinitionId) {
        await request.delete(`${API_BASE}/workflows/definitions/${createdDefinitionId}?project_id=default`, {
          headers,
          failOnStatusCode: false,
        });
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

      const templateCard = page.locator('article').filter({ hasText: 'Explore Requirements Review' }).first();
      await templateCard.getByRole('button', { name: 'Use template' }).click();
      await expect(page.getByRole('heading', { name: 'Create workflow' })).toBeVisible();

      const builder = page.locator('main');
      await builder.getByRole('textbox').nth(0).fill(workflowName);

      const explorationStep = page.locator('article').filter({ hasText: 'Explore Application' }).first();
      await explorationStep.getByLabel('Entry URL').fill('https://example.com');
      await explorationStep.getByRole('spinbutton').fill('1');

      const requirementsStep = page.locator('article').filter({ hasText: 'Generate Requirements' }).first();
      await expect(requirementsStep.getByText('Use Explore Application output')).toBeVisible();
      await expect(requirementsStep.getByText('Connected to Explore Application.')).toBeVisible();
      await expect(requirementsStep.getByDisplayValue('{{steps.explore.external_id}}')).toHaveCount(0);

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
