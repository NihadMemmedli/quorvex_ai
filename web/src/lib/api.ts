/**
 * Centralized API configuration for frontend-to-backend communication.
 *
 * Uses NEXT_PUBLIC_API_URL environment variable when set (production),
 * falls back to localhost:8001 for local development.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

/**
 * Constructs a full API URL from a path.
 *
 * @param path - The API path (e.g., '/exploration/start' or 'exploration/start')
 * @returns Full URL with API_BASE prefix
 */
export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
}
