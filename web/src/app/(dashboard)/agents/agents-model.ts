import type { BrowserAuthSession } from '@/lib/browser-auth-sessions';
import { isBrowserAuthSessionSelectable } from '@/lib/browser-auth-sessions';
import { API_BASE } from '@/lib/api';
import type {
    AgentHistoryStatusFilter,
    AgentHistoryTypeFilter,
    AgentTraceTab,
    ReportReviewFilter,
    ReportSpecItemType,
} from './agents-workspace-state';

export interface AgentRun {
    id: string;
    agent_type: string;
    runtime?: string;
    status: string;
    created_at: string;
    config: any;
    summary?: string;
    result?: any;
    project_id?: string;
    progress?: any;
    state?: any;
    contract_status?: string | null;
    finalization_status?: string | null;
    reporter_status?: string | null;
    verifier_status?: string | null;
    agent_task_id?: string | null;
    temporal_workflow_id?: string | null;
    temporal_run_id?: string | null;
    temporal?: AgentRunTemporal | null;
    artifacts?: AgentArtifact[];
    health?: AgentRunHealth;
    started_at?: string | null;
    completed_at?: string | null;
    updated_at?: string | null;
}

export interface AgentHistoryCounts {
    status: Record<AgentHistoryStatusFilter, number>;
    type: Record<AgentHistoryTypeFilter, number>;
}

export interface AgentRunHistoryResponse {
    items: AgentRun[];
    total: number;
    counts: AgentHistoryCounts;
    next_cursor?: string | null;
}

export interface AgentRunTemporal {
    temporal_workflow_id?: string | null;
    temporal_run_id?: string | null;
    temporal_ui_url?: string | null;
    temporal_ui_workflow_url?: string | null;
    temporal_namespace?: string | null;
    task_queue?: string | null;
    workflow_type?: string | null;
    available?: boolean;
    workflow_status?: string | null;
    summary?: {
        total_activities?: number;
        failed_activities?: number;
        retry_count?: number;
        last_failure?: string | null;
        last_workflow_task_failure?: string | null;
    };
    activities?: Array<{
        activity_type?: string;
        status?: string;
        scheduled_at?: string | null;
        started_at?: string | null;
        completed_at?: string | null;
    }>;
    task_queue_status?: {
        workflow_pollers?: number;
        activity_pollers?: number;
        has_workflow_pollers?: boolean;
        has_activity_pollers?: boolean;
    };
    error?: string | null;
}

export interface AgentArtifact {
    name: string;
    path: string;
    type: string;
    modified_at?: string | null;
}

export interface AgentRunHealth {
    event_count?: number;
    tool_event_count?: number;
    error_event_count?: number;
    latest_event?: AgentRunEvent | null;
    latest_heartbeat_at?: string | null;
    agent_task_id?: string | null;
    terminal?: boolean;
    terminal_reason?: string | null;
}

export interface AgentRunEvent {
    id: string;
    run_id?: string;
    sequence: number;
    event_type: string;
    level: string;
    message: string;
    payload?: Record<string, any>;
    idempotency_key?: string | null;
    created_at: string;
    agent_task_id?: string | null;
}

export type AgentRunNoteType = 'observation' | 'decision' | 'finding' | 'blocker' | 'handoff' | 'verifier_note' | 'reporter_note';

export interface AgentRunNote {
    id: string;
    project_id?: string | null;
    run_id: string;
    agent_task_id?: string | null;
    sequence: number;
    note_type: AgentRunNoteType | string;
    level: string;
    title: string;
    body?: string | null;
    source?: string | null;
    tags?: string[];
    confidence?: number | null;
    url?: string | null;
    tool_name?: string | null;
    artifact_path?: string | null;
    actionable?: boolean;
    related_event_sequence?: number | null;
    related_trace_span_id?: string | null;
    payload?: Record<string, any>;
    created_at: string;
}

export interface AgentTraceSnapshot {
    id: string;
    trace_id: string;
    run_id: string;
    agent_task_id?: string | null;
    attempt: number;
    runtime: string;
    model?: string | null;
    model_tier?: string | null;
    allowed_tools: string[];
    prompt_hash?: string | null;
    context_hash?: string | null;
    memory_block_hash?: string | null;
    prompt_preview?: string;
    memory_preview?: string;
    prompt_artifact_path?: string | null;
    context_artifact_path?: string | null;
    test_data_refs: string[];
    runtime_diagnostics?: Record<string, any>;
    created_at: string;
    updated_at: string;
}

