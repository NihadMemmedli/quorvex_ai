import { expect, type APIRequestContext, type Page, test } from '@playwright/test';
import * as http from 'node:http';

const APP_BASE = process.env.BASE_URL || 'http://localhost:3000';
const API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin123!@#';
const BACKEND_TEST_HOST = process.env.BROWSER_AUTH_E2E_HOST || 'host.docker.internal';

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

type LoginFixture = {
  browserUrl: string;
  backendUrl: string;
  close: () => Promise<void>;
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

  expect(response.ok()).toBeTruthy();
  const body = await response.json() as TokenResponse;
  return body.access_token;
}

async function createProject(request: APIRequestContext) {
  const token = await getAccessToken(request);
  const response = await request.post(`${API_BASE}/projects`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E Browser Auth ${Date.now()} ${Math.random().toString(16).slice(2)}`,
      description: 'Browser auth sessions regression fixture',
      base_url: 'https://example.test',
    },
  });

  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ id: string; name: string }>;
}

async function deleteProject(request: APIRequestContext, projectId: string) {
  const token = await getAccessToken(request);
  await request.delete(`${API_BASE}/projects/${projectId}`, {
    headers: { Authorization: `Bearer ${token}` },
    failOnStatusCode: false,
  });
}

async function loginThroughUi(page: Page, returnTo: string, projectId: string) {
  await page.addInitScript(({ selectedProjectId }) => {
    window.localStorage.removeItem('refresh_token');
    window.localStorage.setItem('we-test-current-project-id', selectedProjectId);
  }, { selectedProjectId: projectId });

  await page.goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
  await page.locator('#email').fill(ADMIN_EMAIL);
  await page.locator('#password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(`**${returnTo}`);
}

async function startLoginFixture(): Promise<LoginFixture> {
  const server = http.createServer((req, res) => {
    if (req.url === '/login' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`
        <!doctype html>
        <html>
          <body>
            <form method="post" action="/login">
              <label>Email <input type="email" name="email" autocomplete="username" /></label>
              <label>Password <input type="password" name="password" autocomplete="current-password" /></label>
              <button type="submit">Log in</button>
            </form>
          </body>
        </html>
      `);
      return;
    }

    if (req.url === '/login' && req.method === 'POST') {
      req.resume();
      res.writeHead(303, {
        Location: '/account',
        'Set-Cookie': 'auth_session=e2e-browser-auth; Path=/; SameSite=Lax',
      });
      res.end();
      return;
    }

    if (req.url === '/account') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end('<h1>Account</h1>');
      return;
    }

    res.writeHead(404);
    res.end('Not found');
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '0.0.0.0', () => resolve());
  });

  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Could not start browser auth login fixture');
  }

  return {
    browserUrl: `http://127.0.0.1:${address.port}`,
    backendUrl: `http://${BACKEND_TEST_HOST}:${address.port}`,
    close: () => new Promise<void>((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve());
    }),
  };
}

async function startEmailFirstLoginFixture(): Promise<LoginFixture> {
  const server = http.createServer((req, res) => {
    if (req.url === '/login' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`
        <!doctype html>
        <html>
          <body>
            <form method="post" action="/login/email">
              <label>Email <input type="email" name="email" autocomplete="username" /></label>
              <button type="submit">Next</button>
            </form>
          </body>
        </html>
      `);
      return;
    }

    if (req.url === '/login/email' && req.method === 'POST') {
      req.resume();
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`
        <!doctype html>
        <html>
          <body>
            <form method="post" action="/login/password">
              <label>Password <input type="password" name="password" autocomplete="current-password" /></label>
              <button type="submit">Sign in</button>
            </form>
          </body>
        </html>
      `);
      return;
    }

    if (req.url === '/login/password' && req.method === 'POST') {
      req.resume();
      res.writeHead(303, {
        Location: '/account',
        'Set-Cookie': 'auth_session=e2e-browser-auth-email-first; Path=/; SameSite=Lax',
      });
      res.end();
      return;
    }

    if (req.url === '/account') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end('<h1>Account</h1>');
      return;
    }

    res.writeHead(404);
    res.end('Not found');
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '0.0.0.0', () => resolve());
  });

  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Could not start browser auth email-first login fixture');
  }

  return {
    browserUrl: `http://127.0.0.1:${address.port}`,
    backendUrl: `http://${BACKEND_TEST_HOST}:${address.port}`,
    close: () => new Promise<void>((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve());
    }),
  };
}

