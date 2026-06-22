import { API_BASE } from '@/lib/api';
import type {
    AgentDefinition,
    AgentHistoryCounts,
    AgentQueueStatus,
    AgentReportSearchItem,
    AgentRunEvent,
    AgentRunNote,
    AgentRun,
    AgentRunHistoryResponse,
    AgentTraceBundle,
    ReportEditTarget,
    SpecResult,
    AgentTool,
} from './agents-model';
import type { AgentHistoryStatusFilter, AgentHistoryTypeFilter, ReportSpecItemType, ReportSearchTypeFilter } from './agents-workspace-state';

export const EMPTY_AGENT_HISTORY_COUNTS: AgentHistoryCounts = {
    status: { all: 0, active: 0, completed: 0, failed: 0, cancelled: 0, paused: 0 },
    type: { all: 0, exploratory: 0, custom: 0, writer: 0, spec_generation: 0 },
};

export function projectQuery(projectId?: string | null) {
    return projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
}

export function appendProjectQuery(path: string, projectId?: string | null) {
    if (!projectId) return path;
    const separator = path.includes('?') ? '&' : '?';
    return `${path}${separator}project_id=${encodeURIComponent(projectId)}`;
}

export function parseAgentApiError(data: any, fallback: string) {
    const detail = data?.detail;
    if (typeof data?.message === 'string') return data.message;
    if (typeof detail === 'string') return detail;
    if (typeof detail?.message === 'string') return detail.message;
    return String(fallback);
}

async function readJsonResponse<T>(res: Response, fallbackMessage: string): Promise<T> {
    let data: any = null;
    try {
        data = await res.json();
    } catch {
        data = null;
    }
    if (!res.ok) {
        throw new Error(parseAgentApiError(data, fallbackMessage || `HTTP ${res.status}`));
    }
    return data as T;
}

export async function fetchAgentRuntimeSetting() {
    const res = await fetch(`${API_BASE}/settings`);
    if (!res.ok) return null;
    const data = await res.json();
    return String(data.agent_runtime || 'claude_sdk');
}

function safeObject(value: unknown): Record<string, any> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {};
}

function safeArray<T = any>(value: unknown): T[] {
    return Array.isArray(value) ? value as T[] : [];
}

function normalizeStructuredReport(value: unknown) {
    const report = safeObject(value);
    return {
        ...report,
        pages_checked: safeArray(report.pages_checked),
        findings: safeArray(report.findings),
        test_ideas: safeArray(report.test_ideas),
        requirements: safeArray(report.requirements),
        evidence: safeArray(report.evidence),
        follow_up_actions: safeArray(report.follow_up_actions),
    };
}

export function normalizeAgentRun(value: AgentRun): AgentRun {
    const raw = safeObject(value) as AgentRun;
    const config = safeObject(raw.config);
    const progress = safeObject(raw.progress);
    const result = safeObject(raw.result);
    const normalizedResult = result.structured_report !== undefined
        ? { ...result, structured_report: normalizeStructuredReport(result.structured_report) }
        : result;

    return {
        ...raw,
        config: {
            ...config,
            selected_tools: safeArray(config.selected_tools),
        },
        progress: {
            ...progress,
            recent_tools: safeArray(progress.recent_tools),
            live_notes_tail: safeArray(progress.live_notes_tail),
        },
        result: normalizedResult,
        artifacts: safeArray(raw.artifacts),
    };
}

export function normalizeAgentRunHistoryResponse(data: AgentRun[] | AgentRunHistoryResponse): AgentRunHistoryResponse {
    if (Array.isArray(data)) {
        const items = data.map(normalizeAgentRun);
        return {
            items,
            total: items.length,
            counts: {
                status: { ...EMPTY_AGENT_HISTORY_COUNTS.status, all: items.length },
                type: { ...EMPTY_AGENT_HISTORY_COUNTS.type, all: items.length },
            },
            next_cursor: null,
        };
    }

    const items = safeArray<AgentRun>(data.items).map(normalizeAgentRun);
    return {
        items,
        total: Number(data.total || 0),
        counts: data.counts || EMPTY_AGENT_HISTORY_COUNTS,
        next_cursor: data.next_cursor || null,
    };
}