export interface AgentTraceSpan {
    id: string;
    trace_id: string;
    sequence: number;
    span_type: string;
    name: string;
    level: string;
    message: string;
    tool_name?: string | null;
    success?: boolean | null;
    duration_ms?: number | null;
    content_hash?: string | null;
    input_preview?: any;
    output_preview?: any;
    artifact_path?: string | null;
    payload?: Record<string, any>;
    agent_run_event_id?: string | null;
    created_at: string;
    started_at?: string | null;
    ended_at?: string | null;
}

export interface AgentTraceBundle {
    snapshot?: AgentTraceSnapshot | null;
    spans: AgentTraceSpan[];
    events: AgentRunEvent[];
    memory_injections: Array<Record<string, any>>;
    artifacts: AgentArtifact[];
    temporal?: AgentRunTemporal | null;
    correlation?: Record<string, any>;
}

export function agentRunNoteFromEvent(event: AgentRunEvent): AgentRunNote | null {
    if (event.event_type !== 'agent_note') return null;
    const payload = event.payload || {};
    return {
        id: event.id,
        project_id: payload.project_id ?? null,
        run_id: event.run_id || String(payload.run_id || ''),
        agent_task_id: event.agent_task_id ?? null,
        sequence: event.sequence,
        note_type: String(payload.note_type || 'observation'),
        level: event.level || 'info',
        title: String(payload.title || event.message || 'Agent note'),
        body: typeof payload.body === 'string' ? payload.body : null,
        source: typeof payload.source === 'string' ? payload.source : null,
        tags: Array.isArray(payload.tags) ? payload.tags.map(String) : [],
        confidence: typeof payload.confidence === 'number' ? payload.confidence : null,
        url: typeof payload.url === 'string' ? payload.url : null,
        tool_name: typeof payload.tool_name === 'string' ? payload.tool_name : null,
        artifact_path: typeof payload.artifact_path === 'string' ? payload.artifact_path : null,
        actionable: Boolean(payload.actionable),
        related_event_sequence: event.sequence,
        related_trace_span_id: typeof payload.related_trace_span_id === 'string' ? payload.related_trace_span_id : null,
        payload,
        created_at: event.created_at,
    };
}

export function mergeAgentRunNotes(existing: AgentRunNote[], incoming: AgentRunNote[]) {
    const bySequence = new Map<number, AgentRunNote>();
    [...existing, ...incoming].forEach(note => {
        if (Number.isFinite(note.sequence)) bySequence.set(note.sequence, note);
    });
    return Array.from(bySequence.values()).sort((a, b) => a.sequence - b.sequence);
}

export function filterAgentRunNotes(notes: AgentRunNote[], filters: {
    search?: string;
    noteType?: string;
    level?: string;
    source?: string;
    actionableOnly?: boolean;
    sort?: 'newest' | 'chronological';
}) {
    const query = (filters.search || '').trim().toLowerCase();
    const filtered = notes.filter(note => {
        if (filters.noteType && filters.noteType !== 'all' && note.note_type !== filters.noteType) return false;
        if (filters.level && filters.level !== 'all' && note.level !== filters.level) return false;
        if (filters.source && filters.source !== 'all' && (note.source || 'runtime') !== filters.source) return false;
        if (filters.actionableOnly && !note.actionable) return false;
        if (!query) return true;
        return [
            note.title,
            note.body,
            note.source,
            note.tool_name,
            note.url,
            ...(note.tags || []),
        ].filter(Boolean).join(' ').toLowerCase().includes(query);
    });
    return [...filtered].sort((a, b) => (
        filters.sort === 'newest' ? b.sequence - a.sequence : a.sequence - b.sequence
    ));
}

export interface AgentTool {
    id: string;
    label: string;
    description: string;
    category: string;
    tool_name: string;
    risk: 'low' | 'medium' | 'high' | 'destructive';
    requires_mcp_server?: string | null;
}

