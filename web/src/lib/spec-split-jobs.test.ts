import { afterEach, describe, expect, it, vi } from 'vitest';
import { splitSpecWithJob } from './spec-split-jobs';

function jsonResponse(data: unknown, init: ResponseInit = {}) {
    return new Response(JSON.stringify(data), {
        status: init.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
        ...init,
    });
}

describe('spec split jobs', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('starts a job and resolves after polling completed status', async () => {
        vi.spyOn(globalThis, 'setTimeout').mockImplementation((callback: any) => {
            if (typeof callback === 'function') callback();
            return 0 as never;
        });
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(jsonResponse({ job_id: 'job-1', status: 'queued' }))
            .mockResolvedValueOnce(jsonResponse({ job_id: 'job-1', status: 'running' }))
            .mockResolvedValueOnce(jsonResponse({
                job_id: 'job-1',
                status: 'completed',
                result: { count: 1, files: ['split/one.md'], output_dir: 'split' },
            }));
        vi.stubGlobal('fetch', fetchMock);

        const result = await splitSpecWithJob(
            { spec_name: 'multi.md', extraction_method: 'ai' },
            { timeoutMs: 10_000, pollIntervalMs: 1 },
        );

        expect(result).toEqual({ count: 1, files: ['split/one.md'], output_dir: 'split' });
        expect(String(fetchMock.mock.calls[0][0])).toContain('/specs/split-jobs');
        expect(String(fetchMock.mock.calls[1][0])).toContain('/specs/split-jobs/job-1');
    });

    it('surfaces failed job detail through the split error parser', async () => {
        vi.spyOn(globalThis, 'setTimeout').mockImplementation((callback: any) => {
            if (typeof callback === 'function') callback();
            return 0 as never;
        });
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(jsonResponse({ job_id: 'job-1', status: 'queued' }))
            .mockResolvedValueOnce(jsonResponse({
                job_id: 'job-1',
                status: 'failed',
                error: 'Provider returned HTTP 401: invalid key',
            })));

        await expect(splitSpecWithJob({ spec_name: 'multi.md' }, { timeoutMs: 10_000, pollIntervalMs: 1 }))
            .rejects.toThrow(/Provider returned HTTP 401:[\s\S]*Settings/);
    });

    it('does not claim failure when polling times out while job is still running', async () => {
        vi.spyOn(globalThis, 'setTimeout').mockImplementation((callback: any) => {
            if (typeof callback === 'function') callback();
            return 0 as never;
        });
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(jsonResponse({ job_id: 'job-1', status: 'queued' }))
            .mockResolvedValue(jsonResponse({ job_id: 'job-1', status: 'running' })));

        await expect(splitSpecWithJob({ spec_name: 'multi.md' }, { timeoutMs: 0, pollIntervalMs: 1 }))
            .rejects.toThrow('Split job is still running');
    });
});
