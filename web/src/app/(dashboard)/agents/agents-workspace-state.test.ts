import { describe, expect, it } from 'vitest';
import {
    applyAgentWorkspaceQueryPatch,
    filterAgentHistoryRuns,
    getAgentHistoryCounts,
    parseAgentWorkspaceQuery,
    validateAgentRunInput,
    type AgentHistoryRunLike,
} from './agents-workspace-state';

const runs: AgentHistoryRunLike[] = [
    {
        id: 'run-active',
        agent_type: 'exploratory',
        status: 'running',
        config: { url: 'https://app.example.com/checkout' },
    },
    {
        id: 'run-custom',
        agent_type: 'custom',
        status: 'completed',
        config: { agent_name: 'API Scout', url: 'https://api.example.com' },
    },
    {
        id: 'run-partial',
        agent_type: 'exploratory',
        status: 'completed_partial',
        config: { url: 'https://app.example.com/inventory' },
    },
    {
        id: 'run-failed',
        agent_type: 'writer',
        status: 'failed',
        config: { flow_title: 'Login spec' },
    },
];

describe('agents workspace query state', () => {
    it('initializes from supported URL params and ignores invalid enum values', () => {
        const state = parseAgentWorkspaceQuery(new URLSearchParams('view=history&runId=abc&agent=custom&definitionId=def-1&create=1&returnTo=%2Fworkflow&resultTab=findings&traceTab=tools&status=active&type=custom&q=checkout&reportQ=postal&reportStatus=needs_action&reportSeverity=high&reportType=finding&specItemId=T-001&specItemType=test_idea'));

        expect(state).toEqual({
            view: 'history',
            runId: 'abc',
            agent: 'custom',
            definitionId: 'def-1',
            create: true,
            returnTo: '/workflow',
            resultTab: 'findings',
            traceTab: 'tools',
            status: 'active',
            type: 'custom',
            q: 'checkout',
            reportQ: 'postal',
            reportStatus: 'needs_action',
            reportSeverity: 'high',
            reportType: 'finding',
            specItemId: 'T-001',
            specItemType: 'test_idea',
        });

        const fallback = parseAgentWorkspaceQuery(new URLSearchParams('view=bad&agent=bad&resultTab=bad&traceTab=bad&status=bad&type=bad&reportStatus=bad&reportType=bad&specItemType=bad'));
        expect(fallback.view).toBe('run');
        expect(fallback.agent).toBe('custom');
        expect(fallback.resultTab).toBe('overview');
        expect(fallback.traceTab).toBe('timeline');
        expect(fallback.status).toBe('all');
        expect(fallback.type).toBe('all');
        expect(fallback.reportStatus).toBe('all');
        expect(fallback.reportType).toBe('all');
        expect(fallback.specItemType).toBe('');
    });

    it('updates and clears URL params when values return to defaults', () => {
        const initial = new URLSearchParams('runId=old&agent=exploratory&q=api&create=1&view=library&specItemId=F-001&specItemType=finding');
        const updated = applyAgentWorkspaceQueryPatch(initial, {
            runId: 'new',
            agent: 'custom',
            resultTab: 'requirements',
            view: 'reports',
            create: false,
            reportQ: 'checkout',
            reportStatus: 'imported',
            reportType: 'requirement',
            q: '',
            specItemId: '',
            specItemType: '',
        });

        expect(updated.get('runId')).toBe('new');
        expect(updated.get('resultTab')).toBe('requirements');
        expect(updated.get('view')).toBe('reports');
        expect(updated.get('reportQ')).toBe('checkout');
        expect(updated.get('reportStatus')).toBe('imported');
        expect(updated.get('reportType')).toBe('requirement');
        expect(updated.has('create')).toBe(false);
        expect(updated.has('agent')).toBe(false);
        expect(updated.has('q')).toBe(false);
        expect(updated.has('specItemId')).toBe(false);
        expect(updated.has('specItemType')).toBe(false);
    });

    it('keeps explicit custom agent intent while opening the builder', () => {
        const updated = applyAgentWorkspaceQueryPatch(new URLSearchParams('view=library'), {
            agent: 'custom',
            create: true,
        });

        expect(updated.get('agent')).toBe('custom');
        expect(updated.get('create')).toBe('1');
    });

    it('keeps explicit run view for run deep links', () => {
        const updated = applyAgentWorkspaceQueryPatch(new URLSearchParams('view=reports&reportQ=address'), {
            view: 'run',
            runId: 'custom-run-reqs',
            resultTab: 'findings',
            specItemId: 'F-001',
            specItemType: 'finding',
        });

        expect(updated.get('view')).toBe('run');
        expect(updated.get('runId')).toBe('custom-run-reqs');
        expect(updated.get('resultTab')).toBe('findings');
        expect(updated.get('specItemId')).toBe('F-001');
        expect(updated.get('specItemType')).toBe('finding');
    });
});

describe('agents history filtering', () => {
    it('filters by search text, status, and agent type', () => {
        expect(filterAgentHistoryRuns(runs, { q: 'checkout', status: 'all', type: 'all' })).toHaveLength(1);
        expect(filterAgentHistoryRuns(runs, { q: '', status: 'active', type: 'all' }).map(run => run.id)).toEqual(['run-active']);
        expect(filterAgentHistoryRuns(runs, { q: '', status: 'completed', type: 'all' }).map(run => run.id)).toEqual(['run-custom', 'run-partial']);
        expect(filterAgentHistoryRuns(runs, { q: 'api', status: 'completed', type: 'custom' }).map(run => run.id)).toEqual(['run-custom']);
    });

    it('returns counted filters for status and type controls', () => {
        const counts = getAgentHistoryCounts(runs);

        expect(counts.status).toMatchObject({ all: 4, active: 1, completed: 2, failed: 1 });
        expect(counts.type).toMatchObject({ all: 4, exploratory: 2, custom: 1, writer: 1 });
    });
});

describe('agents run validation', () => {
    it('requires a URL for built-in agents', () => {
        expect(validateAgentRunInput({
            selectedAgent: 'exploratory',
            selectedDefinitionId: '',
            url: '',
            authType: 'none',
            sessionId: '',
            testData: '',
        })).toBe('Target URL is required.');
    });

    it('requires a custom agent definition for custom runs', () => {
        expect(validateAgentRunInput({
            selectedAgent: 'custom',
            selectedDefinitionId: '',
            url: '',
            authType: 'none',
            sessionId: '',
            testData: '',
        })).toBe('Select or create a custom agent first.');
    });

    it('requires selected session auth and valid JSON test data', () => {
        expect(validateAgentRunInput({
            selectedAgent: 'exploratory',
            selectedDefinitionId: '',
            url: 'https://example.com',
            authType: 'session',
            sessionId: '',
            testData: '',
        })).toBe('Select a browser login session.');

        expect(validateAgentRunInput({
            selectedAgent: 'exploratory',
            selectedDefinitionId: '',
            url: 'https://example.com',
            authType: 'none',
            sessionId: '',
            testData: '{bad',
        })).toBe('Test data must be valid JSON.');
    });
});

describe('agents archive confirmation state', () => {
    it('models dialog open and close around the archive candidate', () => {
        let archiveCandidate: AgentHistoryRunLike | null = null;
        const candidate = runs[1];

        archiveCandidate = candidate;
        expect(Boolean(archiveCandidate)).toBe(true);

        archiveCandidate = null;
        expect(Boolean(archiveCandidate)).toBe(false);
    });
});
