/**
 * Catch-all API proxy route.
 * Proxies all requests from /backend-proxy/* to the backend API server.
 * This eliminates CORS and port accessibility issues by routing
 * all API calls through the same origin as the frontend.
 */

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.INTERNAL_API_URL || 'http://backend:8001';

// Hop-by-hop headers that must not be forwarded by proxies
const HOP_BY_HOP_HEADERS = [
  'connection', 'keep-alive', 'upgrade', 'transfer-encoding',
  'te', 'trailer', 'proxy-authorization', 'proxy-authenticate',
];

async function proxyRequest(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const targetPath = path.join('/');
  const url = new URL(request.url);
  const targetUrl = `${BACKEND_URL}/${targetPath}${url.search}`;

  const headers = new Headers(request.headers);
  // Remove host header so the backend gets its own host
  headers.delete('host');
  // Remove hop-by-hop headers (not valid to forward through a proxy)
  for (const h of HOP_BY_HOP_HEADERS) {
    headers.delete(h);
  }
  // Forward the original client IP
  headers.set('X-Forwarded-For', request.headers.get('x-forwarded-for') || '');
  headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''));

  try {
    const body = request.method !== 'GET' && request.method !== 'HEAD'
      ? await request.arrayBuffer()
      : undefined;

    // 620s timeout (slightly longer than nginx proxy_read_timeout of 600s)
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 620_000);

    const response = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    const responseHeaders = new Headers(response.headers);
    // Remove transfer-encoding as Next.js handles this
    responseHeaders.delete('transfer-encoding');

    return new NextResponse(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error: unknown) {
    console.error(`Proxy error for ${targetUrl}:`, error);
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json(
        { detail: 'Backend request timed out' },
        { status: 504 }
      );
    }
    return NextResponse.json(
      { detail: 'Backend unavailable' },
      { status: 502 }
    );
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
export const PATCH = proxyRequest;
export const OPTIONS = proxyRequest;
