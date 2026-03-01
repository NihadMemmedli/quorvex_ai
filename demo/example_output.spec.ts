import { test, expect } from '@playwright/test';

test.describe('Login Form Validation', () => {
  test('logs in with valid credentials and logs out', async ({ page }) => {
    // Navigate to the login page
    await test.step('Navigate to login page', async () => {
      await page.goto('https://the-internet.herokuapp.com/login');
    });

    // Verify the page heading
    await test.step('Verify Login Page heading is visible', async () => {
      await expect(page.getByRole('heading', { name: 'Login Page' })).toBeVisible();
    });

    // Fill in credentials
    await test.step('Enter username', async () => {
      await page.getByLabel('Username').fill('tomsmith');
    });

    await test.step('Enter password', async () => {
      await page.getByLabel('Password').fill('SuperSecretPassword!');
    });

    // Submit the form
    await test.step('Click Login button', async () => {
      await page.getByRole('button', { name: 'Login' }).click();
    });

    // Verify successful login
    await test.step('Verify Secure Area heading is visible', async () => {
      await expect(page.getByRole('heading', { name: 'Secure Area' })).toBeVisible();
    });

    await test.step('Verify success flash message', async () => {
      await expect(page.locator('#flash')).toContainText('You logged into a secure area!');
    });

    // Log out
    await test.step('Click Logout button', async () => {
      await page.getByRole('link', { name: 'Logout' }).click();
    });

    // Verify redirect to login page
    await test.step('Verify redirect to login page', async () => {
      await expect(page.getByRole('heading', { name: 'Login Page' })).toBeVisible();
    });
  });
});