export async function fetchAgentRunHistory(options: {
    projectId?: string | null;
    status: AgentHistoryStatusFilter;
    type: AgentHistoryTypeFilter;
    query: string;
    cursor?: string | null;
    signal?: AbortSignal;
}) {
    const params = new URLSearchParams({ limit: '40' });
    if (options.projectId) params.set('project_id', options.projectId);
    if (options.status !== 'all') params.set('status', options.status);
    if (options.type !== 'all') params.set('agent_type', options.type);
    if (options.query.trim()) params.set('q', options.query.trim());
    if (options.cursor) params.set('cursor', options.cursor);

    const res = await fetch(`${API_BASE}/api/agents/runs?${params}`, { signal: options.signal });
    const data = await readJsonResponse<AgentRun[] | AgentRunHistoryResponse>(res, `HTTP ${res.status}`);
    return normalizeAgentRunHistoryResponse(data);
}

export async function fetchAgentToolCatalog() {
    const res = await fetch(`${API_BASE}/api/agents/tools/catalog`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return Array.isArray(data.tools) ? data.tools as AgentTool[] : [];
}

export async function fetchAgentDefinitions(projectId?: string | null) {
    const res = await fetch(`${API_BASE}/api/agents/definitions${projectQuery(projectId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return Array.isArray(data) ? data as AgentDefinition[] : [];
}

export interface AgentDefinitionPayload {
    name: string;
    description: string;
    system_prompt: string;
    runtime: string;
    timeout_seconds: number;
    tool_ids: string[];
    test_data_refs: string[];
    project_id?: string;
}

export async function saveAgentDefinition(options: {
    definitionId?: string | null;
    payload: AgentDefinitionPayload;
    projectId?: string | null;
}) {
    const path = options.definitionId
        ? appendProjectQuery(`/api/agents/definitions/${options.definitionId}`, options.projectId)
        : '/api/agents/definitions';
    const res = await fetch(`${API_BASE}${path}`, {
        method: options.definitionId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options.payload),
    });
    return readJsonResponse<AgentDefinition>(res, 'Failed to save agent');
}

export async function archiveAgentDefinition(definitionId: string, projectId?: string | null) {
    const res = await fetch(`${API_BASE}${appendProjectQuery(`/api/agents/definitions/${definitionId}`, projectId)}`, {
        method: 'DELETE',
    });
    return readJsonResponse<Record<string, any>>(res, 'Failed to archive agent');
}

export interface StartAgentDefinitionRunPayload {
    prompt: string;
    url?: string;
    runtime: string;
    test_data_refs: string[];
    config: {
        browser_auth_session_id?: string;
        test_data_refs?: string[];
    };
    project_id?: string;
}

export async function startAgentDefinitionRun(definitionId: string, payload: StartAgentDefinitionRunPayload) {
    const res = await fetch(`${API_BASE}/api/agents/definitions/${definitionId}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    return readJsonResponse<{ run_id: string } & Record<string, any>>(res, 'Agent run failed');
}

export async function fetchAgentQueueStatus() {
    const res = await fetch(`${API_BASE}/api/agents/queue-status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json() as Promise<AgentQueueStatus>;
}

export function queueCleanupSummary(data: Record<string, any>) {
    const cleaned = Number(data.cleaned ?? 0);
    const details = [
        ['lost heartbeat', data.cancelled_orphaned],
        ['timed out', data.timed_out],
        ['terminal owner', data.terminal_owner],
        ['orphaned queued', data.orphaned_queued],
        ['stale queued', data.stale_ownerless_queued],
        ['missing refs', data.missing_task_refs],
    ]
        .map(([label, value]) => [label, Number(value ?? 0)] as const)
        .filter(([, value]) => value > 0)
        .map(([label, value]) => `${value} ${label}`)
        .join(', ');

    return cleaned > 0
        ? `Cleaned ${cleaned} stale queue task${cleaned === 1 ? '' : 's'}${details ? ` (${details})` : ''}`
        : 'No stale queue tasks needed cleanup';
}

export async function cleanStaleAgentQueue() {
    const res = await fetch(`${API_BASE}/api/agents/queue-clean-stale`, { method: 'POST' });
    const data = await readJsonResponse<Record<string, any>>(res, `HTTP ${res.status}`);
    if (data.status === 'error') {
        throw new Error(parseAgentApiError(data, `HTTP ${res.status}`));
    }
    return data;
}

export async function searchAgentReports(options: {
    projectId?: string | null;
    query: string;
    type: ReportSearchTypeFilter;
    severity: string;
    signal?: AbortSignal;
}) {
    const params = new URLSearchParams({ limit: '50' });
    if (options.projectId) params.set('project_id', options.projectId);
    if (options.query.trim()) params.set('query', options.query.trim());
    if (options.type !== 'all') params.set('item_type', options.type);
    if (options.severity !== 'all') params.set('severity', options.severity);

    const res = await fetch(`${API_BASE}/api/agents/reports/search?${params}`, { signal: options.signal });
    const data = await readJsonResponse<{ items?: AgentReportSearchItem[] }>(res, `HTTP ${res.status}`);
    return Array.isArray(data.items) ? data.items : [];
}

export async function fetchAgentRun(runId: string, options: { projectId?: string | null; signal?: AbortSignal } = {}) {
    const res = await fetch(`${API_BASE}${appendProjectQuery(`/api/agents/runs/${runId}`, options.projectId)}`, {
        signal: options.signal,
    });
    const data = await readJsonResponse<AgentRun>(res, `HTTP ${res.status}`);
    return normalizeAgentRun(data);
}

export function looksLikeTestRunId(runId: string) {
    return /^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}/.test(runId);
}

export async function fetchLinkedAgentRunForTestRun(runId: string, options: { projectId?: string | null; signal?: AbortSignal } = {}) {
    const res = await fetch(`${API_BASE}${appendProjectQuery(`/runs/${runId}`, options.projectId)}`, {
        signal: options.signal,
    });
    const data = await readJsonResponse<{ linked_agent_run_id?: string | null }>(res, `HTTP ${res.status}`);
    const linkedAgentRunId = typeof data.linked_agent_run_id === 'string' ? data.linked_agent_run_id : '';
    if (!linkedAgentRunId) {
        throw new Error('No linked agent run found for test run');
    }
    return fetchAgentRun(linkedAgentRunId, options);
}

export async function fetchAgentRunResolvingTestRun(runId: string, options: { projectId?: string | null; signal?: AbortSignal } = {}) {
    try {
        return await fetchAgentRun(runId, options);
    } catch (error) {
        if (!looksLikeTestRunId(runId)) throw error;
        return fetchLinkedAgentRunForTestRun(runId, options);
    }
}

export async function fetchAgentRunEvents(runId: string, options: { limit?: number; afterSequence?: number; projectId?: string | null; signal?: AbortSignal } = {}) {
    const params = new URLSearchParams({
        limit: String(options.limit ?? 200),
    });
    if (options.afterSequence !== undefined) params.set('after_sequence', String(options.afterSequence));
    if (options.projectId) params.set('project_id', options.projectId);
    const res = await fetch(`${API_BASE}/api/agents/runs/${runId}/events?${params}`, { signal: options.signal });
    const data = await readJsonResponse<AgentRunEvent[] | unknown>(res, `HTTP ${res.status}`);
    return Array.isArray(data) ? data as AgentRunEvent[] : [];
}

export async function fetchAgentRunNotes(runId: string, options: { limit?: number; afterSequence?: number; projectId?: string | null; signal?: AbortSignal } = {}) {
    const res = await fetch(agentRunNotesUrl(runId, options), { signal: options.signal });
    const data = await readJsonResponse<AgentRunNote[] | unknown>(res, `HTTP ${res.status}`);
    return Array.isArray(data) ? data as AgentRunNote[] : [];
}

export async function fetchAgentRunTrace(runId: string, projectId?: string | null) {
    const res = await fetch(`${API_BASE}${appendProjectQuery(`/api/agents/runs/${runId}/trace`, projectId)}`);
    return readJsonResponse<AgentTraceBundle>(res, `HTTP ${res.status}`);
}

export function agentRunTraceExportUrl(runId: string, projectId?: string | null) {
    return `${API_BASE}${appendProjectQuery(`/api/agents/runs/${runId}/trace/export`, projectId)}`;
}

export async function fetchFlowSpecAgentRun(runId: string) {
    const [run, events] = await Promise.all([
        fetchAgentRun(runId),
        fetchAgentRunEvents(runId, { limit: 100 }),
    ]);
    return { run, events };
}

export async function fetchExploratorySpecs(runId: string) {
    const res = await fetch(`${API_BASE}/api/agents/exploratory/${runId}/specs`);
    return readJsonResponse<SpecResult>(res, `HTTP ${res.status}`);
}

export async function fetchExploratoryFlowDetails(runId: string, flowId: string) {
    const res = await fetch(`${API_BASE}/api/agents/exploratory/${runId}/flows/${flowId}`);
    return readJsonResponse<{ flow: any }>(res, `HTTP ${res.status}`);
}

export async function generateExploratoryFlowSpec(runId: string, flowId: string, forceRegenerate = false) {
    const path = forceRegenerate
        ? `/api/agents/exploratory/${runId}/flows/${flowId}/generate?force_regenerate=true`
        : `/api/agents/exploratory/${runId}/flows/${flowId}/generate`;
    const res = await fetch(`${API_BASE}${path}`, { method: 'POST' });
    return readJsonResponse<Record<string, any>>(res, `HTTP ${res.status}`);
}

export async function generateReportItemSpec(options: {
    runId: string;
    itemId: string;
    itemType: ReportSpecItemType;
    projectId?: string | null;
    body: Record<string, any>;
}) {
    const params = new URLSearchParams({ item_type: options.itemType });
    if (options.projectId) params.set('project_id', options.projectId);
    const res = await fetch(`${API_BASE}/api/agents/runs/${options.runId}/report-items/${encodeURIComponent(options.itemId)}/generate-spec?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options.body),
    });
    return readJsonResponse<Record<string, any>>(res, `HTTP ${res.status}`);
}

