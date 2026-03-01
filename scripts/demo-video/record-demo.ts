/**
 * Playwright Demo Recording Script
 * Records a guided tour of the AI-powered test automation dashboard.
 *
 * Usage:
 *   npx playwright test scripts/demo-video/record-demo.ts
 *   # or directly:
 *   npx tsx scripts/demo-video/record-demo.ts
 *
 * Prerequisites:
 *   - Dashboard running on localhost:3000 (make dev or make prod-dev)
 *   - Some demo data populated (exploration sessions, test runs, etc.)
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import * as path from 'path';
import * as fs from 'fs';

const BASE_URL = process.env.DEMO_BASE_URL || 'http://localhost:3000';
const OUTPUT_DIR = path.join(__dirname, 'output');
const SCREENSHOT_DIR = path.join(OUTPUT_DIR, 'screenshots');

// Timing constants (milliseconds)
const PACE = {
  pageLoad: 2000,       // Wait after navigation for content to render
  sectionPause: 1500,   // Pause between sections
  quickGlance: 800,     // Quick view of an element
  scrollPause: 600,     // Pause during scroll
  typingDelay: 50,      // Delay between keystrokes
  heroFeature: 3000,    // Longer pause on hero features
};

async function ensureOutputDirs() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function smoothScroll(page: Page, distance: number, duration: number = 1000) {
  const steps = 20;
  const stepDistance = distance / steps;
  const stepDelay = duration / steps;
  for (let i = 0; i < steps; i++) {
    await page.evaluate((d) => window.scrollBy(0, d), stepDistance);
    await page.waitForTimeout(stepDelay);
  }
}

async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: false,
  });
}

async function navigateTo(page: Page, urlPath: string, waitMs: number = PACE.pageLoad) {
  await page.goto(`${BASE_URL}${urlPath}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(waitMs);
}

async function main() {
  await ensureOutputDirs();

  console.log('🎬 Starting demo recording...');
  console.log(`   Base URL: ${BASE_URL}`);
  console.log(`   Output:   ${OUTPUT_DIR}`);

  const browser: Browser = await chromium.launch({
    headless: true,
    args: ['--disable-gpu', '--no-sandbox'],
  });

  const context: BrowserContext = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: {
      dir: OUTPUT_DIR,
      size: { width: 1920, height: 1080 },
    },
    colorScheme: 'dark',
    deviceScaleFactor: 1,
  });

  const page: Page = await context.newPage();

  try {
    // =========================================================
    // HOOK (0-5s): Quick flash of Auto Pilot
    // =========================================================
    console.log('📍 Section: Hook — Auto Pilot flash');
    await navigateTo(page, '/autopilot');
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '00-hook-autopilot');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // ACT 1 (5-12s): Dashboard overview with metrics
    // =========================================================
    console.log('📍 Section: Act 1 — Dashboard overview');
    await navigateTo(page, '/dashboard');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '01-dashboard-overview');

    // Scroll down to show charts
    await smoothScroll(page, 400, 1200);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '01-dashboard-charts');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // ACT 2 (12-25s): AI Exploration
    // =========================================================
    console.log('📍 Section: Act 2 — AI Exploration');
    await navigateTo(page, '/exploration');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '02-exploration-sessions');

    // Try clicking on a session to show details
    const sessionRow = page.locator('table tbody tr, [class*="card"], [class*="session"]').first();
    if (await sessionRow.isVisible({ timeout: 2000 }).catch(() => false)) {
      await sessionRow.click();
      await page.waitForTimeout(PACE.pageLoad);
      await screenshot(page, '02-exploration-detail');
    }

    // Show discovered flows
    await smoothScroll(page, 300, 800);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '02-exploration-flows');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // ACT 3 (25-45s): Auto Pilot — HERO FEATURE
    // =========================================================
    console.log('📍 Section: Act 3 — Auto Pilot (hero)');
    await navigateTo(page, '/autopilot');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '03-autopilot-main');

    // Scroll to show the pipeline phases
    await smoothScroll(page, 300, 1000);
    await page.waitForTimeout(PACE.heroFeature);
    await screenshot(page, '03-autopilot-phases');

    // Scroll further to show results
    await smoothScroll(page, 400, 1000);
    await page.waitForTimeout(PACE.sectionPause);
    await screenshot(page, '03-autopilot-results');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // ACT 4 (45-65s): Testing Arsenal — Quick cuts
    // =========================================================
    console.log('📍 Section: Act 4 — Testing Arsenal');

    // API Testing
    await navigateTo(page, '/api-testing');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '04-api-testing');
    await page.waitForTimeout(PACE.quickGlance);

    // Load Testing
    await navigateTo(page, '/load-testing');
    await page.waitForTimeout(PACE.pageLoad);
    await smoothScroll(page, 200, 600);
    await screenshot(page, '04-load-testing');
    await page.waitForTimeout(PACE.quickGlance);

    // Security Testing
    await navigateTo(page, '/security-testing');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '04-security-testing');
    await page.waitForTimeout(PACE.quickGlance);

    // Database Testing
    await navigateTo(page, '/database-testing');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '04-database-testing');
    await page.waitForTimeout(PACE.quickGlance);

    // LLM Testing
    await navigateTo(page, '/llm-testing');
    await page.waitForTimeout(PACE.pageLoad);
    await smoothScroll(page, 200, 600);
    await screenshot(page, '04-llm-testing');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // ACT 5 (65-80s): Enterprise features
    // =========================================================
    console.log('📍 Section: Act 5 — Enterprise features');

    // CI/CD
    await navigateTo(page, '/ci-cd');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '05-cicd');
    await page.waitForTimeout(PACE.quickGlance);

    // RTM / Coverage
    await navigateTo(page, '/coverage');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '05-coverage-rtm');
    await page.waitForTimeout(PACE.quickGlance);

    // Regression
    await navigateTo(page, '/regression');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '05-regression');
    await page.waitForTimeout(PACE.quickGlance);

    // Schedules
    await navigateTo(page, '/schedules');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '05-schedules');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // CLOSE (80-90s): Dashboard + AI Assistant
    // =========================================================
    console.log('📍 Section: Close — AI Assistant');
    await navigateTo(page, '/assistant');
    await page.waitForTimeout(PACE.pageLoad);
    await screenshot(page, '06-ai-assistant');

    // Back to dashboard for final shot
    await navigateTo(page, '/dashboard');
    await page.waitForTimeout(PACE.heroFeature);
    await screenshot(page, '06-final-dashboard');

    console.log('✅ Recording complete!');
  } catch (error) {
    console.error('❌ Recording failed:', error);
    await screenshot(page, 'error-state');
  } finally {
    await page.close();
    await context.close();
    await browser.close();
  }

  // Rename the video file to a predictable name
  const videoFiles = fs.readdirSync(OUTPUT_DIR).filter(f => f.endsWith('.webm'));
  if (videoFiles.length > 0) {
    const latestVideo = videoFiles.sort().pop()!;
    const src = path.join(OUTPUT_DIR, latestVideo);
    const dest = path.join(OUTPUT_DIR, 'recording.webm');
    if (fs.existsSync(dest)) fs.unlinkSync(dest);
    fs.renameSync(src, dest);
    console.log(`🎥 Video saved: ${dest}`);
  }

  console.log(`📸 Screenshots saved: ${SCREENSHOT_DIR}/`);
}

main().catch(console.error);