export interface AgentDefinition {
    id: string;
    name: string;
    description: string;
    system_prompt: string;
    runtime?: string;
    model?: string | null;
    timeout_seconds: number;
    tool_ids: string[];
    test_data_refs?: string[];
    status: string;
    project_id?: string | null;
}

export interface SpecResult {
    specs?: {
        happy_path?: Record<string, string>;
        edge_cases?: Record<string, string>;
    };
    summary?: string;
    total_specs?: number;
    flows_covered?: string[];
    generated_at?: string;
}

export type AuthType = 'none' | 'credentials' | 'session';
export type CustomResultTab = 'overview' | 'findings' | 'test_ideas' | 'requirements' | 'evidence' | 'raw';
export type ReportSpecBrowserAuthMode = 'session' | 'project_default' | 'none';
export type TraceTab = AgentTraceTab;
export type ReportEditableItemType = 'finding' | 'test_idea' | 'requirement';
export type AgentActionIntent =
    | { type: 'none' }
    | { type: 'createAgent' }
    | { type: 'reviewReportSpec'; runId: string; itemId: string; itemType: ReportSpecItemType };

export interface FlowModalData {
    id: string;
    title: string;
    pages?: string[];
    happy_path?: string;
    edge_cases?: string[];
    test_ideas?: string[];
    entry_point?: string;
    exit_point?: string;
    source_type?: 'custom_report' | string;
    item_type?: ReportSpecItemType;
    generated_spec?: unknown;
}

export interface ReportSpecBrowserAuthSelection {
    mode: ReportSpecBrowserAuthMode;
    sessionId: string;
}

export interface ReportPage {
    id?: string;
    url: string;
    status?: string;
    notes?: string;
}

export interface ReportFinding {
    id: string;
    title: string;
    severity?: string;
    confidence?: string;
    page?: string;
    description?: string;
    evidence?: string;
    suggested_action?: string;
}

export interface ReportTestIdea {
    id: string;
    title: string;
    priority?: string;
    page?: string;
    steps?: string[];
    expected?: string;
    source_finding_id?: string;
}

export interface ReportRequirement {
    id: string;
    title: string;
    description?: string;
    category?: string;
    priority?: string;
    acceptance_criteria?: string[];
    page?: string;
    evidence?: string;
    confidence?: number | string;
    imported_requirement_id?: number;
    imported_requirement_code?: string;
    imported_at?: string;
}

export interface ReportEvidence {
    id?: string;
    type?: string;
    label?: string;
    value?: string;
}

export interface StructuredAgentReport {
    summary?: string;
    scope?: string;
    pages_checked?: ReportPage[];
    findings?: ReportFinding[];
    test_ideas?: ReportTestIdea[];
    requirements?: ReportRequirement[];
    evidence?: ReportEvidence[];
    follow_up_actions?: { id?: string; label?: string; action?: string; target?: string }[];
    parse_status?: string;
}

export type ReportEditTarget =
    | { type: 'overview'; runId: string }
    | { type: ReportEditableItemType; runId: string; itemId: string };

export interface AgentQueueStatus {
    mode?: string;
    active?: number;
    queued?: number;
    max?: number;
    available?: number;
    workers_alive?: number;
    worker_processes_alive?: number;
    workers_busy?: number;
    workers_idle?: number;
    running_task_heartbeats_alive?: number;
    capacity_state?: string;
    stale_running?: number;
    oldest_queued_age_seconds?: number | null;
    orphaned_tasks?: number;
    background_tasks?: number;
    linked_tasks?: number;
    worker_health?: Record<string, any>;
    browser_pool?: Record<string, any>;
    pool_status?: Record<string, any>;
    temporal?: Record<string, any>;
    running_tasks?: Array<Record<string, any>>;
}

export interface AgentReportSearchItem {
    run_id: string;
    project_id?: string | null;
    agent_name?: string;
    created_at?: string;
    type: 'finding' | 'test_idea' | 'requirement' | 'page' | 'evidence' | 'action' | string;
    item: Record<string, any>;
}

export const DEFAULT_CUSTOM_AGENT_SYSTEM_PROMPT =
    'You are a focused QA automation agent. Use the selected tools to inspect the target, report findings clearly, and avoid actions outside the requested task.';

