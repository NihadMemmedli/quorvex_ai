import { expect, test } from '@playwright/test';

test.describe('company external nginx deployment', () => {
  test.skip(process.env.PLAYWRIGHT_COMPANY_EDGE_SMOKE !== 'true', 'Company edge smoke requires the rehearsal nginx proxy.');

  test('keeps browser traffic same-origin and proxies live browser websocket', async ({ page, baseURL }) => {
    test.skip(!baseURL, 'BASE_URL must point at the company-nginx rehearsal URL.');

    const edge = new URL(baseURL!);
    const directRequests: string[] = [];
    const directWebSockets: string[] = [];

    const isDirectRuntimeUrl = (rawUrl: string) => {
      const url = new URL(rawUrl);
      const isLocalHost = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
      const isDirectAppPort = url.port === '8001' || url.port === '6080';
      return isDirectAppPort || (url.hostname !== edge.hostname && isLocalHost);
    };

    page.on('request', request => {
      if (isDirectRuntimeUrl(request.url())) {
        directRequests.push(request.url());
      }
    });
    page.on('websocket', websocket => {
      if (isDirectRuntimeUrl(websocket.url())) {
        directWebSockets.push(websocket.url());
      }
    });

    const loginResponse = await page.goto('/login', { waitUntil: 'domcontentloaded' });
    expect(loginResponse?.status(), 'login route should load through the external edge').toBeLessThan(500);
    await expect(page.locator('body')).toBeVisible();

    const proxyHealth = await page.evaluate(async () => {
      const response = await fetch('/backend-proxy/health');
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      return {
        ok: response.ok,
        status: response.status,
        url: response.url,
        payload,
      };
    });

    expect(proxyHealth.ok, `backend proxy failed with ${proxyHealth.status}`).toBe(true);
    expect(proxyHealth.url).toContain('/backend-proxy/health');

    const websocketUrl = `${edge.protocol === 'https:' ? 'wss:' : 'ws:'}//${edge.host}/websockify`;
    const websocketResult = await page.evaluate((url) => {
      return new Promise<string>((resolve) => {
        const socket = new WebSocket(url);
        const timeout = window.setTimeout(() => {
          socket.close();
          resolve('timeout');
        }, 10_000);

        socket.addEventListener('open', () => {
          window.clearTimeout(timeout);
          socket.close();
          resolve('open');
        });
        socket.addEventListener('error', () => {
          window.clearTimeout(timeout);
          resolve('error');
        });
      });
    }, websocketUrl);

    expect(websocketResult).toBe('open');
    expect(directRequests, 'browser-visible requests must not hit direct backend/VNC ports').toEqual([]);
    expect(directWebSockets, 'browser-visible websockets must not hit direct VNC ports').toEqual([]);
  });
});
