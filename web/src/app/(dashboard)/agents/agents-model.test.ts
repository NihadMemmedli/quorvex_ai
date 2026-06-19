import { describe, expect, it } from 'vitest';
import {
    agentRunDisplayName,
    customAgentExecutionStarted,
    formatQueueAge,
    getStructuredReport,
    isAgentRunTerminal,
    reportItemReviewState,
    reportSearchResultHref,
    runBrowserAuthSessionId,
    textToLines,
    type AgentRun,
} from './agents-model';

const baseRun: AgentRun = {
    id: 'run-1',
    agent_type: 'custom',
    status: 'completed',
    created_at: '2026-06-08T10:00:00Z',
    config: { agent_name: 'Checkout Agent', url: 'https://example.test/checkout' },
    result: {},
};

describe('agents model helpers', () => {
    it('normalizes raw custom run results into a structured report fallback', () => {
        const report = getStructuredReport({
            ...baseRun,
            result: { summary: 'Raw summary' },
        });

        expect(report.summary).toBe('Raw summary');
        expect(report.scope).toBe('https://example.test/checkout');
        expect(report.findings).toEqual([]);
        expect(report.parse_status).toBe('raw');
    });

    it('builds stable report search links with spec review params for actionable items', () => {
        expect(reportSearchResultHref({
            run_id: 'run-1',
            type: 'finding',
            item: { id: 'F-001' },
        })).toBe('/agents?runId=run-1&view=run&resultTab=findings&specItemId=F-001&specItemType=finding');

        expect(reportSearchResultHref({
            run_id: 'run-1',
            type: 'page',
            item: { id: 'P-001' },
        })).toBe('/agents?runId=run-1&view=run&resultTab=overview');
    });

    it('keeps status, queue, and report review classifications compatible', () => {
        expect(isAgentRunTerminal('completed_partial')).toBe(true);
        expect(isAgentRunTerminal('running')).toBe(false);
        expect(formatQueueAge(45)).toBe('45s');
        expect(formatQueueAge(125)).toBe('2m');
        expect(reportItemReviewState({ severity: 'high' }, 'finding')).toBe('needs_action');
        expect(reportItemReviewState({ generated_spec: { id: 1 } }, 'test_idea')).toBe('spec_created');
    });

    it('detects custom run execution and browser auth session ids across current and legacy config', () => {
        expect(agentRunDisplayName(baseRun)).toBe('Checkout Agent');
        expect(customAgentExecutionStarted({ ...baseRun, progress: { tool_calls: 1 } })).toBe(true);
        expect(runBrowserAuthSessionId({ browser_auth: { session_id: 'session-1' } })).toBe('session-1');
        expect(runBrowserAuthSessionId({ auth: { browser_auth_session_id: 'legacy-session' } })).toBe('legacy-session');
    });

    it('converts multiline textarea content into trimmed report arrays', () => {
        expect(textToLines(' one \n\n two\n')).toEqual(['one', 'two']);
    });
});