export const DEFAULT_CUSTOM_AGENT_TOOL_IDS = [
    'read_file',
    'list_files',
    'agent_note',
    'browser_navigate',
    'browser_snapshot',
    'browser_network',
    'browser_console',
    'browser_screenshot',
];

export const TOOL_RISK_PILL_STYLES: Record<AgentTool['risk'], { background: string; borderColor: string; color: string }> = {
    low: {
        background: 'rgba(126, 139, 168, 0.14)',
        borderColor: 'rgba(126, 139, 168, 0.24)',
        color: 'var(--text-secondary)',
    },
    medium: {
        background: 'var(--warning-muted)',
        borderColor: 'rgba(251, 191, 36, 0.28)',
        color: 'var(--warning)',
    },
    high: {
        background: 'var(--danger-muted)',
        borderColor: 'rgba(248, 113, 113, 0.3)',
        color: 'var(--danger)',
    },
    destructive: {
        background: 'rgba(248, 113, 113, 0.16)',
        borderColor: 'rgba(248, 113, 113, 0.36)',
        color: 'var(--danger)',
    },
};

export const AGENT_HISTORY_STATUS_FILTER_LABELS: Record<AgentHistoryStatusFilter, string> = {
    all: 'All',
    active: 'Active',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
    paused: 'Paused',
};

export const AGENT_HISTORY_TYPE_FILTER_LABELS: Record<AgentHistoryTypeFilter, string> = {
    all: 'All',
    exploratory: 'Explorer',
    custom: 'Custom',
    writer: 'Writer',
    spec_generation: 'Spec runs',
};

export const REPORT_PRIORITY_OPTIONS = ['critical', 'high', 'medium', 'low'] as const;
export const REPORT_SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low', 'info'] as const;
export const REPORT_SELECT_EMPTY_VALUE = '__empty__';

export const LIVE_AGENT_STATUSES = new Set(['running', 'pending', 'queued', 'in_progress', 'waiting', 'paused']);
export const TERMINAL_AGENT_STATUSES = new Set(['completed', 'completed_partial', 'failed', 'cancelled', 'canceled', 'timeout']);

export function defaultDefinitionForm(runtime: string) {
    return {
        id: '',
        name: '',
        description: '',
        system_prompt: DEFAULT_CUSTOM_AGENT_SYSTEM_PROMPT,
        runtime,
        timeout_seconds: 1800,
        tool_ids: DEFAULT_CUSTOM_AGENT_TOOL_IDS,
        test_data_refs: '',
    };
}

export function reportSearchResultTab(type: AgentReportSearchItem['type']): CustomResultTab {
    switch (type) {
        case 'finding':
            return 'findings';
        case 'test_idea':
            return 'test_ideas';
        case 'requirement':
            return 'requirements';
        case 'evidence':
            return 'evidence';
        case 'page':
        case 'action':
        default:
            return 'overview';
    }
}

export function reportSearchResultHref(result: AgentReportSearchItem, currentParams?: URLSearchParams | string) {
    const fallbackParams = typeof window !== 'undefined' ? window.location.search : undefined;
    const sourceParams = currentParams ?? fallbackParams;
    const params = new URLSearchParams(typeof sourceParams === 'string' ? sourceParams : sourceParams?.toString());
    params.set('runId', result.run_id);
    params.set('view', 'run');
    params.set('resultTab', reportSearchResultTab(result.type));
    if (result.project_id) params.set('project_id', result.project_id);
    const itemId = result.item?.id != null ? String(result.item.id) : '';

    if ((result.type === 'finding' || result.type === 'test_idea') && itemId) {
        params.set('specItemId', itemId);
        params.set('specItemType', result.type);
    } else {
        params.delete('specItemId');
        params.delete('specItemType');
    }

    return `/agents?${params.toString()}`;
}

export function formatToolName(toolName?: string) {
    if (!toolName) return 'Waiting for first tool';
    const short = toolName.includes('__') ? toolName.split('__').pop() || toolName : toolName;
    return short.replace(/^browser_/, '').replace(/_/g, ' ');
}

