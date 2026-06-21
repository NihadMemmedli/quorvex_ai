import { expect, request as playwrightRequest, type APIRequestContext, type Page, test } from '@playwright/test';

const APP_BASE = process.env.BASE_URL || 'http://localhost:3000';
const API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin123!@#';
const PROJECT_BASE_URL = 'https://pre.wetravel.to/';

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
      if (response.ok()) break;
      if (response.status() !== 429 && response.status() < 500) break;
    } catch (error) {
      lastError = error;
    }
    if (attempt < 5) await new Promise(resolve => setTimeout(resolve, 5_000));
  }

  expect(response?.ok(), `Admin login failed: ${lastError || response?.status()}`).toBeTruthy();
  const body = await response.json() as TokenResponse;
  return body.access_token;
}

async function createProject(request: APIRequestContext) {
  const token = await getAccessToken(request);
  const response = await request.post(`${API_BASE}/projects`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E Base URL ${Date.now()} ${Math.random().toString(16).slice(2)}`,
      description: 'Project base URL regression fixture',
      base_url: PROJECT_BASE_URL,
    },
  });

  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ id: string; name: string; base_url: string }>;
}

async function deleteProjectById(projectId: string) {
  const request = await playwrightRequest.newContext();
  try {
    const token = await getAccessToken(request);
    await request.delete(`${API_BASE}/projects/${projectId}`, {
      headers: { Authorization: `Bearer ${token}` },
      failOnStatusCode: false,
    });
  } finally {
    await request.dispose();
  }
}

async function loginThroughUi(page: Page, returnTo: string, projectId: string) {
  await page.addInitScript(({ selectedProjectId }) => {
    window.localStorage.setItem('we-test-current-project-id', selectedProjectId);
  }, { selectedProjectId: projectId });

  await page.goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
  await page.locator('#email').fill(ADMIN_EMAIL);
  await page.locator('#password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(`**${returnTo}`);
}

async function installPrdAndRequirementMocks(page: Page) {
  await page.route(`${API_BASE}/api/prd/projects**`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{ project: 'E2E PRD Base URL', feature_count: 1, processed_at: new Date().toISOString() }]),
  }));

  await page.route(`${API_BASE}/api/prd/E2E%20PRD%20Base%20URL/features`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      features: [{ name: 'Checkout', slug: 'checkout', requirements: ['Complete checkout'] }],
    }),
  }));

  await page.route(`${API_BASE}/requirements/stats**`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      total: 1,
      by_category: { checkout: 1 },
      by_priority: { high: 1 },
      by_status: { approved: 1 },
    }),
  }));

  await page.route(`${API_BASE}/requirements?**`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        id: 101,
        req_code: 'REQ-101',
        title: 'Checkout works',
        description: 'Customer can complete checkout.',
        category: 'checkout',
        priority: 'high',
        status: 'approved',
        truth_state: 'confirmed_requirement',
        acceptance_criteria: ['Checkout succeeds'],
        source_session_id: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    }),
  }));

  await page.route(`${API_BASE}/requirements/101/spec-status**`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      has_spec: false,
      truth_state: 'confirmed_requirement',
      generation_allowed: true,
    }),
  }));
}

test.describe('Project Base URL defaults', () => {
  test.use({ baseURL: APP_BASE });

  test.beforeAll(async ({ request }) => {
    await assertStackIsReady(request);
    await getAccessToken(request);
  });

  test('prefills URL-driven workflows from the selected project base URL', async ({ page, request }) => {
    test.setTimeout(60_000);
    const project = await createProject(request);

    try {
      await installPrdAndRequirementMocks(page);
      await loginThroughUi(page, '/exploration', project.id);

      await page.getByRole('button', { name: 'New Exploration' }).click();
      await expect(page.locator('.modal-content input[type="url"]').first()).toHaveValue(PROJECT_BASE_URL);
      await page.getByRole('button', { name: 'Cancel' }).click();

      await page.goto('/autopilot');
      await expect(page.locator('textarea').first()).toHaveValue(PROJECT_BASE_URL);

      await page.goto('/security-testing');
      await expect(page.getByPlaceholder('https://example.com')).toHaveValue(PROJECT_BASE_URL);

      await page.goto('/prd');
      await page.getByText('E2E PRD Base URL').click();
      await page.getByText('Configuration').click();
      await expect(page.getByPlaceholder('https://your-app.com')).toHaveValue(PROJECT_BASE_URL);

      await page.goto('/requirements');
      await page.getByRole('button', { name: /Create Spec/ }).first().click();
      await page.getByText('AI Generate').click();
      await expect(page.getByPlaceholder('https://app.example.com/feature')).toHaveValue(PROJECT_BASE_URL);
    } finally {
      await deleteProjectById(project.id);
    }
  });
});