test.describe('Browser login sessions', () => {
  test.use({ baseURL: APP_BASE });

  test.beforeAll(async ({ request }) => {
    await assertStackIsReady(request);
    await getAccessToken(request);
  });

  test('creates and manages a reusable browser login session', async ({ page, request }) => {
    const fixture = await startLoginFixture();
    const project = await createProject(request);

    try {
      await loginThroughUi(page, '/settings', project.id);
      await expect(page.getByText('Browser Login Sessions')).toBeVisible();

      await page.getByRole('button', { name: 'Enter credentials' }).click();
      await page.getByPlaceholder('Staging login').fill('Local test login');
      await page.getByPlaceholder('https://app.example.com', { exact: true }).fill(fixture.browserUrl);
      await page.getByPlaceholder('https://app.example.com/login', { exact: true }).fill(`${fixture.backendUrl}/login`);
      await page.getByPlaceholder('user@example.com').fill('tester@example.com');
      await page.getByPlaceholder('Password', { exact: true }).fill('correct-password');

      await page.getByRole('button', { name: 'Create' }).click();
      await expect(page.getByText('Opening the login page and capturing reusable browser state...')).toBeVisible();
      await expect(page.getByText('Browser login session created.')).toBeVisible({ timeout: 120_000 });

      const sessionRow = page.getByTestId('browser-auth-session-row').filter({ hasText: 'Local test login' });
      await expect(sessionRow).toContainText('active');
      await expect(sessionRow).toContainText('Default');

      await page.getByRole('button', { name: 'Validate Local test login' }).click();
      await expect(page.getByText('Browser login session updated.')).toBeVisible();
      await expect(sessionRow).toContainText('active');

      await page.getByRole('button', { name: 'Refresh Local test login' }).click();
      await expect(page.getByText('Browser login session updated.')).toBeVisible({ timeout: 120_000 });
      await expect(sessionRow).toContainText('active');

      await page.getByRole('button', { name: 'Revoke Local test login' }).click();
      await expect(page.getByText('Browser login session revoked.')).toBeVisible();
      await expect(page.getByText('Local test login')).toBeHidden();
    } finally {
      await deleteProject(request, project.id);
      await fixture.close();
    }
  });

  test('captures an email-first login session with advanced success URL validation', async ({ page, request }) => {
    const fixture = await startEmailFirstLoginFixture();
    const project = await createProject(request);

    try {
      await loginThroughUi(page, '/settings', project.id);
      await expect(page.getByText('Browser Login Sessions')).toBeVisible();

      await page.getByRole('button', { name: 'Enter credentials' }).click();
      await page.getByPlaceholder('Staging login').fill('Email-first login');
      await page.getByPlaceholder('https://app.example.com', { exact: true }).fill(fixture.browserUrl);
      await page.getByPlaceholder('https://app.example.com/login', { exact: true }).fill(`${fixture.backendUrl}/login`);
      await page.getByPlaceholder('user@example.com').fill('tester@example.com');
      await page.getByPlaceholder('Password', { exact: true }).fill('correct-password');
      await page.getByText('Advanced selectors').click();
      await page.getByPlaceholder('/dashboard$').fill('/account$');

      await page.getByRole('button', { name: 'Create' }).click();
      await expect(page.getByText('Opening the login page and capturing reusable browser state...')).toBeVisible();
      await expect(page.getByText('Browser login session created.')).toBeVisible({ timeout: 120_000 });

      const sessionRow = page.getByTestId('browser-auth-session-row').filter({ hasText: 'Email-first login' });
      await expect(sessionRow).toContainText('active');
      await expect(sessionRow).toContainText('/account$');
    } finally {
      await deleteProject(request, project.id);
      await fixture.close();
    }
  });
});