export async function patchAgentReport(options: {
    target: ReportEditTarget;
    payload: Record<string, any>;
    projectId?: string | null;
}) {
    const params = new URLSearchParams();
    if (options.projectId) params.set('project_id', options.projectId);
    let path = `/api/agents/runs/${options.target.runId}/report`;
    let body = options.payload;
    if (options.target.type !== 'overview') {
        params.set('item_type', options.target.type);
        path = `/api/agents/runs/${options.target.runId}/report-items/${encodeURIComponent(options.target.itemId)}`;
        body = { patch: options.payload };
    }
    const query = params.toString() ? `?${params}` : '';
    const res = await fetch(`${API_BASE}${path}${query}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return readJsonResponse<Record<string, any>>(res, `HTTP ${res.status}`);
}

export async function importAgentReportRequirements(options: {
    runId: string;
    itemIds?: string[];
    projectId?: string | null;
}) {
    const params = new URLSearchParams();
    if (options.projectId) params.set('project_id', options.projectId);
    const query = params.toString() ? `?${params}` : '';
    const selectedIds = (options.itemIds || []).filter(Boolean);
    const res = await fetch(`${API_BASE}/api/agents/runs/${options.runId}/report-requirements/import${query}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(selectedIds.length > 0 ? { item_ids: selectedIds } : { import_all: true }),
    });
    return readJsonResponse<Record<string, any>>(res, `HTTP ${res.status}`);
}

