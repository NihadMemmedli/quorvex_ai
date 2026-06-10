import { afterEach, describe, expect, it, vi } from 'vitest';

async function importApiModule() {
  vi.resetModules();
  return import('./api');
}

describe('apiUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('uses localhost backend defaults for local dashboard sessions', async () => {
    const { apiUrl } = await importApiModule();

    expect(apiUrl('/health')).toBe('http://localhost:8001/health');
    expect(apiUrl('settings')).toBe('http://localhost:8001/settings');
  });

  it('honors NEXT_PUBLIC_API_URL when explicitly configured', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test');

    const { apiUrl } = await importApiModule();

    expect(apiUrl('/runs')).toBe('https://api.example.test/runs');
  });
});
