import { test, expect } from '@playwright/test';

test.use({
  serviceWorkers: 'block',
  viewport: {
    height: 720,
    width: 1280
  }
});

test('test', async ({ page }) => {
  await page.routeFromHAR('/app/runs/recordings/recording_20260530_092001_a224a61e/recording.har');
  await page.goto('https://my.gov.az/serviceCategories');
  await page.getByRole('link', { name: 'Medicine Səhiyyə' }).click();
  await page.getByRole('link', { name: 'Rentgen kabinetinin istismarı' }).click();
  await page.getByRole('link', { name: 'Tikinti üçün torpaq sahəsinin' }).click();
  await page.getByRole('button', { name: 'MÜRACİƏT ET' }).first().click();
  await page.getByRole('button', { name: 'DAXİL OLUN ' }).click();
  await page.goto('https://mygovid.gov.az/auth');
  await page.getByRole('button', { name: 'Digər üsullar' }).click();
  await page.getByText('İdentifikasiya nömrəsi ilə').click();
});