export function customAgentCurrentActivity(progress: any = {}) {
    if (String(progress.auth_preflight_status || '').toLowerCase() === 'failed') {
        const reason = String(progress.auth_preflight_failure_reason || progress.message || '');
        return /challenge|security|cloudflare|captcha|verify you are human|just a moment/i.test(reason)
            ? 'Auth challenge'
            : 'Session validation failed';
    }
    if (progress.current_tool_label || progress.last_tool_label || progress.current_tool || progress.last_tool) {
        return progress.current_tool_label || progress.last_tool_label || formatToolName(progress.current_tool || progress.last_tool);
    }
    if (progress.phase === 'llm_retry' || progress.retry_attempt) {
        const attempt = progress.retry_attempt ? ` ${progress.retry_attempt}${progress.retry_max_attempts ? `/${progress.retry_max_attempts}` : ''}` : '';
        return `LLM retry${attempt}`;
    }
    return formatToolName('');
}

export function sortArtifactsByModifiedAt(artifacts: AgentArtifact[] = []) {
    return [...artifacts].sort((a, b) => {
        const bTime = b.modified_at ? new Date(b.modified_at).getTime() : 0;
        const aTime = a.modified_at ? new Date(a.modified_at).getTime() : 0;
        return bTime - aTime;
    });
}

export function getArtifactUrl(artifact: AgentArtifact) {
    return `${API_BASE}${artifact.path}`;
}

export function runBrowserAuthSessionId(config: any): string {
    const authConfig = config?.browser_auth && typeof config.browser_auth === 'object' ? config.browser_auth : {};
    const legacyAuth = config?.auth && typeof config.auth === 'object' ? config.auth : {};
    return String(
        config?.browser_auth_session_id ||
        authConfig.session_id ||
        authConfig.browser_auth_session_id ||
        legacyAuth.browser_auth_session_id ||
        legacyAuth.session_id ||
        ''
    );
}

export function defaultReportSpecBrowserAuthSelection(
    sessions: BrowserAuthSession[],
    selectedSessionId: string
): ReportSpecBrowserAuthSelection {
    const activeSessions = sessions.filter(isBrowserAuthSessionSelectable);
    const selectedSession = activeSessions.find(item => item.id === selectedSessionId);
    if (selectedSession) {
        return { mode: 'session', sessionId: selectedSession.id };
    }
    const defaultSession = activeSessions.find(item => item.is_default);
    if (defaultSession) {
        return { mode: 'project_default', sessionId: '' };
    }
    return { mode: 'none', sessionId: '' };
}

export function reportSpecBrowserAuthBody(mode: ReportSpecBrowserAuthMode, sessionId: string) {
    if (mode === 'session') {
        return { browser_auth_session_id: sessionId };
    }
    if (mode === 'project_default') {
        return { use_project_default_browser_auth: true };
    }
    return { skip_browser_auth: true };
}

function safeReportObject(value: unknown): Record<string, any> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {};
}

function safeReportArray<T = any>(value: unknown): T[] {
    return Array.isArray(value) ? value as T[] : [];
}

export function getStructuredReport(run: AgentRun): StructuredAgentReport {
    const result = safeReportObject(run.result);
    const config = safeReportObject(run.config);
    const report = safeReportObject(result.structured_report);
    const hasStructuredReport = Object.keys(report).length > 0;
    const fallbackSummary = typeof result.summary === 'string' && result.summary.trim()
        ? result.summary
        : 'Custom agent completed. Review the raw output for details.';
    const fallbackScope = String(config.prompt || config.url || '');

    if (!hasStructuredReport) {
        return {
            summary: fallbackSummary,
            scope: fallbackScope,
            pages_checked: [],
            findings: [],
            test_ideas: [],
            requirements: [],
            evidence: [],
            follow_up_actions: [],
            parse_status: 'raw',
        };
    }

    return {
        ...report,
        summary: typeof report.summary === 'string' ? report.summary : fallbackSummary,
        scope: typeof report.scope === 'string' ? report.scope : fallbackScope,
        pages_checked: safeReportArray<ReportPage>(report.pages_checked),
        findings: safeReportArray<ReportFinding>(report.findings),
        test_ideas: safeReportArray<ReportTestIdea>(report.test_ideas),
        requirements: safeReportArray<ReportRequirement>(report.requirements),
        evidence: safeReportArray<ReportEvidence>(report.evidence),
        follow_up_actions: safeReportArray(report.follow_up_actions),
        parse_status: typeof report.parse_status === 'string' ? report.parse_status : undefined,
    };
}

