import { defineConfig, devices } from '@playwright/test';

const startWebServer = process.env.PLAYWRIGHT_START_WEB_SERVER === 'true';
const baseURL = process.env.BASE_URL || 'http://localhost:3000';
const parsedBaseURL = new URL(baseURL);
const webServerPort = process.env.PLAYWRIGHT_WEB_PORT || parsedBaseURL.port || '3000';
const webServerHost = process.env.PLAYWRIGHT_WEB_HOST || '0.0.0.0';
const playwrightHeadless = process.env.PLAYWRIGHT_HEADLESS?.toLowerCase();
const genericHeadless = process.env.HEADLESS?.toLowerCase();
const runHeaded = playwrightHeadless === 'false' || genericHeadless === 'false';
const configuredWorkers = parseInt(process.env.PLAYWRIGHT_WORKERS || '4', 10);

/**
 * Playwright Test Configuration
 */
export default defineConfig({
  testDir: './tests',
  testMatch: ['generated/**/*.spec.ts', 'e2e/**/*.spec.ts'],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: runHeaded ? 1 : configuredWorkers,
  reporter: 'list',

  use: {
    baseURL: process.env.BASE_URL || undefined,
    headless: runHeaded ? false : undefined,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],

  webServer: startWebServer
    ? {
        command: `npm --prefix web run dev -- -H ${webServerHost} -p ${webServerPort}`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : undefined,
});
