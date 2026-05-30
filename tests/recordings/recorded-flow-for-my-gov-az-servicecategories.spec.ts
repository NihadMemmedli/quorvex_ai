import { test, expect } from '@playwright/test';

test.use({
  serviceWorkers: 'block',
  viewport: {
    height: 720,
    width: 1280
  }
});

test('test', async ({ page }) => {
  await page.routeFromHAR('/app/runs/recordings/recording_20260529_183357_1c8a1f6d/recording.har');
  await page.goto('https://my.gov.az/serviceCategories');
  await page.getByRole('button', { name: 'Bağla' }).click();
  await page.getByRole('button', { name: 'Daxil ol' }).click();
  await page.goto('https://mygovid.gov.az/auth');
  await page.getByRole('button', { name: 'Digər üsullar' }).click();
  await page.getByText('İdentifikasiya nömrəsi ilə').click();
  await page.getByRole('textbox', { name: 'İdentifikasiya nömrəsi' }).click();
  await page.getByRole('textbox', { name: 'İdentifikasiya nömrəsi' }).fill('1xck201');
  await page.getByRole('textbox', { name: 'İdentifikasiya nömrəsi' }).press('Tab');
  await page.getByRole('textbox', { name: 'Şifrə' }).fill('Generation77!!');
  await page.getByRole('textbox', { name: 'Şifrə' }).press('Alt+a');
  await page.getByRole('textbox', { name: 'Şifrə' }).press('Alt+a');
  await page.getByRole('textbox', { name: 'Şifrə' }).dblclick();
  await page.getByRole('textbox', { name: 'Şifrə' }).fill('Jj3630882!!!');
  await page.locator('div').filter({ hasText: /^Daxil ol$/ }).click();
  await page.goto('https://my.gov.az/serviceCategories');
  await page.getByRole('tab', { name: 'Qurumlar' }).click();
  await page.getByText('Dövlət Gömrük Komitəsi(10)10').click();
  await page.getByRole('link', { name: 'Mərkəzi Seçki Komissiyası Mə' }).click();
  await page.getByRole('link', { name: 'Onlayn müraciət' }).click();
  await page.getByRole('button', { name: 'MÜRACİƏT ET' }).first().click();
  await page.getByRole('button').nth(4).click();
});