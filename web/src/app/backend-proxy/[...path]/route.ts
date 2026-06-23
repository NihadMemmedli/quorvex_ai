/**
 * Catch-all API proxy route.
 * Proxies all requests from /backend-proxy/* to the backend API server.
 * This eliminates CORS and port accessibility issues by routing
 * all API calls through the same origin as the frontend.
 */

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
const PROXY_TIMEOUT_MS = Number(process.env.BACKEND_PROXY_TIMEOUT_MS || process.env.API_TIMEOUT_MS || 620_000);

function createBackendDispatcher(): unknown {
  try {
    const requireUndici = eval('require') as NodeRequire;
    const { Agent } = requireUndici('undici');
    return new Agent({
      headersTimeout: PROXY_TIMEOUT_MS,
      bodyTimeout: PROXY_TIMEOUT_MS,
    });
  } catch {
    return undefined;
  }
}

const BACKEND_DISPATCHER = createBackendDispatcher();

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
  // The request body is re-materialized below, so let fetch calculate this.
  headers.delete('content-length');
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

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

    let response: Response;
    try {
      response = await fetch(targetUrl, {
        method: request.method,
        headers,
        body,
        signal: controller.signal,
        dispatcher: BACKEND_DISPATCHER,
      } as RequestInit & { dispatcher?: unknown });
    } finally {
      clearTimeout(timeoutId);
    }

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
