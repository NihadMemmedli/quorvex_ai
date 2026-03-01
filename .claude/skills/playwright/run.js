#!/usr/bin/env node
/**
 * Playwright Skill Runner
 *
 * Universal executor for Playwright scripts.
 * Handles browser lifecycle, environment configuration, and output capture.
 *
 * Usage:
 *   node run.js <script-path>        # Execute a script file
 *   node run.js --code "<code>"      # Execute inline code
 *   node run.js --test               # Run self-test
 */

import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Configuration from environment
const config = {
  headless: process.env.HEADLESS === 'true' || process.env.PLAYWRIGHT_HEADLESS === 'true',
  slowMo: parseInt(process.env.SLOW_MO || '0', 10),
  timeout: parseInt(process.env.SKILL_TIMEOUT || '30000', 10),
  screenshotDir: process.env.SCREENSHOT_DIR || '/tmp/playwright-screenshots',
  viewport: {
    width: parseInt(process.env.VIEWPORT_WIDTH || '1280', 10),
    height: parseInt(process.env.VIEWPORT_HEIGHT || '720', 10),
  },
};

/**
 * Execute a Playwright script with managed browser lifecycle
 */
async function executeScript(scriptContent, scriptPath = null) {
  let browser = null;
  let context = null;
  let page = null;

  const startTime = Date.now();
  const result = {
    success: false,
    output: null,
    error: null,
    duration: 0,
    screenshots: [],
  };

  try {
    // Launch browser
    browser = await chromium.launch({
      headless: config.headless,
      slowMo: config.slowMo,
    });

    context = await browser.newContext({
      viewport: config.viewport,
      // Accept downloads
      acceptDownloads: true,
    });

    page = await context.newPage();

    // Add console listener for debugging
    page.on('console', (msg) => {
      const type = msg.type();
      const text = msg.text();
      if (type === 'error') {
        console.error(`[browser:error] ${text}`);
      } else if (type === 'warning') {
        console.warn(`[browser:warn] ${text}`);
      } else {
        console.log(`[browser:${type}] ${text}`);
      }
    });

    // Handle dialogs automatically
    page.on('dialog', async (dialog) => {
      console.log(`[dialog] ${dialog.type()}: ${dialog.message()}`);
      await dialog.accept();
    });

    // Import helpers and make them available
    const helpersPath = resolve(__dirname, 'lib/helpers.js');
    let helpers = {};
    if (existsSync(helpersPath)) {
      helpers = await import(helpersPath);
    }

    // Create execution context with globals
    const globals = {
      page,
      context,
      browser,
      config,
      ...helpers,
      // Utility for screenshots
      screenshot: async (name) => {
        const path = `${config.screenshotDir}/${name}-${Date.now()}.png`;
        await page.screenshot({ path });
        result.screenshots.push(path);
        console.log(`[screenshot] Saved: ${path}`);
        return path;
      },
    };

    // Build the async function wrapper
    // The script has access to page, context, browser, and helpers
    const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;

    // Wrap script to have access to all globals
    const wrappedScript = `
      const { page, context, browser, config, screenshot, safeClick, safeType, retry, waitForNetworkIdle } = globals;
      ${scriptContent}
    `;

    const scriptFn = new AsyncFunction('globals', wrappedScript);

    // Execute with timeout
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`Script timeout after ${config.timeout}ms`)), config.timeout);
    });

    const executionPromise = scriptFn(globals);

    result.output = await Promise.race([executionPromise, timeoutPromise]);
    result.success = true;

  } catch (error) {
    result.error = {
      message: error.message,
      stack: error.stack,
      name: error.name,
    };
    console.error(`[error] ${error.message}`);

    // Take error screenshot if page exists
    if (page) {
      try {
        const errorPath = `${config.screenshotDir}/error-${Date.now()}.png`;
        await page.screenshot({ path: errorPath });
        result.screenshots.push(errorPath);
        console.log(`[screenshot] Error screenshot: ${errorPath}`);
      } catch (screenshotError) {
        // Ignore screenshot errors
      }
    }
  } finally {
    result.duration = Date.now() - startTime;

    // Cleanup
    if (context) {
      await context.close().catch(() => {});
    }
    if (browser) {
      await browser.close().catch(() => {});
    }
  }

  return result;
}

/**
 * Self-test function
 */
async function selfTest() {
  console.log('Running Playwright Skill self-test...\n');

  const testScript = `
    await page.goto('https://example.com');
    const title = await page.title();
    console.log('Page loaded:', title);
    return { title };
  `;

  const result = await executeScript(testScript);

  if (result.success && result.output?.title === 'Example Domain') {
    console.log('\n[PASS] Self-test completed successfully');
    console.log(`  Duration: ${result.duration}ms`);
    console.log(`  Title: ${result.output.title}`);
    return 0;
  } else {
    console.error('\n[FAIL] Self-test failed');
    if (result.error) {
      console.error(`  Error: ${result.error.message}`);
    }
    return 1;
  }
}

/**
 * Main entry point
 */
async function main() {
  const args = process.argv.slice(2);

  if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
    console.log(`
Playwright Skill Runner

Usage:
  node run.js <script-path>        Execute a script file
  node run.js --code "<code>"      Execute inline code
  node run.js --test               Run self-test
  node run.js --help               Show this help

Environment:
  HEADLESS=true                    Run headless (default: false)
  SLOW_MO=100                      Slow down by 100ms
  SKILL_TIMEOUT=30000              Script timeout in ms
  SCREENSHOT_DIR=/tmp              Screenshot output directory

Examples:
  node run.js /tmp/my-script.js
  node run.js --code "await page.goto('https://example.com')"
  HEADLESS=true node run.js script.js
`);
    process.exit(0);
  }

  // Self-test mode
  if (args.includes('--test')) {
    const exitCode = await selfTest();
    process.exit(exitCode);
  }

  // Inline code mode
  const codeIndex = args.indexOf('--code');
  if (codeIndex !== -1) {
    const code = args[codeIndex + 1];
    if (!code) {
      console.error('Error: --code requires a script argument');
      process.exit(1);
    }

    const result = await executeScript(code);
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.success ? 0 : 1);
  }

  // Script file mode
  const scriptPath = args[0];
  if (!existsSync(scriptPath)) {
    console.error(`Error: Script not found: ${scriptPath}`);
    process.exit(1);
  }

  const scriptContent = readFileSync(scriptPath, 'utf-8');
  const result = await executeScript(scriptContent, scriptPath);

  // Output result as JSON
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.success ? 0 : 1);
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
