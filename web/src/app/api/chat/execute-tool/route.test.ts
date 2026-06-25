import { beforeEach, describe, expect, it, vi } from 'vitest';

import { backendFetch } from '@/lib/ai/backend-client';
import { validateActionRole } from './route';

vi.mock('@/lib/ai/backend-client', () => ({
  backendFetch: vi.fn(),
}));

const mockBackendFetch = vi.mocked(backendFetch);

describe('validateActionRole', () => {
  beforeEach(() => {
    mockBackendFetch.mockReset();
  });

  it('preserves unauthenticated local mode', async () => {
    await expect(validateActionRole('editor', undefined, 'project-a')).resolves.toBeNull();

    expect(mockBackendFetch).not.toHaveBeenCalled();
  });

  it('rejects viewers for editor actions', async () => {
    mockBackendFetch.mockResolvedValue({
      ok: true,
      status: 200,
      data: { role: 'viewer', is_superuser: false },
    });

    await expect(validateActionRole('editor', 'token-a', 'project-a')).resolves.toBe(
      'This assistant action requires an editor or administrator'
    );

    expect(mockBackendFetch).toHaveBeenCalledWith('/projects/project-a/my-role', {
      authToken: 'token-a',
      projectId: 'project-a',
      timeoutMs: 5000,
    });
  });

  it('allows editors, admins, and superusers for editor actions', async () => {
    mockBackendFetch
      .mockResolvedValueOnce({ ok: true, status: 200, data: { role: 'editor', is_superuser: false } })
      .mockResolvedValueOnce({ ok: true, status: 200, data: { role: 'admin', is_superuser: false } })
      .mockResolvedValueOnce({ ok: true, status: 200, data: { role: 'viewer', is_superuser: true } });

    await expect(validateActionRole('editor', 'token-a', 'project-a')).resolves.toBeNull();
    await expect(validateActionRole('editor', 'token-a', 'project-a')).resolves.toBeNull();
    await expect(validateActionRole('editor', 'token-a', 'project-a')).resolves.toBeNull();
  });

  it('keeps admin-only actions admin-only', async () => {
    mockBackendFetch
      .mockResolvedValueOnce({ ok: true, status: 200, data: { role: 'editor', is_superuser: false } })
      .mockResolvedValueOnce({ ok: true, status: 200, data: { role: 'admin', is_superuser: false } })
      .mockResolvedValueOnce({ ok: true, status: 200, data: { role: 'viewer', is_superuser: true } });

    await expect(validateActionRole('admin', 'token-a', 'project-a')).resolves.toBe(
      'This assistant action requires an administrator'
    );
    await expect(validateActionRole('admin', 'token-a', 'project-a')).resolves.toBeNull();
    await expect(validateActionRole('admin', 'token-a', 'project-a')).resolves.toBeNull();
  });

  it('fails closed when authenticated project role cannot be verified', async () => {
    mockBackendFetch.mockResolvedValue({ ok: false, status: 403, error: 'Forbidden' });

    await expect(validateActionRole('editor', 'token-a', 'project-a')).resolves.toBe(
      'Could not verify user permissions for this assistant action'
    );
  });
});
