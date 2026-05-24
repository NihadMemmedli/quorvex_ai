/**
 * Playwright Demo Recording Script
 * Records a guided tour of the AI-powered test automation dashboard.
 *
 * Usage:
 *   npx playwright test scripts/demo-video/record-demo.ts
 *   # or directly:
 *   npx --yes tsx scripts/demo-video/record-demo.ts
 *   npx --yes tsx scripts/demo-video/record-demo.ts --base-url http://localhost:3000 --output-dir scripts/demo-video/output
 *
 * Prerequisites:
 *   - Dashboard running on localhost:3000 (make dev or make prod-dev)
 *   - Some demo data populated (exploration sessions, test runs, etc.)
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import * as path from 'path';
import * as fs from 'fs';

type CliOptions = {
  baseUrl: string;
  outputDir: string;
  authContext: string;
  mode: 'standard' | 'premium';
};

type DemoAuthContext = {
  refresh_token?: string;
  project_id?: string;
  conversation_id?: string;
  agent_run_id?: string;
  exploration_run_id?: string;
};

function parseCliOptions(): CliOptions {
  const options: CliOptions = {
    baseUrl: process.env.DEMO_BASE_URL || 'http://localhost:3000',
    outputDir: process.env.DEMO_OUTPUT_DIR || path.join(__dirname, 'output'),
    authContext: process.env.DEMO_AUTH_CONTEXT || path.join(process.env.DEMO_OUTPUT_DIR || path.join(__dirname, 'output'), 'demo-auth.json'),
    mode: process.env.DEMO_RECORDING_MODE === 'premium' ? 'premium' : 'standard',
  };

  const args = process.argv.slice(2);
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === '--base-url') {
      options.baseUrl = args[++index] || options.baseUrl;
    } else if (arg === '--output-dir') {
      options.outputDir = args[++index] || options.outputDir;
    } else if (arg === '--auth-context') {
      options.authContext = args[++index] || options.authContext;
    } else if (arg === '--mode') {
      const mode = args[++index] || options.mode;
      if (mode !== 'standard' && mode !== 'premium') {
        throw new Error(`Unknown recording mode: ${mode}`);
      }
      options.mode = mode;
    } else if (arg === '--premium') {
      options.mode = 'premium';
    } else if (arg === '--help' || arg === '-h') {
      console.log('Usage: npx --yes tsx scripts/demo-video/record-demo.ts [--base-url URL] [--output-dir DIR] [--auth-context FILE] [--mode standard|premium]');
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  options.outputDir = path.resolve(options.outputDir);
  options.authContext = path.resolve(options.authContext);
  return options;
}

const CLI_OPTIONS = parseCliOptions();
const BASE_URL = CLI_OPTIONS.baseUrl.replace(/\/$/, '');
const OUTPUT_DIR = CLI_OPTIONS.outputDir;
const SCREENSHOT_DIR = path.join(OUTPUT_DIR, 'screenshots');
const PROJECT_ROOT = path.resolve(__dirname, '../..');
const PREMIUM = CLI_OPTIONS.mode === 'premium';

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

function readAuthContext(): DemoAuthContext {
  if (!fs.existsSync(CLI_OPTIONS.authContext)) {
    return {};
  }
  return JSON.parse(fs.readFileSync(CLI_OPTIONS.authContext, 'utf-8'));
}

async function prepareBrowserContext(context: BrowserContext, auth: DemoAuthContext) {
  await context.addInitScript((state) => {
    if (state.refresh_token) {
      window.localStorage.setItem('refresh_token', state.refresh_token);
    }
    if (state.project_id) {
      window.localStorage.setItem('we-test-current-project-id', state.project_id);
    }
    if (state.conversation_id) {
      window.localStorage.setItem('chat-last-conversation-id', state.conversation_id);
    }
  }, auth);

  if (!PREMIUM) return;

  await context.addInitScript(() => {
    const installCursor = () => {
      if (!document.body) return;
      if (document.getElementById('quorvex-demo-cursor')) return;

      const style = document.createElement('style');
      style.textContent = `
        #quorvex-demo-cursor {
          position: fixed;
          left: 0;
          top: 0;
          width: 24px;
          height: 24px;
          border-radius: 999px;
          pointer-events: none;
          z-index: 2147483647;
          transform: translate3d(1540px, 140px, 0);
          transition: transform 520ms cubic-bezier(.2,.8,.2,1), opacity 180ms ease;
          opacity: .94;
          filter: drop-shadow(0 8px 18px rgba(0,0,0,.38));
        }
        #quorvex-demo-cursor::before {
          content: "";
          position: absolute;
          inset: 4px;
          border-radius: inherit;
          background: rgba(255,255,255,.96);
          border: 1px solid rgba(15,23,42,.36);
        }
        #quorvex-demo-cursor::after {
          content: "";
          position: absolute;
          inset: -10px;
          border: 2px solid rgba(96,165,250,.52);
          border-radius: inherit;
          opacity: 0;
          transform: scale(.5);
        }
        #quorvex-demo-cursor.demo-click::after {
          animation: quorvex-demo-click 380ms ease-out;
        }
        @keyframes quorvex-demo-click {
          0% { opacity: .9; transform: scale(.45); }
          100% { opacity: 0; transform: scale(1.65); }
        }
      `;
      document.documentElement.appendChild(style);

      const cursor = document.createElement('div');
      cursor.id = 'quorvex-demo-cursor';
      document.body.appendChild(cursor);

      (window as any).__quorvexDemoCursor = {
        moveTo(x: number, y: number, duration = 560) {
          cursor.style.transitionDuration = `${duration}ms, 180ms`;
          cursor.style.transform = `translate3d(${x}px, ${y}px, 0)`;
        },
        click() {
          cursor.classList.remove('demo-click');
          void cursor.offsetWidth;
          cursor.classList.add('demo-click');
        },
      };
    };

    installCursor();
    window.addEventListener('DOMContentLoaded', installCursor);
  });
}

async function navigateTo(page: Page, urlPath: string, waitMs: number = PACE.pageLoad) {
  await page.goto(`${BASE_URL}${urlPath}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(waitMs);
}

async function captureAgentBrowserArtifact(page: Page, auth: DemoAuthContext) {
  const runIds = [auth.agent_run_id, auth.exploration_run_id].filter(Boolean) as string[];
  if (!runIds.length) return;
  for (const runId of runIds) {
    const artifactDir = path.join(PROJECT_ROOT, 'runs', runId, 'artifacts');
    fs.mkdirSync(artifactDir, { recursive: true });
    await page.screenshot({
      path: path.join(artifactDir, 'browser-preview.png'),
      fullPage: false,
    });
  }
}

async function waitForApp(page: Page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(PACE.pageLoad);
}

async function moveCursor(page: Page, x: number, y: number, duration = 560) {
  if (!PREMIUM) return;
  await page.evaluate(
    ({ cursorX, cursorY, transitionMs }) => {
      (window as any).__quorvexDemoCursor?.moveTo(cursorX, cursorY, transitionMs);
    },
    { cursorX: x, cursorY: y, transitionMs: duration },
  );
  await page.waitForTimeout(duration + 90);
}

async function cursorClick(page: Page, x: number, y: number, duration = 520) {
  if (!PREMIUM) return;
  await moveCursor(page, x, y, duration);
  await page.evaluate(() => {
    (window as any).__quorvexDemoCursor?.click();
  });
  await page.waitForTimeout(260);
}

async function guidedScroll(page: Page, distance: number, duration = 1000) {
  if (PREMIUM) {
    await moveCursor(page, 1475, 830, 420);
  }
  await smoothScroll(page, distance, duration);
}

async function typeAssistantPrompt(page: Page) {
  if (!PREMIUM) return;

  const prompt = 'Create a focused checkout-risk QA agent and run the next review.';
  const input = page
    .locator('textarea, [contenteditable="true"], input[type="text"], input:not([type])')
    .last();

  if (!(await input.isVisible({ timeout: 2500 }).catch(() => false))) {
    return;
  }

  const box = await input.boundingBox();
  if (box) {
    await moveCursor(page, box.x + Math.min(box.width - 28, 220), box.y + box.height / 2, 520);
  }
  await input.click({ delay: 80 });
  await page.keyboard.type(prompt, { delay: 42 });
  await page.waitForTimeout(900);
}

async function main() {
  await ensureOutputDirs();
  const auth = readAuthContext();

  console.log('🎬 Starting demo recording...');
  console.log(`   Base URL: ${BASE_URL}`);
  console.log(`   Output:   ${OUTPUT_DIR}`);
  console.log(`   Mode:     ${CLI_OPTIONS.mode}`);

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
  await prepareBrowserContext(context, auth);

  const page: Page = await context.newPage();

  try {
    // =========================================================
    // HOOK (0-10s): Healthy command center, not failure-heavy data.
    // =========================================================
    console.log('📍 Section: Hook — Command Center');
    await navigateTo(page, '/');
    await waitForApp(page);
    await cursorClick(page, 360, 210);
    await screenshot(page, '00-command-center');
    await page.waitForTimeout(PACE.heroFeature);

    // =========================================================
    // ACT 1 (10-25s): Autonomous missions and work items.
    // =========================================================
    console.log('📍 Section: Act 1 — Autonomous missions');
    await navigateTo(page, '/autonomous');
    await waitForApp(page);
    await cursorClick(page, 510, 300);
    await screenshot(page, '01-autonomous-top');
    await guidedScroll(page, 460, 1600);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '01-autonomous-work-items');
    await guidedScroll(page, 540, 1600);
    await page.waitForTimeout(PACE.sectionPause);
    await screenshot(page, '01-autonomous-proposals');

    // =========================================================
    // ACT 2 (25-40s): Real browser exploration history.
    // =========================================================
    console.log('📍 Section: Act 2 — Discovery and live browser context');
    await navigateTo(page, '/exploration');
    await waitForApp(page);
    await cursorClick(page, 470, 315);
    await screenshot(page, '02-exploration-clean-history');
    await guidedScroll(page, 520, 1600);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '02-exploration-scroll');

    // Capture an app screenshot into agent artifacts so the LiveBrowserView
    // fallback shows real browser evidence if VNC is not available locally.
    await navigateTo(page, '/rtm');
    await waitForApp(page);
    await captureAgentBrowserArtifact(page, auth);

    // =========================================================
    // ACT 3 (40-58s): Live browser view and custom agent output.
    // =========================================================
    console.log('📍 Section: Act 3 — Live browser and custom agents');
    const liveRunId = auth.exploration_run_id || 'demo-agent-live-browser-preview';
    await navigateTo(page, `/agents?runId=${encodeURIComponent(liveRunId)}&demoCapture=1`);
    await waitForApp(page);
    await cursorClick(page, 1170, 360);
    await screenshot(page, '03-live-browser-view');
    await guidedScroll(page, 420, 1400);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '03-live-browser-activity');

    const reportRunId = auth.agent_run_id || 'demo-agent-checkout-risk-scout';
    await navigateTo(page, `/agents?runId=${encodeURIComponent(reportRunId)}`);
    await waitForApp(page);
    await cursorClick(page, 650, 330);
    await screenshot(page, '04-custom-agent-report');
    await guidedScroll(page, 520, 1500);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '04-custom-agent-findings');

    // =========================================================
    // ACT 4 (58-74s): RTM traceability with meaningful scroll.
    // =========================================================
    console.log('📍 Section: Act 4 — RTM coverage');
    await navigateTo(page, '/rtm');
    await waitForApp(page);
    await cursorClick(page, 730, 330);
    await screenshot(page, '05-rtm-top');
    await guidedScroll(page, 580, 1700);
    await page.waitForTimeout(PACE.quickGlance);
    await screenshot(page, '05-rtm-scroll');

    // =========================================================
    // ACT 5 (74-88s): Assistant powered workflow.
    // =========================================================
    console.log('📍 Section: Act 5 — AI Assistant workflow');
    await navigateTo(page, '/assistant');
    await waitForApp(page);
    await typeAssistantPrompt(page);
    await screenshot(page, '06-assistant-custom-agent');
    await page.waitForTimeout(PACE.sectionPause);

    // =========================================================
    // CLOSE (88-95s): Reporting proof.
    // =========================================================
    console.log('📍 Section: Close — Reporting proof');
    await navigateTo(page, '/dashboard');
    await waitForApp(page);
    await cursorClick(page, 520, 270);
    await screenshot(page, '07-reporting-dashboard');
    await guidedScroll(page, 520, 1700);
    await page.waitForTimeout(PACE.heroFeature);
    await screenshot(page, '07-reporting-scroll');

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
  const videoFiles = fs.readdirSync(OUTPUT_DIR)
    .filter(f => f.endsWith('.webm') && f !== 'recording.webm');
  if (videoFiles.length > 0) {
    const latestVideo = videoFiles.sort().pop()!;
    const src = path.join(OUTPUT_DIR, latestVideo);
    const dest = path.join(OUTPUT_DIR, 'recording.webm');
    if (src !== dest) {
      if (fs.existsSync(dest)) fs.unlinkSync(dest);
      fs.renameSync(src, dest);
    }
    console.log(`🎥 Video saved: ${dest}`);
  }

  console.log(`📸 Screenshots saved: ${SCREENSHOT_DIR}/`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
