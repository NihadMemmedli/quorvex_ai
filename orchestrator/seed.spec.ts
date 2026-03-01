import { test, expect } from '@playwright/test';

test('seed test for exploration', async ({ page }) => {
  // This is a minimal seed test to enable browser exploration
  await page.goto('https://my.gov.az');
  // Wait for page to load
  await page.waitForLoadState('networkidle');
});