export function severityColor(value?: string) {
    const normalized = (value || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 'var(--danger)';
    if (normalized === 'medium') return 'var(--warning)';
    if (normalized === 'low') return 'var(--primary)';
    return 'var(--text-secondary)';
}

export function reportItemReviewState(item: Record<string, any>, kind: 'finding' | 'test_idea' | 'requirement' | string): ReportReviewFilter {
    if (item.imported_requirement_id || item.imported_requirement_code || item.imported_at) return 'imported';
    if (item.spec_id || item.spec_file || item.generated_spec || item.spec_created_at || item.created_spec_id) return 'spec_created';
    const urgency = String(item.severity || item.priority || '').toLowerCase();
    if (kind === 'finding' || ['critical', 'high'].includes(urgency)) return 'needs_action';
    return 'unreviewed';
}

export function reportItemSeverity(item: Record<string, any>) {
    return String(item.severity || item.priority || 'info').toLowerCase();
}

export function formatQueueAge(seconds?: number | null) {
    if (!seconds || seconds < 1) return 'None';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}

export function queueStateLabel(queue?: AgentQueueStatus | null) {
    if (!queue) return 'Unknown';
    const state = queue.capacity_state || queue.mode || 'available';
    return state.replace(/_/g, ' ');
}

export function reportStatusColor(value?: string) {
    const normalized = (value || '').toLowerCase();
    if (normalized.includes('issue') || normalized.includes('failed') || normalized.includes('error')) return 'var(--danger)';
    if (normalized.includes('load') || normalized.includes('pass')) return 'var(--success)';
    return 'var(--text-secondary)';
}

export function isAgentRunTerminal(status?: string) {
    return TERMINAL_AGENT_STATUSES.has(String(status || '').toLowerCase());
}

export function agentRunPartialReason(run?: AgentRun | null) {
    if (!run || run.status !== 'completed_partial') return '';
    const result = run.result || {};
    const diagnostics = result.diagnostics || {};
    const finalizer = diagnostics.finalizer || {};
    const candidates = [
        result.partial_reason,
        result.partial_completion_reason,
        result.recovery_reason,
        finalizer.browser_timeout_recovery_reason,
        diagnostics.browser_timeout_recovery_reason,
        Array.isArray(result.contract_warnings) ? result.contract_warnings[0] : '',
    ];
    return String(candidates.find(value => typeof value === 'string' && value.trim()) || '').trim();
}

export function agentStatusTone(status?: string) {
    if (status === 'completed') return { bg: 'var(--success-muted)', color: 'var(--success)' };
    if (status === 'completed_partial') return { bg: 'var(--warning-muted)', color: 'var(--warning)' };
    if (status === 'failed' || status === 'cancelled' || status === 'timeout') return { bg: 'var(--danger-muted)', color: 'var(--danger)' };
    if (status === 'paused') return { bg: 'rgba(245, 158, 11, 0.12)', color: 'var(--warning)' };
    return { bg: 'var(--primary-glow)', color: 'var(--primary)' };
}

export function agentRunDisplayName(run: AgentRun) {
    if (run.agent_type === 'spec_generation') return 'Spec Generation';
    if (run.agent_type === 'custom') return run.config?.agent_name || 'Custom';
    if (run.agent_type === 'writer') return 'Writer';
    return 'Explorer';
}

export function agentRunResultTitle(run: AgentRun) {
    return run.config?.agent_name || run.config?.flow_title || run.config?.url || agentRunDisplayName(run);
}

export function customAgentExecutionStarted(run: AgentRun) {
    const progress = run.progress || {};
    if (String(progress.auth_preflight_status || '').toLowerCase() === 'failed') {
        return true;
    }
    if (
        progress.last_tool ||
        progress.browser_activity_seen ||
        Number(progress.tool_calls || 0) > 0 ||
        Number(progress.browser_tool_calls || 0) > 0 ||
        Number(progress.interactions || 0) > 0 ||
        ['tool_use', 'tool_result', 'running', 'browser_slot', 'retrying', 'completed', 'failed'].includes(String(progress.phase || '')) ||
        (run.health?.latest_heartbeat_at)
    ) {
        return true;
    }
    const executeActivity = (run.temporal?.activities || []).find(activity => activity.activity_type === 'execute_agent_run');
    if (executeActivity?.status === 'scheduled') return false;
    if (executeActivity && ['started', 'completed', 'failed', 'timed_out'].includes(String(executeActivity.status))) return true;
    return false;
}

export function customAgentWorkerMessage(run: AgentRun) {
    const temporalError = run.temporal?.error || run.temporal?.summary?.last_workflow_task_failure;
    if (temporalError) return temporalError;
    if (String((run.progress || {}).auth_preflight_status || '').toLowerCase() === 'failed') {
        return (run.progress || {}).auth_preflight_failure_reason || 'Saved browser session validation failed before the agent started.';
    }
    if ((run.progress || {}).browser_runtime === 'headless_worker' || (run.progress || {}).live_view_available === false) {
        return 'Browser execution is running outside the VNC display. Follow the latest screenshots and activity timeline.';
    }
    if (['queued', 'worker_wait'].includes(String((run.progress || {}).phase || ''))) return 'Agent task is queued for a worker. Browser evidence will appear when the worker starts the task.';
    const executeActivity = (run.temporal?.activities || []).find(activity => activity.activity_type === 'execute_agent_run');
    if (executeActivity?.status === 'scheduled') {
        return `Temporal scheduled agent execution. Waiting for a custom workflow worker on ${run.temporal?.task_queue || 'the workflow task queue'}.`;
    }
    if (run.temporal_workflow_id) return 'Temporal scheduled the run. Waiting for the custom workflow worker to start agent execution.';
    return 'Waiting for the run to be scheduled.';
}

export function itemPrompt(run: AgentRun, item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test idea') {
    const title = item.title || item.id;
    return [
        `Use custom agent run ${run.id} (${run.config?.agent_name || 'Custom Agent'}) as context.`,
        `Selected ${kind}: ${item.id} - ${title}`,
        'Create an actionable next step. If it requires changing platform state, prepare an approval action instead of doing it silently.',
    ].join('\n');
}

export function markAgentsAction(payload: Record<string, unknown>) {
    if (typeof window === 'undefined' || process.env.NODE_ENV === 'production') return;
    (window as typeof window & { __agentsLastAction?: Record<string, unknown> }).__agentsLastAction = payload;
}

export function reportItemToFlow(item: ReportFinding | ReportTestIdea, kind: ReportSpecItemType, run: AgentRun): FlowModalData {
    return {
        id: item.id,
        title: item.title || item.id,
        pages: item.page ? [item.page] : [],
        happy_path: 'steps' in item && item.steps?.length ? item.steps.join('\n') : ('description' in item ? item.description : undefined),
        edge_cases: kind === 'finding' && 'evidence' in item && item.evidence ? [item.evidence] : [],
        test_ideas: kind === 'test_idea' && 'expected' in item && item.expected ? [item.expected] : [],
        entry_point: item.page || run.config?.url,
        exit_point: item.page || run.config?.url,
        source_type: 'custom_report',
        item_type: kind,
    };
}

export function linesToText(value?: string[]) {
    return Array.isArray(value) ? value.join('\n') : '';
}

export function textToLines(value?: string) {
    return (value || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
}

export function normalizeReportPatchResponse(data: any): AgentRun | null {
    if (data?.run?.id) return data.run as AgentRun;
    if (data?.id) return data as AgentRun;
    return null;
}

export function reportEditDialogTitle(target: ReportEditTarget | null) {
    if (!target) return 'Edit Report Summary';
    if (target.type === 'overview') return 'Edit Report Summary';
    if (target.type === 'finding') return `Edit finding ${target.itemId}`;
    if (target.type === 'test_idea') return `Edit test idea ${target.itemId}`;
    return `Edit requirement ${target.itemId}`;
}

export function findReportSpecItem(run: AgentRun | null, itemId: string, itemType: ReportSpecItemType) {
    if (!run?.result?.structured_report || !itemId) return null;
    const report = getStructuredReport(run);
    const items = itemType === 'finding' ? report.findings || [] : report.test_ideas || [];
    const item = items.find(candidate => candidate.id === itemId);
    if (!item) return null;
    return {
        item,
        flow: reportItemToFlow(item, itemType, run),
    };
}
