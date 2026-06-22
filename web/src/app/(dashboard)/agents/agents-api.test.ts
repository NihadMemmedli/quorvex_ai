import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    agentRunEventsStreamUrl,
    agentRunNotesUrl,
    appendProjectQuery,
    fetchAgentRunResolvingTestRun,
    fetchAgentRunEvents,
    looksLikeTestRunId,
    normalizeAgentRun,
    normalizeAgentRunHistoryResponse,
    parseAgentApiError,
    projectQuery,
    queueCleanupSummary,
    specFileToSplitName,
} from './agents-api';
import type { AgentRun } from './agents-model';

const run: AgentRun = {
    id: 'run-1',
    agent_type: 'custom',
    status: 'completed',
    created_at: '2026-06-08T10:00:00Z',
    config: {},
};

describe('agents API helpers', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('normalizes legacy array history responses with safe run fields', () => {
        const payload = normalizeAgentRunHistoryResponse([run]);

        expect(payload.items[0]).toMatchObject(run);
        expect(payload.items[0].config.selected_tools).toEqual([]);
        expect(payload.items[0].progress.recent_tools).toEqual([]);
        expect(payload.items[0].artifacts).toEqual([]);
        expect(payload.total).toBe(1);
        expect(payload.counts.status.all).toBe(1);
        expect(payload.next_cursor).toBeNull();
    });

    it('normalizes paged history responses with empty fallbacks', () => {
        const payload = normalizeAgentRunHistoryResponse({
            items: [],
            total: 0,
            counts: undefined as never,
        });

        expect(payload.items).toEqual([]);
        expect(payload.total).toBe(0);
        expect(payload.counts.type.custom).toBe(0);
        expect(payload.next_cursor).toBeNull();
    });

    it('normalizes malformed agent run object and array fields', () => {
        const payload = normalizeAgentRun({
            ...run,
            config: { selected_tools: { id: 'bad' } },
            progress: { recent_tools: 'bad', live_notes_tail: { id: 'note-1' } },
            result: {
                structured_report: {
                    findings: { id: 'F-1' },
                    test_ideas: null,
                    requirements: 'bad',
                    pages_checked: { url: 'https://example.test' },
                    evidence: false,
                    follow_up_actions: { id: 'A-1' },
                },
            },
            artifacts: { name: 'bad' } as never,
        });

        expect(payload.config.selected_tools).toEqual([]);
        expect(payload.progress.recent_tools).toEqual([]);
        expect(payload.progress.live_notes_tail).toEqual([]);
        expect(payload.artifacts).toEqual([]);
        expect(payload.result.structured_report.findings).toEqual([]);
        expect(payload.result.structured_report.test_ideas).toEqual([]);
        expect(payload.result.structured_report.requirements).toEqual([]);
        expect(payload.result.structured_report.pages_checked).toEqual([]);
        expect(payload.result.structured_report.evidence).toEqual([]);
        expect(payload.result.structured_report.follow_up_actions).toEqual([]);
    });

    it('keeps project query construction and API error parsing centralized', () => {
        expect(projectQuery('project 1')).toBe('?project_id=project%201');
        expect(projectQuery('')).toBe('');
        expect(appendProjectQuery('/api/agents/runs/1/events?limit=10', 'project 1')).toBe('/api/agents/runs/1/events?limit=10&project_id=project%201');
        expect(parseAgentApiError({ detail: 'Queue unavailable' }, 'Fallback')).toBe('Queue unavailable');
        expect(parseAgentApiError({ detail: { message: 'Nested message' } }, 'Fallback')).toBe('Nested message');
        expect(parseAgentApiError({}, 'Fallback')).toBe('Fallback');
    });

    it('builds stream and split-spec paths without leaking endpoint details to callers', () => {
        expect(agentRunEventsStreamUrl('run 1', { afterSequence: 4, projectId: 'project 1' })).toContain('/api/agents/runs/run 1/events/stream?after_sequence=4&project_id=project+1');
        expect(agentRunNotesUrl('run 1', { afterSequence: 4, limit: 20, projectId: 'project 1' })).toContain('/api/agents/runs/run 1/notes?limit=20&after_sequence=4&project_id=project+1');
        expect(specFileToSplitName('/tmp/work/specs/account/login.md')).toBe('account/login.md');
        expect(specFileToSplitName('/tmp/generated/login.md')).toBe('generated/login.md');
    });

    it('includes project_id when fetching run events', async () => {
        const fetchMock = vi.fn(() => Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
        } as Response));
        vi.stubGlobal('fetch', fetchMock);

        await fetchAgentRunEvents('run 1', { afterSequence: 4, limit: 20, projectId: 'project 1' });

        const firstCall = fetchMock.mock.calls[0] as unknown as [string, RequestInit?];
        expect(String(firstCall[0])).toContain('/api/agents/runs/run 1/events?limit=20&after_sequence=4&project_id=project+1');
    });

    it('resolves timestamp test run ids through linked agent runs', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({
                ok: false,
                status: 404,
                json: () => Promise.resolve({ detail: 'Run not found' }),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ linked_agent_run_id: 'agent-run-1' }),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ ...run, id: 'agent-run-1', progress: {}, artifacts: [] }),
            } as Response);
        vi.stubGlobal('fetch', fetchMock);

        const resolved = await fetchAgentRunResolvingTestRun('2026-06-22_14-59-09', { projectId: 'project 1' });

        expect(looksLikeTestRunId('2026-06-22_14-59-09')).toBe(true);
        expect(resolved.id).toBe('agent-run-1');
        expect(String(fetchMock.mock.calls[1][0])).toContain('/runs/2026-06-22_14-59-09?project_id=project%201');
        expect(String(fetchMock.mock.calls[2][0])).toContain('/api/agents/runs/agent-run-1?project_id=project%201');
    });

    it('formats stale queue cleanup summaries with useful detail', () => {
        expect(queueCleanupSummary({ cleaned: 0 })).toBe('No stale queue tasks needed cleanup');
        expect(queueCleanupSummary({
            cleaned: 3,
            cancelled_orphaned: 1,
            timed_out: 2,
        })).toBe('Cleaned 3 stale queue tasks (1 lost heartbeat, 2 timed out)');
    });
});
