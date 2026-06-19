export type AgentWorkspaceMode = 'exploratory' | 'writer' | 'custom';
export type AgentWorkspaceView = 'run' | 'history' | 'library' | 'reports' | 'queue';
export type AgentResultTab = 'overview' | 'findings' | 'test_ideas' | 'requirements' | 'evidence' | 'raw';
export type AgentTraceTab = 'timeline' | 'context' | 'tools' | 'memory' | 'runtime' | 'artifacts';
export type AgentHistoryStatusFilter = 'all' | 'active' | 'completed' | 'failed' | 'cancelled' | 'paused';
export type AgentHistoryTypeFilter = 'all' | 'exploratory' | 'custom' | 'writer' | 'spec_generation';
export type ReportReviewFilter = 'all' | 'unreviewed' | 'needs_action' | 'imported' | 'spec_created';
export type ReportSearchTypeFilter = 'all' | 'finding' | 'test_idea' | 'requirement' | 'page' | 'evidence' | 'action';
export type ReportSpecItemType = 'finding' | 'test_idea';

export interface AgentWorkspaceQueryState {
    view: AgentWorkspaceView;
    runId: string;
    agent: AgentWorkspaceMode;
    definitionId: string;
    create: boolean;
    returnTo: string;
    resultTab: AgentResultTab;
    traceTab: AgentTraceTab;
    status: AgentHistoryStatusFilter;
    type: AgentHistoryTypeFilter;
    q: string;
    reportQ: string;
    reportStatus: ReportReviewFilter;
    reportSeverity: string;
    reportType: ReportSearchTypeFilter;
    specItemId: string;
    specItemType: ReportSpecItemType | '';
}

export interface AgentHistoryRunLike {
    id: string;
    agent_type: string;
    status: string;
    config?: {
        url?: string;
        agent_name?: string;
        flow_title?: string;
        [key: string]: unknown;
    };
}

export interface AgentRunValidationInput {
    selectedAgent: AgentWorkspaceMode;
    selectedDefinitionId: string;
    url: string;
    authType: string;
    sessionId: string;
    testData: string;
}

export const DEFAULT_AGENT_WORKSPACE_QUERY: AgentWorkspaceQueryState = {
    view: 'run',
    runId: '',
    agent: 'custom',
    definitionId: '',
    create: false,
    returnTo: '',
    resultTab: 'overview',
    traceTab: 'timeline',
    status: 'all',
    type: 'all',
    q: '',
    reportQ: '',
    reportStatus: 'all',
    reportSeverity: 'all',
    reportType: 'all',
    specItemId: '',
    specItemType: '',
};

const WORKSPACE_VIEWS = new Set<AgentWorkspaceView>(['run', 'history', 'library', 'reports', 'queue']);
const AGENT_MODES = new Set<AgentWorkspaceMode>(['exploratory', 'writer', 'custom']);
const RESULT_TABS = new Set<AgentResultTab>(['overview', 'findings', 'test_ideas', 'requirements', 'evidence', 'raw']);
const TRACE_TABS = new Set<AgentTraceTab>(['timeline', 'context', 'tools', 'memory', 'runtime', 'artifacts']);
const STATUS_FILTERS = new Set<AgentHistoryStatusFilter>(['all', 'active', 'completed', 'failed', 'cancelled', 'paused']);
const TYPE_FILTERS = new Set<AgentHistoryTypeFilter>(['all', 'exploratory', 'custom', 'writer', 'spec_generation']);
const REPORT_REVIEW_FILTERS = new Set<ReportReviewFilter>(['all', 'unreviewed', 'needs_action', 'imported', 'spec_created']);
const REPORT_TYPE_FILTERS = new Set<ReportSearchTypeFilter>(['all', 'finding', 'test_idea', 'requirement', 'page', 'evidence', 'action']);
const REPORT_SPEC_ITEM_TYPES = new Set<ReportSpecItemType>(['finding', 'test_idea']);
const ACTIVE_STATUSES = new Set(['running', 'pending', 'queued']);
const COMPLETED_STATUSES = new Set(['completed', 'completed_partial']);

function pickParam<T extends string>(value: string | null, allowed: Set<T>, fallback: T): T {
    return value && allowed.has(value as T) ? value as T : fallback;
}

