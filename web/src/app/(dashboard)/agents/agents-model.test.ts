import { describe, expect, it } from 'vitest';
import {
    DEFAULT_CUSTOM_AGENT_TOOL_IDS,
    agentRunDisplayName,
    agentRunNoteFromEvent,
    agentRunPartialReason,
    customAgentCurrentActivity,
    customAgentExecutionStarted,
    filterAgentRunNotes,
    formatQueueAge,
    getStructuredReport,
    isAgentRunTerminal,
    mergeAgentRunNotes,
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

    it('returns safe empty structured report arrays for malformed fields', () => {
        const report = getStructuredReport({
            ...baseRun,
            result: {
                summary: 'Fallback',
                structured_report: {
                    summary: 'Structured',
                    pages_checked: { url: 'https://example.test' },
                    findings: { id: 'F-1' },
                    test_ideas: 'bad',
                    requirements: null,
                    evidence: false,
                    follow_up_actions: { id: 'A-1' },
                },
            },
        });

        expect(report.summary).toBe('Structured');
        expect(report.pages_checked).toEqual([]);
        expect(report.findings).toEqual([]);
        expect(report.test_ideas).toEqual([]);
        expect(report.requirements).toEqual([]);
        expect(report.evidence).toEqual([]);
        expect(report.follow_up_actions).toEqual([]);
    });

    it('builds stable report search links with spec review params for actionable items', () => {
        const findingHref = reportSearchResultHref({
            run_id: 'run-1',
            project_id: 'project-a',
            type: 'finding',
            item: { id: 'F-001' },
        }, 'traceTab=tools&specItemId=old&specItemType=test_idea');
        const findingParams = new URL(findingHref, 'https://app.test').searchParams;
        expect(findingHref.startsWith('/agents?')).toBe(true);
        expect(findingParams.get('traceTab')).toBe('tools');
        expect(findingParams.get('runId')).toBe('run-1');
        expect(findingParams.get('view')).toBe('run');
        expect(findingParams.get('resultTab')).toBe('findings');
        expect(findingParams.get('project_id')).toBe('project-a');
        expect(findingParams.get('specItemId')).toBe('F-001');
        expect(findingParams.get('specItemType')).toBe('finding');

        const pageHref = reportSearchResultHref({
            run_id: 'run-1',
            type: 'page',
            item: { id: 'P-001' },
        }, 'traceTab=tools&specItemId=old&specItemType=finding');
        const pageParams = new URL(pageHref, 'https://app.test').searchParams;
        expect(pageParams.get('traceTab')).toBe('tools');
        expect(pageParams.get('runId')).toBe('run-1');
        expect(pageParams.get('view')).toBe('run');
        expect(pageParams.get('resultTab')).toBe('overview');
        expect(pageParams.has('specItemId')).toBe(false);
        expect(pageParams.has('specItemType')).toBe(false);
    });

    it('keeps status, queue, and report review classifications compatible', () => {
        expect(isAgentRunTerminal('completed_partial')).toBe(true);
        expect(isAgentRunTerminal('running')).toBe(false);
        expect(formatQueueAge(45)).toBe('45s');
        expect(formatQueueAge(125)).toBe('2m');
        expect(reportItemReviewState({ severity: 'high' }, 'finding')).toBe('needs_action');
        expect(reportItemReviewState({ generated_spec: { id: 1 } }, 'test_idea')).toBe('spec_created');
    });

    it('returns a concise partial completion reason for recovered browser timeouts', () => {
        expect(agentRunPartialReason({
            ...baseRun,
            status: 'completed_partial',
            result: {
                partial_reason: 'Recovered partial evidence after browser_click timed out after 30s/45s.',
            },
        })).toBe('Recovered partial evidence after browser_click timed out after 30s/45s.');
        expect(agentRunPartialReason({
            ...baseRun,
            status: 'completed_partial',
            result: {
                diagnostics: {
                    finalizer: {
                        browser_timeout_recovery_reason: 'Recovered partial evidence after browser_type timed out after 30s/45s.',
                    },
                },
            },
        })).toContain('browser_type timed out');
        expect(agentRunPartialReason({ ...baseRun, status: 'completed' })).toBe('');
    });

    it('detects custom run execution and browser auth session ids across current and legacy config', () => {
        expect(agentRunDisplayName(baseRun)).toBe('Checkout Agent');
        expect(customAgentExecutionStarted({ ...baseRun, progress: { tool_calls: 1 } })).toBe(true);
        expect(customAgentExecutionStarted({ ...baseRun, agent_task_id: 'agent-task-1', progress: { phase: 'worker_wait' } })).toBe(false);
        expect(customAgentExecutionStarted({ ...baseRun, status: 'running', progress: { browser_activity_seen: true } })).toBe(true);
        expect(customAgentCurrentActivity({
            auth_preflight_status: 'failed',
            auth_preflight_failure_reason: 'Security challenge',
            last_tool: 'Read',
        })).toBe('Auth challenge');
        expect(customAgentCurrentActivity({
            auth_preflight_status: 'failed',
            auth_preflight_failure_reason: 'Password prompt',
            last_tool: 'Read',
        })).toBe('Session validation failed');
        expect(runBrowserAuthSessionId({ browser_auth: { session_id: 'session-1' } })).toBe('session-1');
        expect(runBrowserAuthSessionId({ auth: { browser_auth_session_id: 'legacy-session' } })).toBe('legacy-session');
    });

    it('converts multiline textarea content into trimmed report arrays', () => {
        expect(textToLines(' one \n\n two\n')).toEqual(['one', 'two']);
    });

    it('extracts, merges, and filters live agent notes by sequence', () => {
        const note = agentRunNoteFromEvent({
            id: 'evt-1',
            run_id: 'run-1',
            sequence: 2,
            event_type: 'agent_note',
            level: 'warning',
            message: 'Blocked',
            payload: {
                note_type: 'blocker',
                title: 'Login blocked',
                body: 'Missing credentials',
                source: 'verifier',
                tags: ['auth'],
                actionable: true,
            },
            created_at: '2026-06-21T10:00:00Z',
        });

        expect(note?.title).toBe('Login blocked');
        expect(note?.actionable).toBe(true);

        const merged = mergeAgentRunNotes([
            { ...note!, title: 'Older duplicate' },
            { ...note!, id: 'evt-0', sequence: 1, title: 'Started', note_type: 'handoff', level: 'info', actionable: false },
        ], [note!]);

        expect(merged.map(item => item.title)).toEqual(['Started', 'Login blocked']);
        expect(filterAgentRunNotes(merged, { search: 'credentials', actionableOnly: true, sort: 'newest' }).map(item => item.sequence)).toEqual([2]);
        expect(filterAgentRunNotes(merged, { noteType: 'handoff', sort: 'chronological' }).map(item => item.title)).toEqual(['Started']);
    });
});

describe('custom agent defaults', () => {
    it('selects the explicit agent note tool by default', () => {
        expect(DEFAULT_CUSTOM_AGENT_TOOL_IDS).toContain('agent_note');
    });
});
