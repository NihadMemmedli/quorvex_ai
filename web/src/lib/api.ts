/**
 * Centralized API configuration for frontend-to-backend communication.
 *
 * Uses NEXT_PUBLIC_API_URL environment variable when set.
 * Without an override, resolves the backend host from the current browser host.
 */

const ENV_API_BASE = process.env.NEXT_PUBLIC_API_URL;

function getDefaultApiBase(): string {
  if (typeof window !== 'undefined') {
    const { protocol, hostname } = window.location;
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return '/backend-proxy';
    }
    return `${protocol}//${hostname}:8001`;
  }

  return 'http://localhost:8001';
}

function getApiBase(): string {
  if (typeof window !== 'undefined') {
    const { hostname } = window.location;
    const envPointsToLocalhost = Boolean(ENV_API_BASE && /\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(ENV_API_BASE));
    if (hostname !== 'localhost' && hostname !== '127.0.0.1' && (!ENV_API_BASE || envPointsToLocalhost)) {
      return '/backend-proxy';
    }
  }
  return ENV_API_BASE || getDefaultApiBase();
}

export const API_BASE = getApiBase();

/**
 * Constructs a full API URL from a path.
 *
 * @param path - The API path (e.g., '/exploration/start' or 'exploration/start')
 * @returns Full URL with API_BASE prefix
 */
export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
}
