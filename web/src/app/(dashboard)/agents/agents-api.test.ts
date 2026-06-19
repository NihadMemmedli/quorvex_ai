import { describe, expect, it } from 'vitest';
import {
    agentRunEventsStreamUrl,
    appendProjectQuery,
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
    it('normalizes legacy array history responses without changing run items', () => {
        const payload = normalizeAgentRunHistoryResponse([run]);

        expect(payload.items).toEqual([run]);
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
        expect(specFileToSplitName('/tmp/work/specs/account/login.md')).toBe('account/login.md');
        expect(specFileToSplitName('/tmp/generated/login.md')).toBe('generated/login.md');
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
