import { expect, test } from '@playwright/test';
import {
  APP_BASE,
  attachUiErrorGuards,
  authenticateDashboard,
  expectPageReady,
  installDashboardApiMocks,
} from './helpers/dashboard-mocks';

const dashboardRoutes: Array<{ path: string; heading: string | RegExp }> = [
  { path: '/', heading: 'Quality Overview' },
  { path: '/dashboard', heading: 'Reporting Dashboard' },
  { path: '/specs', heading: 'Test Specs' },
  { path: '/specs/new', heading: 'New Test Spec' },
  { path: '/runs', heading: 'Test Runs' },
  { path: '/regression', heading: 'Regression Testing' },
  { path: '/regression/batches', heading: 'Batch Reports' },
  { path: '/exploration', heading: 'Discovery' },
  { path: '/autopilot', heading: /Auto\s*Pilot/i },
  { path: '/autonomous', heading: 'Autonomous Missions' },
  { path: '/requirements', heading: 'Requirements' },
  { path: '/rtm', heading: 'RTM' },
  { path: '/coverage', heading: 'Coverage Intelligence' },
  { path: '/memory', heading: 'Memory' },
  { path: '/agents', heading: 'Autonomous Agents' },
  { path: '/prd', heading: 'PRD Processing' },
  { path: '/api-testing', heading: 'API Testing' },
  { path: '/load-testing', heading: 'Load Testing' },
  { path: '/security-testing', heading: 'Security Testing' },
  { path: '/database-testing', heading: 'Database Testing' },
  { path: '/llm-testing', heading: 'LLM / AI Testing' },
  { path: '/schedules', heading: 'Schedules' },
  { path: '/ci-cd', heading: 'CI/CD Pipelines' },
  { path: '/analytics', heading: 'Test Analytics' },
  { path: '/templates', heading: 'Templates' },
  { path: '/templates/new', heading: 'New Template' },
  { path: '/test-data', heading: 'Test Data' },
  { path: '/workflow', heading: 'Custom Workflows' },
  { path: '/recordings', heading: 'Recording Mode' },
  { path: '/pr-advisor', heading: 'PR Advisor' },
  { path: '/projects', heading: 'Projects' },
  { path: '/settings', heading: 'Settings' },
  { path: '/assistant', heading: 'AI Assistant' },
  { path: '/admin/users', heading: 'User Management' },
  { path: '/admin/workflow-step-types', heading: 'Workflow Step Types' },
];

test.describe('Dashboard route smoke', () => {
  test.use({ baseURL: APP_BASE });

  for (const route of dashboardRoutes) {
    test(`${route.path} loads its primary UI`, async ({ page }) => {
      await authenticateDashboard(page);
      await installDashboardApiMocks(page);
      const guards = attachUiErrorGuards(page);

      const response = await page.goto(route.path);
      expect(response?.status(), `${route.path} should not return a server error`).toBeLessThan(500);
      await expectPageReady(page, route.heading);
      await expect(page.locator('body')).not.toContainText('Application error');
      await guards.assertClean();
    });
  }

  test('auth routes render without an existing session', async ({ page }) => {
    await installDashboardApiMocks(page);
    const guards = attachUiErrorGuards(page);

    await page.goto('/login');
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible();

    await page.goto('/register');
    await expect(page.getByRole('heading', { name: 'Create an account' })).toBeVisible();
    await expect(page.getByLabel(/Full Name/)).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Confirm Password')).toBeVisible();

    await guards.assertClean();
  });

  test('protected dashboard routes redirect unauthenticated users to login', async ({ page }) => {
    await installDashboardApiMocks(page);

    await page.goto('/settings');

    await expect(page).toHaveURL(/\/login\?returnTo=%2Fsettings$/);
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  });
});
