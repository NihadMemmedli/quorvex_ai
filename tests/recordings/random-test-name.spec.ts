import { test, expect } from '@playwright/test';

test.use({
  serviceWorkers: 'block',
  viewport: {
    height: 720,
    width: 1280
  }
});

test('test', async ({ page }) => {
  await page.routeFromHAR('/app/runs/recordings/recording_20260518_144353_6c3141aa/recording.har');
  await page.goto('https://my.gov.az/');
  await page.getByRole('button', { name: 'Daxil ol' }).click();
  await page.getByRole('button', { name: 'Digər üsullar' }).click();
  await page.locator('.panel-left').first().click();
  await page.getByText('Geri').click();
  await page.locator('div').filter({ hasText: /^EN$/ }).click();
});