export function specFileToSplitName(specFile: string) {
    const specsIndex = specFile.indexOf('/specs/');
    return specsIndex !== -1 ? specFile.substring(specsIndex + 7) : specFile.split('/').slice(-2).join('/');
}

export async function splitSpecFile(specFile: string) {
    const res = await fetch(`${API_BASE}/specs/split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spec_name: specFileToSplitName(specFile) }),
    });
    return readJsonResponse<{ count: number; files: string[]; output_dir: string }>(res, `HTTP ${res.status}`);
}

export async function controlAgentRun(runId: string, action: 'pause' | 'resume' | 'cancel', projectId?: string | null) {
    const res = await fetch(`${API_BASE}${appendProjectQuery(`/api/agents/runs/${runId}/${action}`, projectId)}`, {
        method: 'POST',
    });
    const data = await readJsonResponse<AgentRun>(res, `Failed to ${action} agent run`);
    return normalizeAgentRun(data);
}

export async function retryAgentRun(runId: string, projectId?: string | null) {
    const res = await fetch(`${API_BASE}${appendProjectQuery(`/api/agents/runs/${runId}/retry`, projectId)}`, {
        method: 'POST',
    });
    const data = await readJsonResponse<AgentRun>(res, 'Failed to retry agent run');
    return normalizeAgentRun(data);
}

export async function synthesizeExploratorySpecs(runId: string) {
    const res = await fetch(`${API_BASE}/api/agents/exploratory/${runId}/synthesize`, { method: 'POST' });
    return readJsonResponse<Record<string, any>>(res, 'Spec synthesis failed');
}

export function agentRunEventsStreamUrl(runId: string, options: { afterSequence: number; projectId?: string | null }) {
    const params = new URLSearchParams({ after_sequence: String(options.afterSequence) });
    if (options.projectId) params.set('project_id', options.projectId);
    return `${API_BASE}/api/agents/runs/${runId}/events/stream?${params}`;
}

export function agentRunNotesUrl(runId: string, options: { limit?: number; afterSequence?: number; projectId?: string | null } = {}) {
    const params = new URLSearchParams({ limit: String(options.limit ?? 100) });
    if (options.afterSequence !== undefined) params.set('after_sequence', String(options.afterSequence));
    if (options.projectId) params.set('project_id', options.projectId);
    return `${API_BASE}/api/agents/runs/${runId}/notes?${params}`;
}
