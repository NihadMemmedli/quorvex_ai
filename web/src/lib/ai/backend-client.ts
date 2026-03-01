/**
 * Server-side fetch wrapper for calling the FastAPI backend from Next.js API routes.
 * Forwards auth tokens and handles errors gracefully.
 */

const INTERNAL_API_URL = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

interface BackendRequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  authToken?: string;
  projectId?: string;
}

export interface BackendResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  status: number;
}

export async function backendFetch<T = unknown>(
  path: string,
  options: BackendRequestOptions = {}
): Promise<BackendResponse<T>> {
  const { method = 'GET', body, headers = {}, authToken, projectId } = options;

  const url = `${INTERNAL_API_URL}${path.startsWith('/') ? '' : '/'}${path}`;

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  };

  if (authToken) {
    requestHeaders['Authorization'] = `Bearer ${authToken}`;
  }

  if (projectId) {
    requestHeaders['X-Project-ID'] = projectId;
  }

  try {
    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(30000),
    });

    if (!response.ok) {
      let errorMessage = `Backend returned ${response.status}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        // ignore parse errors
      }
      return { ok: false, error: errorMessage, status: response.status };
    }

    const data = await response.json() as T;
    return { ok: true, data, status: response.status };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Backend unreachable';
    return { ok: false, error: message, status: 0 };
  }
}
