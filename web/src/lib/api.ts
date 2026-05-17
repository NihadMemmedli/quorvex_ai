/**
 * Centralized API configuration for frontend-to-backend communication.
 *
 * Uses NEXT_PUBLIC_API_URL environment variable when set.
 * Without an override, resolves the backend host from the current browser host.
 */

function getDefaultApiBase(): string {
  if (typeof window !== 'undefined') {
    const { protocol, hostname } = window.location;
    if (hostname === 'host.docker.internal') {
      return `${protocol}//host.docker.internal:8001`;
    }
    if (hostname === '127.0.0.1' || hostname === 'localhost') {
      return `${protocol}//${hostname}:8001`;
    }
  }

  return 'http://localhost:8001';
}

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || getDefaultApiBase();

/**
 * Constructs a full API URL from a path.
 *
 * @param path - The API path (e.g., '/exploration/start' or 'exploration/start')
 * @returns Full URL with API_BASE prefix
 */
export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
}
