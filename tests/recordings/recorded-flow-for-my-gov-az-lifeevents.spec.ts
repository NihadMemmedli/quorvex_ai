import { test, expect } from '@playwright/test';

test.use({
  viewport: {
    height: 720,
    width: 1280
  }
});

test('test', async ({ page }) => {
  await page.goto('https://my.gov.az/lifeEvents');
  await page.getByRole('link', { name: 'Marriage Ailə qurmaq' }).click();
  await page.getByText('Ailə qurmaq, nikaha daxil').click();
  await page.getByRole('link', { name: 'Nikahın qeydiyyata alınmas' }).click();
  await page.locator('#infoSection').click();
  await page.getByRole('cell', { name: 'Bir nəfər üçün tibbi müayinəd' }).click();
  await page.getByRole('button', { name: 'MÜRACİƏT ET' }).first().click();
  await page.getByRole('button', { name: 'DAXİL OLUN ' }).click();
  await page.getByRole('button', { name: 'Digər üsullar' }).click();
  await page.getByText('SİMA İmza ilə Sistemə daxil').click();
  await page.locator('path').first().click();
});