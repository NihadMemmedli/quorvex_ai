import { expect, test } from '@playwright/test';
import {
  APP_BASE,
  attachUiErrorGuards,
  authenticateDashboard,
  expectPageReady,
  installDashboardApiMocks,
} from './helpers/dashboard-mocks';

async function bootDashboard(page: Parameters<typeof installDashboardApiMocks>[0]) {
  await authenticateDashboard(page);
  await installDashboardApiMocks(page);
  return attachUiErrorGuards(page);
}

test.describe('Dashboard feature controls', () => {
  test.use({ baseURL: APP_BASE });

  test('logs in through the UI and lands on the requested dashboard route', async ({ page }) => {
    await installDashboardApiMocks(page);
    const guards = attachUiErrorGuards(page);

    await page.goto('/login?returnTo=/dashboard');
    await page.getByLabel('Email').fill('qa@example.com');
    await page.getByLabel('Password').fill('Admin123!@#');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await page.waitForURL('**/dashboard');
    await expectPageReady(page, 'Reporting Dashboard');
    await guards.assertClean();
  });

  test('validates registration passwords before account creation', async ({ page }) => {
    await installDashboardApiMocks(page);

    await page.goto('/register');
    await page.getByLabel(/Full Name/).fill('E2E User');
    await page.getByLabel('Email').fill('new-user@example.test');
    await page.getByLabel('Password', { exact: true }).fill('weak');
    await page.getByLabel('Confirm Password').fill('weak');
    await expect(page.getByText('At least 8 characters')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create account' })).toBeDisabled();

    await page.getByLabel('Password', { exact: true }).fill('Strong123!');
    await page.getByLabel('Confirm Password').fill('Strong123?');
    await expect(page.getByText('Passwords do not match')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create account' })).toBeDisabled();
  });

  test('creates, switches to, edits, and deletes a project with mocked API cleanup', async ({ page }) => {
    const guards = await bootDashboard(page);
    const projectName = `E2E Project ${Date.now()}`;
    const updatedName = `${projectName} Updated`;

    await page.goto('/projects');
    await expectPageReady(page, 'Projects');

    await page.getByRole('button', { name: 'New Project' }).click();
    const createDialog = page.getByRole('heading', { name: 'Create New Project' }).locator('..').locator('..');
    await createDialog.getByPlaceholder('My Test Project').fill(projectName);
    await createDialog.getByPlaceholder('Optional description for this project').fill('Created by mocked E2E controls.');
    await createDialog.getByPlaceholder('https://example.com').fill('https://created.example.test');
    await createDialog.getByRole('button', { name: 'Create Project' }).click();

    const projectCard = page.locator('div').filter({ hasText: projectName }).filter({ hasText: 'Created by mocked E2E controls.' }).first();
    await expect(projectCard).toBeVisible();
    await projectCard.getByRole('button', { name: 'Switch' }).click();
    await expect(projectCard).toContainText('Current');

    await projectCard.getByRole('button', { name: `Edit ${projectName}` }).click();
    await expect(page.getByRole('heading', { name: 'Edit Project' })).toBeVisible();
    const editDialog = page.getByRole('heading', { name: 'Edit Project' }).locator('..').locator('..');
    await editDialog.locator('input[type="text"]').fill(updatedName);
    await editDialog.getByRole('button', { name: 'Save Changes' }).click();
    await expect(page.getByText(updatedName)).toBeVisible();

    const updatedCard = page.locator('div').filter({ hasText: updatedName }).filter({ hasText: 'Current' }).first();
    await updatedCard.getByRole('button', { name: `Delete ${updatedName}` }).click();
    await expect(page.getByRole('heading', { name: 'Delete Project?' })).toBeVisible();
    await page.getByRole('button', { name: 'Delete Project' }).click();
    await expect(page.getByText(updatedName)).toHaveCount(0);
    await guards.assertClean();
  });

  test('navigates primary sections from the sidebar', async ({ page }) => {
    const guards = await bootDashboard(page);

    await page.goto('/');
    await expectPageReady(page, 'Quality Overview');

    await page.getByRole('navigation').getByRole('link', { name: 'API Testing' }).click();
    await page.waitForURL('**/api-testing');
    await expectPageReady(page, 'API Testing');

    await page.getByRole('navigation').getByRole('link', { name: 'Projects' }).click();
    await page.waitForURL('**/projects');
    await expectPageReady(page, 'Projects');

    await page.getByRole('navigation').getByRole('link', { name: 'Settings' }).click();
    await page.waitForURL('**/settings');
    await expectPageReady(page, 'Settings');
    await guards.assertClean();
  });

  test('opens tabbed specialized testing workspaces', async ({ page }) => {
    const guards = await bootDashboard(page);

    await page.goto('/api-testing');
    await expectPageReady(page, 'API Testing');
    await page.getByRole('button', { name: /OpenAPI Import/ }).click();
    await expect(page.getByRole('heading', { name: 'Import OpenAPI / Swagger Specification' })).toBeVisible();
    await page.getByRole('button', { name: /Run History/ }).click();
    await expect(page.getByText('No test runs yet')).toBeVisible();

    await page.goto('/database-testing');
    await expectPageReady(page, 'Database Testing');
    for (const tab of ['Viewer', 'Analyzer', 'Specs', 'History', 'Dashboard']) {
      await page.getByRole('button', { name: new RegExp(`^${tab}$`) }).click();
    }
    await expect(page.getByRole('button', { name: 'Connections' })).toBeVisible();

    await page.goto('/llm-testing');
    await expectPageReady(page, 'LLM / AI Testing');
    for (const tab of ['Specs', 'Datasets', 'Run', 'Compare', 'History', 'Analytics', 'Prompts', 'Schedules', 'Providers']) {
      const tabButton = page.getByRole('tab', { name: tab });
      await tabButton.focus();
      await page.keyboard.press('Enter');
      await expect(tabButton).toHaveAttribute('data-state', 'active');
    }

    await page.goto('/load-testing');
    await expectPageReady(page, 'Load Testing');
    for (const tab of ['Scenarios', 'Scripts', 'Run History', 'Overview']) {
      await page.getByRole('button', { name: new RegExp(tab) }).click();
    }

    await page.goto('/security-testing');
    await expectPageReady(page, 'Security Testing');
    await expect(page.getByText(/Scan/i).first()).toBeVisible();
    await guards.assertClean();
  });

  test('creates a requirement and opens RTM from the requirements workspace', async ({ page }) => {
    const guards = await bootDashboard(page);

    await page.goto('/requirements');
    await expectPageReady(page, 'Requirements');
    await page.getByRole('button', { name: 'Add Requirement' }).click();
    await expect(page.getByRole('heading', { name: 'Add Requirement' })).toBeVisible();
    await page.getByPlaceholder('User can log in with email and password').fill('E2E user can authenticate');
    await page.getByPlaceholder('Detailed description...').fill('Created through the mocked UI smoke path.');
    await page.getByRole('button', { name: 'Create Requirement' }).click();

    await expect(page.getByRole('heading', { name: 'Add Requirement' })).toHaveCount(0);
    await page.getByRole('link', { name: /Open RTM/ }).first().click();
    await expectPageReady(page, 'RTM');
    await guards.assertClean();
  });

  test('starts and stops a recording dry-run path', async ({ page }) => {
    const guards = await bootDashboard(page);

    await page.goto('/recordings');
    await expectPageReady(page, 'Recording Mode');
    await expect(page.getByText('No recordings yet')).toBeVisible();
    const targetUrl = page.getByRole('textbox', { name: 'Target URL' });
    await targetUrl.fill('https://example.test/login');
    await page.getByRole('textbox', { name: 'Spec Name' }).fill('E2E recording');
    await expect(targetUrl).toHaveValue('https://example.test/login');
    await expect(page.getByRole('button', { name: 'Start Recording' })).toBeEnabled();
    await page.getByRole('button', { name: 'Start Recording' }).click();
    await expect(page.getByText(/recording/i).first()).toBeVisible();
    await page.getByRole('button', { name: 'Stop' }).click();
    await expect(page.getByText(/stopped|import/i).first()).toBeVisible();
    await guards.assertClean();
  });
});