export function parseAgentWorkspaceQuery(params: URLSearchParams): AgentWorkspaceQueryState {
    const specItemType = params.get('specItemType');
    return {
        view: pickParam(params.get('view'), WORKSPACE_VIEWS, DEFAULT_AGENT_WORKSPACE_QUERY.view),
        runId: params.get('runId') || DEFAULT_AGENT_WORKSPACE_QUERY.runId,
        agent: pickParam(params.get('agent'), AGENT_MODES, DEFAULT_AGENT_WORKSPACE_QUERY.agent),
        definitionId: params.get('definitionId') || DEFAULT_AGENT_WORKSPACE_QUERY.definitionId,
        create: ['1', 'true', 'yes'].includes((params.get('create') || '').toLowerCase()),
        returnTo: params.get('returnTo') || DEFAULT_AGENT_WORKSPACE_QUERY.returnTo,
        resultTab: pickParam(params.get('resultTab'), RESULT_TABS, DEFAULT_AGENT_WORKSPACE_QUERY.resultTab),
        traceTab: pickParam(params.get('traceTab'), TRACE_TABS, DEFAULT_AGENT_WORKSPACE_QUERY.traceTab),
        status: pickParam(params.get('status'), STATUS_FILTERS, DEFAULT_AGENT_WORKSPACE_QUERY.status),
        type: pickParam(params.get('type'), TYPE_FILTERS, DEFAULT_AGENT_WORKSPACE_QUERY.type),
        q: params.get('q') || DEFAULT_AGENT_WORKSPACE_QUERY.q,
        reportQ: params.get('reportQ') || DEFAULT_AGENT_WORKSPACE_QUERY.reportQ,
        reportStatus: pickParam(params.get('reportStatus'), REPORT_REVIEW_FILTERS, DEFAULT_AGENT_WORKSPACE_QUERY.reportStatus),
        reportSeverity: params.get('reportSeverity') || DEFAULT_AGENT_WORKSPACE_QUERY.reportSeverity,
        reportType: pickParam(params.get('reportType'), REPORT_TYPE_FILTERS, DEFAULT_AGENT_WORKSPACE_QUERY.reportType),
        specItemId: params.get('specItemId') || DEFAULT_AGENT_WORKSPACE_QUERY.specItemId,
        specItemType: specItemType && REPORT_SPEC_ITEM_TYPES.has(specItemType as ReportSpecItemType)
            ? specItemType as ReportSpecItemType
            : DEFAULT_AGENT_WORKSPACE_QUERY.specItemType,
    };
}

export function applyAgentWorkspaceQueryPatch(
    params: URLSearchParams,
    patch: Partial<Record<keyof AgentWorkspaceQueryState, string | boolean | null | undefined>>
) {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([key, value]) => {
        const defaultValue = DEFAULT_AGENT_WORKSPACE_QUERY[key as keyof AgentWorkspaceQueryState];
        const normalizedValue = typeof value === 'boolean' ? (value ? '1' : '') : value;
        const normalizedDefault = typeof defaultValue === 'boolean' ? (defaultValue ? '1' : '') : defaultValue;
        if (key === 'agent' && patch.create === true && normalizedValue) {
            next.set(key, normalizedValue);
            return;
        }
        if (!normalizedValue || normalizedValue === normalizedDefault) {
            next.delete(key);
        } else {
            next.set(key, normalizedValue);
        }
    });
    return next;
}

export function filterAgentHistoryRuns<T extends AgentHistoryRunLike>(
    runs: T[],
    filters: Pick<AgentWorkspaceQueryState, 'q' | 'status' | 'type'>
) {
    const query = filters.q.trim().toLowerCase();
    return runs.filter(run => {
        if (filters.type !== 'all' && run.agent_type !== filters.type) return false;
        if (filters.status !== 'all') {
            if (filters.status === 'active') {
                if (!ACTIVE_STATUSES.has(run.status)) return false;
            } else if (filters.status === 'completed') {
                if (!COMPLETED_STATUSES.has(run.status)) return false;
            } else if (run.status !== filters.status) {
                return false;
            }
        }
        if (!query) return true;
        const haystack = [
            run.id,
            run.agent_type,
            run.status,
            run.config?.url,
            run.config?.agent_name,
            run.config?.flow_title,
        ].filter(Boolean).join(' ').toLowerCase();
        return haystack.includes(query);
    });
}

export function getAgentHistoryCounts(runs: AgentHistoryRunLike[]) {
    return {
        status: {
            all: runs.length,
            active: runs.filter(run => ACTIVE_STATUSES.has(run.status)).length,
            completed: runs.filter(run => COMPLETED_STATUSES.has(run.status)).length,
            failed: runs.filter(run => run.status === 'failed').length,
            cancelled: runs.filter(run => run.status === 'cancelled').length,
            paused: runs.filter(run => run.status === 'paused').length,
        },
        type: {
            all: runs.length,
            exploratory: runs.filter(run => run.agent_type === 'exploratory').length,
            custom: runs.filter(run => run.agent_type === 'custom').length,
            writer: runs.filter(run => run.agent_type === 'writer').length,
            spec_generation: runs.filter(run => run.agent_type === 'spec_generation').length,
        },
    };
}

export function validateAgentRunInput(input: AgentRunValidationInput): string | null {
    if (input.selectedAgent === 'custom' && !input.selectedDefinitionId) {
        return 'Select or create a custom agent first.';
    }
    if (input.selectedAgent !== 'custom' && !input.url.trim()) {
        return 'Target URL is required.';
    }
    if (input.selectedAgent !== 'writer' && input.authType === 'session' && !input.sessionId.trim()) {
        return 'Select a browser login session.';
    }
    if (input.testData.trim()) {
        try {
            JSON.parse(input.testData);
        } catch {
            return 'Test data must be valid JSON.';
        }
    }
    return null;
}
