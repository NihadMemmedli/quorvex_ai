import { expect, test } from '@playwright/test';
import {
  APP_BASE,
  attachUiErrorGuards,
  authenticateDashboard,
  installDashboardApiMocks,
} from './helpers/dashboard-mocks';

test.describe('AutoPilot live checklist', () => {
  test.use({ baseURL: APP_BASE });

  test('renders persisted checklist rows in sequence order', async ({ page }) => {
    await authenticateDashboard(page);
    await page.addInitScript(() => {
      Object.defineProperty(window, 'EventSource', { value: undefined });
    });
    await installDashboardApiMocks(page);
    const guards = attachUiErrorGuards(page);

    await page.goto('/autopilot?sessionId=autopilot-e2e');

    const panel = page.getByLabel('AutoPilot live checklist');
    await expect(panel.getByText('Agent-Filled Live Checklist')).toBeVisible();
    await expect(panel.getByText('0/2 done')).toBeVisible();
    await expect(panel.getByText('Polling fallback')).toBeVisible();

    const rows = panel.locator('.autopilot-checklist-row');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText('Exploration phase');
    await expect(rows.nth(0)).toContainText('Exploring first URL');
    await expect(rows.nth(1)).toContainText('Question: review requirements');
    await expect(rows.nth(1)).toContainText('Proceed with all requirements?');

    await expect(panel).toBeVisible();
    await expect(page.getByText('Live Browser', { exact: true }).first()).toBeVisible();
    await guards.assertClean();
  });
});
