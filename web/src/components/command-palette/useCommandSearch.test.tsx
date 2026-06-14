import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { specHref, useCommandSearch } from './useCommandSearch';

vi.mock('@/contexts/AuthContext', () => ({
    fetchWithAuth: vi.fn(),
}));

vi.mock('@/contexts/ProjectContext', () => ({
    useProject: () => ({
        currentProject: { id: 'project-1' },
    }),
}));

vi.mock('@/lib/api', () => ({
    API_BASE: '',
}));

const fetchWithAuthMock = vi.mocked(fetchWithAuth);

function jsonResponse(data: unknown): Response {
    return {
        ok: true,
        json: async () => data,
    } as Response;
}

describe('specHref', () => {
    it('encodes nested spec path segments', () => {
        expect(specHref('auth/login happy.md')).toBe('/specs/auth/login%20happy.md');
    });
});

describe('useCommandSearch', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        fetchWithAuthMock.mockImplementation((url: string | URL | Request) => {
            const href = String(url);

            if (href.startsWith('/specs/list')) {
                return Promise.resolve(jsonResponse({
                    items: [{ name: 'auth/login.md', spec_type: 'e2e' }],
                }));
            }

            if (href.startsWith('/runs')) {
                return Promise.resolve(jsonResponse({
                    runs: [{ id: 'run-1', test_name: 'Login run', status: 'passed' }],
                }));
            }

            if (href.startsWith('/requirements')) {
                return Promise.resolve(jsonResponse({
                    items: [{ id: 'req-1', req_code: 'REQ-1', title: 'Login works', category: 'auth' }],
                }));
            }

            if (href.startsWith('/chat/search-entities')) {
                return Promise.resolve(jsonResponse({
                    entities: [
                        { type: 'batch', id: 'batch-1', label: 'Nightly Login', description: 'Regression batch' },
                        { type: 'batch', id: 'batch-1', label: 'Nightly Login duplicate', description: 'Duplicate batch' },
                        { type: 'exploration', id: 'session-1', label: 'Login discovery', description: 'Discovery session' },
                        { type: 'spec', id: 'ignored', label: 'Ignored spec' },
                    ],
                }));
            }

            return Promise.resolve(jsonResponse({}));
        });
    });

    afterEach(() => {
        cleanup();
        vi.useRealTimers();
        vi.clearAllMocks();
    });

    it('searches typed sources and chat entities with project scope, deduping entity results', async () => {
        const { result } = renderHook(() => useCommandSearch('login'));

        await act(async () => {
            await vi.advanceTimersByTimeAsync(300);
        });

        expect(result.current.isSearching).toBe(false);

        expect(fetchWithAuthMock).toHaveBeenCalledWith(
            '/requirements?project_id=project-1&search=login&limit=5',
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
        expect(fetchWithAuthMock).toHaveBeenCalledWith(
            '/chat/search-entities?q=login&project_id=project-1&limit=8',
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );

        expect(result.current.results).toEqual([
            expect.objectContaining({ type: 'spec', href: '/specs/auth/login.md' }),
            expect.objectContaining({ type: 'run', href: '/runs/run-1' }),
            expect.objectContaining({ type: 'requirement', href: '/requirements?highlight=req-1' }),
            expect.objectContaining({ type: 'batch', href: '/regression/batches/batch-1' }),
            expect.objectContaining({ type: 'exploration', href: '/exploration' }),
        ]);

        expect(result.current.results.filter(item => item.type === 'batch')).toHaveLength(1);
    });
});
