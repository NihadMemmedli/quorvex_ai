/**
 * Playwright Skill Helpers
 *
 * Utility functions for common browser automation patterns.
 * These are automatically available in skill scripts.
 */

/**
 * Safe click with auto-wait and scroll into view
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} selector - Element selector
 * @param {Object} options - Click options
 * @returns {Promise<boolean>} - True if click succeeded
 */
export async function safeClick(page, selector, options = {}) {
  const { timeout = 5000, force = false } = options;

  try {
    const element = page.locator(selector);
    await element.waitFor({ state: 'visible', timeout });
    await element.scrollIntoViewIfNeeded();
    await element.click({ force, timeout });
    return true;
  } catch (error) {
    console.error(`[safeClick] Failed to click "${selector}": ${error.message}`);
    return false;
  }
}

/**
 * Safe type with clear and retry
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} selector - Input selector
 * @param {string} text - Text to type
 * @param {Object} options - Type options
 * @returns {Promise<boolean>} - True if type succeeded
 */
export async function safeType(page, selector, text, options = {}) {
  const { timeout = 5000, clear = true, delay = 0 } = options;

  try {
    const element = page.locator(selector);
    await element.waitFor({ state: 'visible', timeout });

    if (clear) {
      await element.clear();
    }

    await element.type(text, { delay });
    return true;
  } catch (error) {
    console.error(`[safeType] Failed to type in "${selector}": ${error.message}`);
    return false;
  }
}

/**
 * Retry an async operation with exponential backoff
 *
 * @param {Function} fn - Async function to retry
 * @param {Object} options - Retry options
 * @returns {Promise<any>} - Result of the function
 */
export async function retry(fn, options = {}) {
  const { attempts = 3, delay = 1000, backoff = 2, onError = null } = options;

  let lastError;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (onError) {
        onError(error, i + 1);
      }

      if (i < attempts - 1) {
        const waitTime = delay * Math.pow(backoff, i);
        console.log(`[retry] Attempt ${i + 1}/${attempts} failed, waiting ${waitTime}ms...`);
        await new Promise((resolve) => setTimeout(resolve, waitTime));
      }
    }
  }

  throw lastError;
}

/**
 * Wait for network to be idle (no pending requests)
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {Object} options - Wait options
 * @returns {Promise<void>}
 */
export async function waitForNetworkIdle(page, options = {}) {
  const { timeout = 10000, idleTime = 500 } = options;

  await page.waitForLoadState('networkidle', { timeout });

  // Additional wait for any delayed requests
  await new Promise((resolve) => setTimeout(resolve, idleTime));
}

/**
 * Take a screenshot with timestamp
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} name - Screenshot name (without extension)
 * @param {Object} options - Screenshot options
 * @returns {Promise<string>} - Screenshot file path
 */
export async function screenshot(page, name, options = {}) {
  const { fullPage = false, dir = '/tmp/playwright-screenshots' } = options;

  const timestamp = Date.now();
  const path = `${dir}/${name}-${timestamp}.png`;

  await page.screenshot({ path, fullPage });
  console.log(`[screenshot] Saved: ${path}`);

  return path;
}

/**
 * Wait for element to disappear
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} selector - Element selector
 * @param {Object} options - Wait options
 * @returns {Promise<boolean>} - True if element disappeared
 */
export async function waitForHidden(page, selector, options = {}) {
  const { timeout = 10000 } = options;

  try {
    await page.locator(selector).waitFor({ state: 'hidden', timeout });
    return true;
  } catch (error) {
    console.error(`[waitForHidden] Element still visible: "${selector}"`);
    return false;
  }
}

/**
 * Extract text from multiple elements
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} selector - Element selector (matches multiple)
 * @returns {Promise<string[]>} - Array of text contents
 */
export async function extractTexts(page, selector) {
  const elements = page.locator(selector);
  return await elements.allTextContents();
}

/**
 * Wait for URL to match pattern
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string|RegExp} pattern - URL pattern
 * @param {Object} options - Wait options
 * @returns {Promise<boolean>} - True if URL matched
 */
export async function waitForUrl(page, pattern, options = {}) {
  const { timeout = 10000 } = options;

  try {
    await page.waitForURL(pattern, { timeout });
    return true;
  } catch (error) {
    console.error(`[waitForUrl] URL did not match pattern: ${pattern}`);
    return false;
  }
}

/**
 * Fill a form with multiple fields
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {Object} fields - Object with selector:value pairs
 * @param {Object} options - Fill options
 * @returns {Promise<boolean>} - True if all fields filled successfully
 */
export async function fillForm(page, fields, options = {}) {
  const { timeout = 5000 } = options;

  for (const [selector, value] of Object.entries(fields)) {
    const success = await safeType(page, selector, value, { timeout });
    if (!success) {
      return false;
    }
  }

  return true;
}

/**
 * Intercept network requests
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} urlPattern - URL pattern to match
 * @param {Function} handler - Request handler function
 * @returns {Promise<Function>} - Cleanup function to remove handler
 */
export async function interceptRequests(page, urlPattern, handler) {
  await page.route(urlPattern, handler);

  return async () => {
    await page.unroute(urlPattern);
  };
}

/**
 * Mock API response
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @param {string} urlPattern - URL pattern to mock
 * @param {Object} response - Mock response { status, body, headers }
 * @returns {Promise<Function>} - Cleanup function
 */
export async function mockApi(page, urlPattern, response) {
  const { status = 200, body = {}, headers = { 'Content-Type': 'application/json' } } = response;

  return await interceptRequests(page, urlPattern, async (route) => {
    await route.fulfill({
      status,
      body: typeof body === 'string' ? body : JSON.stringify(body),
      headers,
    });
  });
}

/**
 * Get performance metrics
 *
 * @param {import('playwright').Page} page - Playwright page object
 * @returns {Promise<Object>} - Performance metrics
 */
export async function getPerformanceMetrics(page) {
  const metrics = await page.evaluate(() => {
    const timing = performance.timing;
    const navigation = performance.getEntriesByType('navigation')[0];

    return {
      loadTime: timing.loadEventEnd - timing.navigationStart,
      domContentLoaded: timing.domContentLoadedEventEnd - timing.navigationStart,
      firstPaint: navigation?.startTime || 0,
      transferSize: navigation?.transferSize || 0,
    };
  });

  return metrics;
}
