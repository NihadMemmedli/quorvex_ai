'use client';
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import Link from 'next/link';
import Bot from 'lucide-react/dist/esm/icons/bot';
import FileText from 'lucide-react/dist/esm/icons/file-text';
import Play from 'lucide-react/dist/esm/icons/play';
import Pause from 'lucide-react/dist/esm/icons/pause';
import Terminal from 'lucide-react/dist/esm/icons/terminal';
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right';
import CheckCircle2 from 'lucide-react/dist/esm/icons/check-circle-2';
import AlertTriangle from 'lucide-react/dist/esm/icons/alert-triangle';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import Clock from 'lucide-react/dist/esm/icons/clock';
import RotateCcw from 'lucide-react/dist/esm/icons/rotate-ccw';
import Lock from 'lucide-react/dist/esm/icons/lock';
import Globe from 'lucide-react/dist/esm/icons/globe';
import Settings from 'lucide-react/dist/esm/icons/settings';
import Download from 'lucide-react/dist/esm/icons/download';
import List from 'lucide-react/dist/esm/icons/list';
import Sparkles from 'lucide-react/dist/esm/icons/sparkles';
import Zap from 'lucide-react/dist/esm/icons/zap';
import ArrowRight from 'lucide-react/dist/esm/icons/arrow-right';
import Info from 'lucide-react/dist/esm/icons/info';
import X from 'lucide-react/dist/esm/icons/x';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw';
import Scissors from 'lucide-react/dist/esm/icons/scissors';
import ExternalLink from 'lucide-react/dist/esm/icons/external-link';
import Plus from 'lucide-react/dist/esm/icons/plus';
import Save from 'lucide-react/dist/esm/icons/save';
import Trash2 from 'lucide-react/dist/esm/icons/trash-2';
import Wrench from 'lucide-react/dist/esm/icons/wrench';
import MessageSquare from 'lucide-react/dist/esm/icons/message-square';
import Bug from 'lucide-react/dist/esm/icons/bug';
import Lightbulb from 'lucide-react/dist/esm/icons/lightbulb';
import Eye from 'lucide-react/dist/esm/icons/eye';
import VideoIcon from 'lucide-react/dist/esm/icons/video';
import Monitor from 'lucide-react/dist/esm/icons/monitor';
import ImageIcon from 'lucide-react/dist/esm/icons/image';
import Copy from 'lucide-react/dist/esm/icons/copy';
import Search from 'lucide-react/dist/esm/icons/search';
import Database from 'lucide-react/dist/esm/icons/database';
import Cpu from 'lucide-react/dist/esm/icons/cpu';
import PackageOpen from 'lucide-react/dist/esm/icons/package-open';
import MoreHorizontal from 'lucide-react/dist/esm/icons/more-horizontal';
import Archive from 'lucide-react/dist/esm/icons/archive';
import SlidersHorizontal from 'lucide-react/dist/esm/icons/sliders-horizontal';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down';
import ReactMarkdown from 'react-markdown';
import { toast } from 'sonner';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { LiveBrowserView } from '@/components/LiveBrowserView';
import { TestDataPicker } from '@/components/TestDataPicker';
import { StatusBadge } from '@/components/shared/StatusBadge';
import type { BrowserAuthSession } from '@/lib/browser-auth-sessions';
import {
    browserAuthSessionLabel,
    fetchProjectBrowserAuthSessions,
    isBrowserAuthSessionSelectable,
} from '@/lib/browser-auth-sessions';
import {
    applyAgentWorkspaceQueryPatch,
    filterAgentHistoryRuns,
    getAgentHistoryCounts,
    parseAgentWorkspaceQuery,
    validateAgentRunInput,
    type AgentHistoryStatusFilter,
    type AgentHistoryTypeFilter,
    type AgentTraceTab,
    type AgentWorkspaceMode,
    type AgentWorkspaceView,
    type ReportReviewFilter,
    type ReportSearchTypeFilter,
} from './agents-workspace-state';

interface AgentRun {
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
    agent_task_id?: string | null;
    temporal_workflow_id?: string | null;
    temporal_run_id?: string | null;
    temporal?: AgentRunTemporal | null;
    artifacts?: AgentArtifact[];
    health?: AgentRunHealth;
    started_at?: string | null;
    completed_at?: string | null;
}

interface AgentRunTemporal {
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

interface AgentArtifact {
    name: string;
    path: string;
    type: string;
    modified_at?: string | null;
}

interface AgentRunHealth {
    event_count?: number;
    tool_event_count?: number;
    error_event_count?: number;
    latest_event?: AgentRunEvent | null;
    latest_heartbeat_at?: string | null;
    agent_task_id?: string | null;
    terminal?: boolean;
    terminal_reason?: string | null;
}

interface AgentRunEvent {
    id: string;
    sequence: number;
    event_type: string;
    level: string;
    message: string;
    payload?: Record<string, any>;
    created_at: string;
    agent_task_id?: string | null;
}

interface AgentTraceSnapshot {
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

interface AgentTraceSpan {
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

interface AgentTraceBundle {
    snapshot?: AgentTraceSnapshot | null;
    spans: AgentTraceSpan[];
    events: AgentRunEvent[];
    memory_injections: Array<Record<string, any>>;
    artifacts: AgentArtifact[];
    temporal?: AgentRunTemporal | null;
    correlation?: Record<string, any>;
}

interface AgentTool {
    id: string;
    label: string;
    description: string;
    category: string;
    tool_name: string;
    risk: 'low' | 'medium' | 'high' | 'destructive';
    requires_mcp_server?: string | null;
}

interface AgentDefinition {
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

interface SpecResult {
    specs?: {
        happy_path?: Record<string, string>;
        edge_cases?: Record<string, string>;
    };
    summary?: string;
    total_specs?: number;
    flows_covered?: string[];
    generated_at?: string;
}

type AuthType = 'none' | 'credentials' | 'session';
type CustomResultTab = 'overview' | 'findings' | 'test_ideas' | 'requirements' | 'evidence' | 'raw';
type ReportSpecBrowserAuthMode = 'session' | 'project_default' | 'none';
type TraceTab = AgentTraceTab;

const AGENT_HISTORY_STATUS_FILTER_LABELS: Record<AgentHistoryStatusFilter, string> = {
    all: 'All',
    active: 'Active',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
    paused: 'Paused',
};

const AGENT_HISTORY_TYPE_FILTER_LABELS: Record<AgentHistoryTypeFilter, string> = {
    all: 'All',
    exploratory: 'Explorer',
    custom: 'Custom',
    writer: 'Writer',
    spec_generation: 'Spec runs',
};

interface ReportSpecBrowserAuthSelection {
    mode: ReportSpecBrowserAuthMode;
    sessionId: string;
}

interface ReportPage {
    id?: string;
    url: string;
    status?: string;
    notes?: string;
}

interface ReportFinding {
    id: string;
    title: string;
    severity?: string;
    confidence?: string;
    page?: string;
    description?: string;
    evidence?: string;
    suggested_action?: string;
}

interface ReportTestIdea {
    id: string;
    title: string;
    priority?: string;
    page?: string;
    steps?: string[];
    expected?: string;
    source_finding_id?: string;
}

interface ReportRequirement {
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

interface ReportEvidence {
    id?: string;
    type?: string;
    label?: string;
    value?: string;
}

interface StructuredAgentReport {
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

interface AgentQueueStatus {
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

interface AgentReportSearchItem {
    run_id: string;
    agent_name?: string;
    created_at?: string;
    type: 'finding' | 'test_idea' | 'requirement' | 'page' | 'evidence' | 'action' | string;
    item: Record<string, any>;
}

function formatToolName(toolName?: string) {
    if (!toolName) return 'Waiting for first tool';
    const short = toolName.includes('__') ? toolName.split('__').pop() || toolName : toolName;
    return short.replace(/^browser_/, '').replace(/_/g, ' ');
}

function customAgentCurrentActivity(progress: any = {}) {
    if (progress.last_tool_label || progress.last_tool) {
        return progress.last_tool_label || formatToolName(progress.last_tool);
    }
    if (progress.phase === 'llm_retry' || progress.retry_attempt) {
        const attempt = progress.retry_attempt ? ` ${progress.retry_attempt}${progress.retry_max_attempts ? `/${progress.retry_max_attempts}` : ''}` : '';
        return `LLM retry${attempt}`;
    }
    return formatToolName('');
}

function sortArtifactsByModifiedAt(artifacts: AgentArtifact[] = []) {
    return [...artifacts].sort((a, b) => {
        const bTime = b.modified_at ? new Date(b.modified_at).getTime() : 0;
        const aTime = a.modified_at ? new Date(a.modified_at).getTime() : 0;
        return bTime - aTime;
    });
}

function getArtifactUrl(artifact: AgentArtifact) {
    return `${API_BASE}${artifact.path}`;
}

function runBrowserAuthSessionId(config: any): string {
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

function defaultReportSpecBrowserAuthSelection(
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

function reportSpecBrowserAuthBody(mode: ReportSpecBrowserAuthMode, sessionId: string) {
    if (mode === 'session') {
        return { browser_auth_session_id: sessionId };
    }
    if (mode === 'project_default') {
        return { use_project_default_browser_auth: true };
    }
    return { skip_browser_auth: true };
}

function AgentRunCapturePanel({
    activeRun,
    mode,
}: {
    activeRun: AgentRun;
    mode: 'live' | 'recording';
}) {
    const artifacts = activeRun.artifacts || [];
    const latestVideo = sortArtifactsByModifiedAt(artifacts.filter(artifact => artifact.type === 'video'))[0];
    const latestImage = sortArtifactsByModifiedAt(artifacts.filter(artifact => artifact.type === 'image'))[0];

    if (!latestVideo && !latestImage && mode === 'recording') {
        return null;
    }

    return (
        <div style={{
            border: '1px solid var(--border)',
            borderRadius: '8px',
            overflow: 'hidden',
            background: 'var(--surface-hover)'
        }}>
            <div style={{
                padding: '0.75rem 1rem',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.75rem'
            }}>
                <h4 style={{
                    margin: 0,
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem'
                }}>
                    {mode === 'live' ? <Monitor size={16} /> : <VideoIcon size={16} />}
                    {mode === 'live' ? 'Live Capture' : 'Recording'}
                </h4>
                {latestVideo && (
                    <a
                        href={getArtifactUrl(latestVideo)}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.35rem',
                            color: 'var(--primary)',
                            fontSize: '0.8rem',
                            textDecoration: 'none',
                            flexShrink: 0
                        }}
                    >
                        Open <ExternalLink size={13} />
                    </a>
                )}
            </div>

            <div style={{ padding: '1rem' }}>
                {latestVideo ? (
                    <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: '#000' }}>
                        <video
                            controls
                            preload="metadata"
                            src={getArtifactUrl(latestVideo)}
                            style={{ width: '100%', display: 'block', aspectRatio: '16/9', background: '#000' }}
                        />
                        <div style={{
                            padding: '0.65rem 0.85rem',
                            background: 'var(--surface)',
                            borderTop: '1px solid var(--border)',
                            fontSize: '0.82rem',
                            color: 'var(--text-secondary)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                        }}>
                            {latestVideo.name}
                        </div>
                    </div>
                ) : latestImage ? (
                    <div>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.4rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.82rem',
                            marginBottom: '0.75rem'
                        }}>
                            <ImageIcon size={14} />
                            Latest screenshot
                        </div>
                        <img
                            src={getArtifactUrl(latestImage)}
                            alt="Latest agent browser screenshot"
                            style={{
                                width: '100%',
                                display: 'block',
                                aspectRatio: '16 / 9',
                                objectFit: 'contain',
                                borderRadius: '8px',
                                border: '1px solid var(--border)',
                                background: '#000'
                            }}
                        />
                    </div>
                ) : (
                    <div style={{
                        minHeight: '90px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--text-secondary)',
                        fontSize: '0.9rem',
                        textAlign: 'center'
                    }}>
                        Waiting for the first browser capture...
                    </div>
                )}
            </div>
        </div>
    );
}

function getStructuredReport(run: AgentRun): StructuredAgentReport {
    return run.result?.structured_report || {
        summary: run.result?.summary || 'Custom agent completed. Review the raw output for details.',
        scope: run.config?.prompt || run.config?.url || '',
        pages_checked: [],
        findings: [],
        test_ideas: [],
        requirements: [],
        evidence: [],
        follow_up_actions: [],
        parse_status: 'raw',
    };
}

function severityColor(value?: string) {
    const normalized = (value || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 'var(--danger)';
    if (normalized === 'medium') return 'var(--warning)';
    if (normalized === 'low') return 'var(--primary)';
    return 'var(--text-secondary)';
}

function reportItemReviewState(item: Record<string, any>, kind: 'finding' | 'test_idea' | 'requirement' | string): ReportReviewFilter {
    if (item.imported_requirement_id || item.imported_requirement_code || item.imported_at) return 'imported';
    if (item.spec_id || item.spec_file || item.generated_spec || item.spec_created_at || item.created_spec_id) return 'spec_created';
    const urgency = String(item.severity || item.priority || '').toLowerCase();
    if (kind === 'finding' || ['critical', 'high'].includes(urgency)) return 'needs_action';
    return 'unreviewed';
}

function reportItemSeverity(item: Record<string, any>) {
    return String(item.severity || item.priority || 'info').toLowerCase();
}

function formatQueueAge(seconds?: number | null) {
    if (!seconds || seconds < 1) return 'None';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}

function queueStateLabel(queue?: AgentQueueStatus | null) {
    if (!queue) return 'Unknown';
    const state = queue.capacity_state || queue.mode || 'available';
    return state.replace(/_/g, ' ');
}

function reportStatusColor(value?: string) {
    const normalized = (value || '').toLowerCase();
    if (normalized.includes('issue') || normalized.includes('failed') || normalized.includes('error')) return 'var(--danger)';
    if (normalized.includes('load') || normalized.includes('pass')) return 'var(--success)';
    return 'var(--text-secondary)';
}

const LIVE_AGENT_STATUSES = new Set(['running', 'pending', 'queued', 'paused']);

function agentStatusTone(status?: string) {
    if (status === 'completed') return { bg: 'var(--success-muted)', color: 'var(--success)' };
    if (status === 'failed' || status === 'cancelled' || status === 'timeout') return { bg: 'var(--danger-muted)', color: 'var(--danger)' };
    if (status === 'paused') return { bg: 'rgba(245, 158, 11, 0.12)', color: 'var(--warning)' };
    return { bg: 'var(--primary-glow)', color: 'var(--primary)' };
}

function agentRunDisplayName(run: AgentRun) {
    if (run.agent_type === 'spec_generation') return 'Spec Generation';
    if (run.agent_type === 'custom') return run.config?.agent_name || 'Custom';
    if (run.agent_type === 'writer') return 'Writer';
    return 'Explorer';
}

function agentRunResultTitle(run: AgentRun) {
    return run.config?.agent_name || run.config?.flow_title || run.config?.url || agentRunDisplayName(run);
}

function customAgentExecutionStarted(run: AgentRun) {
    const progress = run.progress || {};
    if (
        run.agent_task_id ||
        progress.agent_task_id ||
        progress.last_tool ||
        Number(progress.tool_calls || 0) > 0 ||
        Number(progress.browser_tool_calls || 0) > 0 ||
        ['tool_use', 'tool_result', 'running', 'completed', 'failed'].includes(String(progress.phase || '')) ||
        (run.health?.latest_heartbeat_at)
    ) {
        return true;
    }
    const executeActivity = (run.temporal?.activities || []).find(activity => activity.activity_type === 'execute_agent_run');
    if (executeActivity?.status === 'scheduled') return false;
    if (executeActivity && ['started', 'completed', 'failed', 'timed_out'].includes(String(executeActivity.status))) return true;
    return false;
}

function customAgentWorkerMessage(run: AgentRun) {
    const temporalError = run.temporal?.error || run.temporal?.summary?.last_workflow_task_failure;
    if (temporalError) return temporalError;
    if ((run.progress || {}).browser_runtime === 'headless_worker' || (run.progress || {}).live_view_available === false) {
        return 'Browser execution is running outside the VNC display. Follow the latest screenshots and activity timeline.';
    }
    if ((run.progress || {}).phase === 'queued') return 'Agent task is queued for a worker. Browser evidence will appear when the worker starts the task.';
    const executeActivity = (run.temporal?.activities || []).find(activity => activity.activity_type === 'execute_agent_run');
    if (executeActivity?.status === 'scheduled') {
        return `Temporal scheduled agent execution. Waiting for a custom workflow worker on ${run.temporal?.task_queue || 'the workflow task queue'}.`;
    }
    if (run.temporal_workflow_id) return 'Temporal scheduled the run. Waiting for the custom workflow worker to start agent execution.';
    return 'Waiting for the run to be scheduled.';
}

function itemPrompt(run: AgentRun, item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test idea') {
    const title = item.title || item.id;
    return [
        `Use custom agent run ${run.id} (${run.config?.agent_name || 'Custom Agent'}) as context.`,
        `Selected ${kind}: ${item.id} - ${title}`,
        'Create an actionable next step. If it requires changing platform state, prepare an approval action instead of doing it silently.',
    ].join('\n');
}

function CustomAgentReportView({
    run,
    activeTab,
    onTabChange,
    onAskAssistant,
    onCreateSpecFromReport,
    onImportRequirements,
    importingRequirementIds,
    importError,
    reportStatusFilter,
    onReportStatusFilterChange,
    reportSeverityFilter,
    onReportSeverityFilterChange,
}: {
    run: AgentRun;
    activeTab: CustomResultTab;
    onTabChange: (tab: CustomResultTab) => void;
    onAskAssistant: (prompt: string) => void;
    onCreateSpecFromReport: (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => void;
    onImportRequirements: (itemIds?: string[]) => void;
    importingRequirementIds: string[];
    importError?: string | null;
    reportStatusFilter: ReportReviewFilter;
    onReportStatusFilterChange: (value: ReportReviewFilter) => void;
    reportSeverityFilter: string;
    onReportSeverityFilterChange: (value: string) => void;
}) {
    const report = getStructuredReport(run);
    const findings = report.findings || [];
    const testIdeas = report.test_ideas || [];
    const requirements = report.requirements || [];
    const filteredFindings = findings.filter(item => (
        (reportStatusFilter === 'all' || reportItemReviewState(item as unknown as Record<string, any>, 'finding') === reportStatusFilter) &&
        (reportSeverityFilter === 'all' || reportItemSeverity(item as unknown as Record<string, any>) === reportSeverityFilter)
    ));
    const filteredTestIdeas = testIdeas.filter(item => (
        (reportStatusFilter === 'all' || reportItemReviewState(item as unknown as Record<string, any>, 'test_idea') === reportStatusFilter) &&
        (reportSeverityFilter === 'all' || reportItemSeverity(item as unknown as Record<string, any>) === reportSeverityFilter)
    ));
    const filteredRequirements = requirements.filter(item => (
        (reportStatusFilter === 'all' || reportItemReviewState(item as unknown as Record<string, any>, 'requirement') === reportStatusFilter) &&
        (reportSeverityFilter === 'all' || reportItemSeverity(item as unknown as Record<string, any>) === reportSeverityFilter)
    ));
    const unimportedRequirements = requirements.filter(item => !item.imported_requirement_id && !item.imported_requirement_code);
    const pages = report.pages_checked || [];
    const evidence = report.evidence || [];
    const tabs: { key: CustomResultTab; label: string }[] = [
        { key: 'overview', label: 'Overview' },
        { key: 'findings', label: `Findings ${findings.length}` },
        { key: 'test_ideas', label: `Test Ideas ${testIdeas.length}` },
        { key: 'requirements', label: `Requirements ${requirements.length}` },
        { key: 'evidence', label: `Evidence ${evidence.length}` },
        { key: 'raw', label: 'Raw Output' },
    ];
    const basePrompt = `Analyze custom agent run ${run.id} (${run.config?.agent_name || 'Custom Agent'}). Focus on findings, test ideas, and useful follow-up actions.`;
    const selectedTabIndex = tabs.findIndex(tab => tab.key === activeTab);
    const handleReportTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
        if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const lastIndex = tabs.length - 1;
        const nextIndex = event.key === 'Home'
            ? 0
            : event.key === 'End'
            ? lastIndex
            : event.key === 'ArrowRight' || event.key === 'ArrowDown'
            ? (selectedTabIndex + 1) % tabs.length
            : (selectedTabIndex - 1 + tabs.length) % tabs.length;
        onTabChange(tabs[nextIndex].key);
        window.requestAnimationFrame(() => {
            document.getElementById(`agents-report-tab-${tabs[nextIndex].key}`)?.focus();
        });
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ minWidth: 0 }}>
                        <h3 style={{ fontWeight: 700, fontSize: '1rem', margin: '0 0 0.35rem' }}>
                            {run.config?.agent_name || 'Custom Agent'}
                        </h3>
                        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            {run.result?.duration_seconds ? `Completed in ${run.result.duration_seconds.toFixed(1)} seconds` : 'Completed'}
                            {report.parse_status ? ` · ${report.parse_status} report` : ''}
                        </p>
                    </div>
                    <button
                        onClick={() => onAskAssistant(basePrompt)}
                        style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.45rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}
                    >
                        <MessageSquare size={14} /> Ask Assistant
                    </button>
                </div>
                {report.summary && (
                    <p style={{ margin: '0.85rem 0 0', color: 'var(--text)', lineHeight: 1.55, fontSize: '0.92rem' }}>
                        {report.summary}
                    </p>
                )}
            </div>

            <div role="tablist" aria-label="Report sections" style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', borderBottom: '1px solid var(--border)', paddingBottom: '0.6rem' }}>
                {tabs.map(tab => (
                    <button
                        key={tab.key}
                        id={`agents-report-tab-${tab.key}`}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === tab.key}
                        aria-controls={`agents-report-panel-${tab.key}`}
                        tabIndex={activeTab === tab.key ? 0 : -1}
                        onKeyDown={handleReportTabKeyDown}
                        onClick={() => onTabChange(tab.key)}
                        style={{
                            border: '1px solid var(--border)',
                            background: activeTab === tab.key ? 'var(--primary-glow)' : 'var(--background)',
                            color: activeTab === tab.key ? 'var(--primary)' : 'var(--text-secondary)',
                            borderRadius: '6px',
                            padding: '0.4rem 0.65rem',
                            cursor: 'pointer',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                        }}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {activeTab !== 'overview' && activeTab !== 'raw' && activeTab !== 'evidence' && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.65rem', padding: '0.75rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)' }}>
                    <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                        Review state
                        <select
                            value={reportStatusFilter}
                            onChange={event => onReportStatusFilterChange(event.target.value as ReportReviewFilter)}
                            style={{ minHeight: 36, borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', padding: '0.4rem 0.55rem' }}
                        >
                            <option value="all">All review states</option>
                            <option value="needs_action">Needs action</option>
                            <option value="unreviewed">Unreviewed</option>
                            <option value="imported">Imported</option>
                            <option value="spec_created">Spec created</option>
                        </select>
                    </label>
                    <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                        Severity or priority
                        <select
                            value={reportSeverityFilter}
                            onChange={event => onReportSeverityFilterChange(event.target.value)}
                            style={{ minHeight: 36, borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', padding: '0.4rem 0.55rem' }}
                        >
                            <option value="all">All severities</option>
                            <option value="critical">Critical</option>
                            <option value="high">High</option>
                            <option value="medium">Medium</option>
                            <option value="low">Low</option>
                            <option value="info">Info</option>
                        </select>
                    </label>
                </div>
            )}

            {activeTab === 'overview' && (
                <div id="agents-report-panel-overview" role="tabpanel" aria-labelledby="agents-report-tab-overview" style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem' }}>
                        {[
                            { label: 'Pages Checked', value: pages.length, icon: Eye },
                            { label: 'Findings', value: findings.length, icon: Bug },
                            { label: 'Test Ideas', value: testIdeas.length, icon: Lightbulb },
                            { label: 'Requirements', value: requirements.length, icon: CheckCircle2 },
                            { label: 'Tool Calls', value: run.result?.tool_calls?.length || 0, icon: Wrench },
                        ].map(item => {
                            const Icon = item.icon;
                            return (
                                <div key={item.label} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.45rem' }}>
                                        <Icon size={14} /> {item.label}
                                    </div>
                                    <div style={{ fontWeight: 800, fontSize: '1.4rem' }}>{item.value}</div>
                                </div>
                            );
                        })}
                    </div>
                    {report.scope && (
                        <div style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: '0.35rem' }}>Scope</div>
                            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{report.scope}</p>
                        </div>
                    )}
                    {pages.length > 0 && (
                        <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                            <div style={{ padding: '0.7rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 700, fontSize: '0.85rem' }}>Pages Checked</div>
                            {pages.slice(0, 12).map((page, i) => (
                                <div key={`${page.url}-${i}`} style={{ padding: '0.65rem 0.9rem', borderBottom: i === Math.min(pages.length, 12) - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.8rem', fontSize: '0.82rem' }}>
                                    <span style={{ overflowWrap: 'anywhere' }}>{page.url}</span>
                                    <span style={{ color: reportStatusColor(page.status), fontWeight: 700, textTransform: 'capitalize' }}>{page.status || 'unknown'}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'findings' && (
                <div id="agents-report-panel-findings" role="tabpanel" aria-labelledby="agents-report-tab-findings" style={{ display: 'grid', gap: '0.75rem' }}>
                    {filteredFindings.length === 0 ? (
                        <EmptyReportState text="No structured findings were reported." />
                    ) : filteredFindings.map(finding => (
                        <div key={finding.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{finding.id}: {finding.title}</div>
                                <span style={{ color: severityColor(finding.severity), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{finding.severity || 'info'}</span>
                            </div>
                            {finding.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{finding.page}</div>}
                            {finding.description && <p style={{ margin: '0 0 0.45rem', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{finding.description}</p>}
                            {finding.evidence && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem', lineHeight: 1.45 }}><strong>Evidence:</strong> {finding.evidence}</p>}
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <ReportActionButton onClick={() => onAskAssistant(itemPrompt(run, finding, 'finding'))} label="Use in Assistant" icon={MessageSquare} />
                                <ReportActionButton onClick={() => onCreateSpecFromReport(finding, 'finding')} label="Create Spec" icon={FileText} />
                                <ReportActionButton onClick={() => onAskAssistant(`Start a follow-up custom agent from finding ${finding.id} in run ${run.id}. Verify whether this issue still reproduces and collect evidence. Use approval before starting the agent.`)} label="Follow Up Agent" icon={Bot} />
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'test_ideas' && (
                <div id="agents-report-panel-test_ideas" role="tabpanel" aria-labelledby="agents-report-tab-test_ideas" style={{ display: 'grid', gap: '0.75rem' }}>
                    {filteredTestIdeas.length === 0 ? (
                        <EmptyReportState text="No structured test ideas were reported." />
                    ) : filteredTestIdeas.map(idea => (
                        <div key={idea.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{idea.id}: {idea.title}</div>
                                <span style={{ color: severityColor(idea.priority), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{idea.priority || 'medium'}</span>
                            </div>
                            {idea.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{idea.page}</div>}
                            {idea.steps && idea.steps.length > 0 && (
                                <ol style={{ margin: '0.35rem 0 0.55rem 1.15rem', color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45 }}>
                                    {idea.steps.map((step, i) => <li key={`${idea.id}-step-${i}`}>{step}</li>)}
                                </ol>
                            )}
                            {idea.expected && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem' }}><strong>Expected:</strong> {idea.expected}</p>}
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <ReportActionButton onClick={() => onAskAssistant(itemPrompt(run, idea, 'test idea'))} label="Use in Assistant" icon={MessageSquare} />
                                <ReportActionButton onClick={() => onCreateSpecFromReport(idea, 'test_idea')} label="Create Spec" icon={FileText} />
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'requirements' && (
                <div id="agents-report-panel-requirements" role="tabpanel" aria-labelledby="agents-report-tab-requirements" style={{ display: 'grid', gap: '0.75rem' }}>
                    {importError && (
                        <div style={{ padding: '0.75rem 0.9rem', border: '1px solid var(--danger)', borderRadius: '8px', color: 'var(--danger)', background: 'var(--danger-muted)', fontSize: '0.84rem' }}>
                            {importError}
                        </div>
                    )}
                    {requirements.length > 0 && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                {unimportedRequirements.length} candidate{unimportedRequirements.length === 1 ? '' : 's'} ready for review import.
                            </div>
                            <ReportActionButton
                                onClick={() => onImportRequirements()}
                                label={importingRequirementIds.includes('__all__') ? 'Importing...' : 'Import Requirements'}
                                icon={CheckCircle2}
                                disabled={unimportedRequirements.length === 0 || importingRequirementIds.includes('__all__')}
                            />
                        </div>
                    )}
                    {filteredRequirements.length === 0 ? (
                        <EmptyReportState text="No structured requirements were reported." />
                    ) : filteredRequirements.map(requirement => {
                        const imported = Boolean(requirement.imported_requirement_id || requirement.imported_requirement_code);
                        const pending = importingRequirementIds.includes('__all__') || importingRequirementIds.includes(requirement.id);
                        return (
                            <div key={requirement.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                    <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{requirement.id}: {requirement.title}</div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                                        {requirement.category && <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: '0.74rem', textTransform: 'uppercase' }}>{requirement.category}</span>}
                                        <span style={{ color: severityColor(requirement.priority), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{requirement.priority || 'medium'}</span>
                                    </div>
                                </div>
                                {requirement.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{requirement.page}</div>}
                                {requirement.description && <p style={{ margin: '0 0 0.45rem', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{requirement.description}</p>}
                                {requirement.acceptance_criteria && requirement.acceptance_criteria.length > 0 && (
                                    <ul style={{ margin: '0.35rem 0 0.55rem 1.15rem', color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45 }}>
                                        {requirement.acceptance_criteria.map((criterion, i) => <li key={`${requirement.id}-criterion-${i}`}>{criterion}</li>)}
                                    </ul>
                                )}
                                {requirement.evidence && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem', lineHeight: 1.45 }}><strong>Evidence:</strong> {requirement.evidence}</p>}
                                {imported && (
                                    <div style={{ marginBottom: '0.7rem', fontSize: '0.82rem', color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                                        <CheckCircle2 size={14} />
                                        Imported as
                                        <Link href={`/requirements${requirement.imported_requirement_id ? `?highlight=${requirement.imported_requirement_id}` : ''}`} style={{ color: 'var(--primary)', fontWeight: 700 }}>
                                            {requirement.imported_requirement_code || `REQ-${requirement.imported_requirement_id}`}
                                        </Link>
                                    </div>
                                )}
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <ReportActionButton onClick={() => onAskAssistant(`Review candidate requirement ${requirement.id} from custom agent run ${run.id}: ${requirement.title}`)} label="Use in Assistant" icon={MessageSquare} />
                                    <ReportActionButton
                                        onClick={() => onImportRequirements([requirement.id])}
                                        label={pending ? 'Importing...' : imported ? 'Imported' : 'Import'}
                                        icon={CheckCircle2}
                                        disabled={imported || pending}
                                    />
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {activeTab === 'evidence' && (
                <div id="agents-report-panel-evidence" role="tabpanel" aria-labelledby="agents-report-tab-evidence" style={{ display: 'grid', gap: '0.6rem' }}>
                    {evidence.length === 0 ? (
                        <EmptyReportState text="No structured evidence was reported." />
                    ) : evidence.map((item, i) => (
                        <div key={item.id || `${item.label}-${i}`} style={{ padding: '0.75rem 0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.3rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', fontSize: '0.84rem' }}>
                                <strong>{item.label || item.id || `Evidence ${i + 1}`}</strong>
                                <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{item.type || 'note'}</span>
                            </div>
                            {item.value && (
                                item.value.startsWith('/api/') ? (
                                    <a href={`${API_BASE}${item.value}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{item.value}</a>
                                ) : (
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{item.value}</span>
                                )
                            )}
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'raw' && (
                <div id="agents-report-panel-raw" role="tabpanel" aria-labelledby="agents-report-tab-raw" style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ background: '#111827', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                        <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.84rem', color: '#e5e7eb', margin: 0 }}>
                            {run.result?.output || JSON.stringify(run.result, null, 2)}
                        </pre>
                    </div>
                    {run.result?.tool_calls?.length > 0 && (
                        <details>
                            <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem' }}>
                                Tool Calls ({run.result.tool_calls.length})
                            </summary>
                            <div style={{ marginTop: '0.5rem', display: 'grid', gap: '0.4rem' }}>
                                {run.result.tool_calls.map((call: any, i: number) => (
                                    <div key={`${call.name}-${i}`} style={{ padding: '0.5rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.78rem' }}>
                                        <strong>{call.name}</strong>
                                        {call.duration_ms !== undefined && <span style={{ color: 'var(--text-secondary)' }}> · {Math.round(call.duration_ms)}ms</span>}
                                        {call.error && <div style={{ color: 'var(--danger)', marginTop: '0.25rem' }}>{call.error}</div>}
                                    </div>
                                ))}
                            </div>
                        </details>
                    )}
                </div>
            )}
        </div>
    );
}

function EmptyReportState({ text }: { text: string }) {
    return (
        <div style={{ padding: '1.25rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', color: 'var(--text-secondary)', textAlign: 'center', fontSize: '0.86rem' }}>
            {text}
        </div>
    );
}

function ReportActionButton({ onClick, label, icon: Icon, disabled = false }: { onClick: () => void; label: string; icon: any; disabled?: boolean }) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{ border: '1px solid var(--border)', background: 'var(--surface-hover)', color: disabled ? 'var(--text-secondary)' : 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.6rem', cursor: disabled ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: disabled ? 0.65 : 1 }}
        >
            <Icon size={13} /> {label}
        </button>
    );
}

function TraceJsonBlock({ title, value }: { title: string; value: any }) {
    if (value === undefined || value === null || value === '') return null;
    return (
        <details style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
            <summary style={{ cursor: 'pointer', padding: '0.55rem 0.7rem', fontWeight: 700, fontSize: '0.78rem' }}>{title}</summary>
            <pre style={{ margin: 0, padding: '0.7rem', borderTop: '1px solid var(--border)', overflowX: 'auto', whiteSpace: 'pre-wrap', fontSize: '0.74rem', lineHeight: 1.45, color: 'var(--text-secondary)' }}>
                {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
            </pre>
        </details>
    );
}

function TracePill({ label, value }: { label: string; value: any }) {
    if (value === undefined || value === null || value === '') return null;
    return (
        <span style={{ display: 'inline-flex', gap: '0.35rem', alignItems: 'center', padding: '0.32rem 0.48rem', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', fontSize: '0.75rem', maxWidth: '100%' }}>
            <strong style={{ color: 'var(--text-secondary)' }}>{label}</strong>
            <span style={{ overflowWrap: 'anywhere' }}>{String(value)}</span>
        </span>
    );
}

function AgentRunObservabilityPanel({
    run,
    events,
    trace,
    traceLoading = false,
    traceSearch = '',
    onTraceSearch,
    traceSpanType = '',
    onTraceSpanType,
    onExportTrace,
    activeTraceTab = 'timeline',
    onTraceTabChange,
}: {
    run: AgentRun;
    events: AgentRunEvent[];
    trace?: AgentTraceBundle | null;
    traceLoading?: boolean;
    traceSearch?: string;
    onTraceSearch?: (value: string) => void;
    traceSpanType?: string;
    onTraceSpanType?: (value: string) => void;
    onExportTrace?: () => void;
    activeTraceTab?: TraceTab;
    onTraceTabChange?: (value: TraceTab) => void;
}) {
    const health = run.health || {};
    const temporal = run.temporal || {};
    const [internalTraceTab, setInternalTraceTab] = useState<TraceTab>(activeTraceTab);
    const selectedTraceTab = onTraceTabChange ? activeTraceTab : internalTraceTab;
    const changeTraceTab = (tab: TraceTab) => {
        if (onTraceTabChange) onTraceTabChange(tab);
        else setInternalTraceTab(tab);
    };
    const traceSpans = trace?.spans || [];
    const searchableTraceSpans = useMemo(() => traceSpans.map(span => ({
        span,
        searchText: [
            span.name,
            span.message,
            span.span_type,
            span.tool_name,
            span.content_hash,
            span.payload ? JSON.stringify(span.payload) : '',
            span.input_preview ? JSON.stringify(span.input_preview) : '',
            span.output_preview ? JSON.stringify(span.output_preview) : '',
        ].join(' ').toLowerCase(),
    })), [traceSpans]);
    const filteredSpans = useMemo(() => searchableTraceSpans.filter(({ span, searchText }) => {
        if (traceSpanType && span.span_type !== traceSpanType) return false;
        if (!traceSearch.trim()) return true;
        const query = traceSearch.toLowerCase();
        return searchText.includes(query);
    }).map(item => item.span), [searchableTraceSpans, traceSearch, traceSpanType]);
    const recentEvents = events.slice(-12).reverse();
    const visibleSpans = filteredSpans.slice(-80).reverse();
    const toolSpans = filteredSpans.filter(span => span.span_type === 'tool_call' || span.span_type === 'tool_result');
    const spanTypes = Array.from(new Set(traceSpans.map(span => span.span_type))).sort();
    const logArtifacts = sortArtifactsByModifiedAt((run.artifacts || []).filter(artifact => artifact.type === 'log'));
    const traceArtifacts = trace?.artifacts || [];
    const snapshot = trace?.snapshot;
    const memoryInjections = trace?.memory_injections || [];
    const traceTabs: Array<{ key: TraceTab; label: string; icon: any }> = [
        { key: 'timeline', label: 'Timeline', icon: Clock },
        { key: 'context', label: 'Context', icon: FileText },
        { key: 'tools', label: 'Tools', icon: Wrench },
        { key: 'memory', label: 'Memory', icon: Database },
        { key: 'runtime', label: 'Runtime', icon: Cpu },
        { key: 'artifacts', label: 'Artifacts', icon: PackageOpen },
    ];
    const copyText = (value: string | null | undefined) => {
        if (!value || typeof navigator === 'undefined') return;
        void navigator.clipboard?.writeText(value);
    };

    return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.65rem' }}>
                {[
                    { label: 'Events', value: health.event_count ?? events.length, icon: List },
                    { label: 'Tool Events', value: health.tool_event_count ?? 0, icon: Wrench },
                    { label: 'Errors', value: health.error_event_count ?? 0, icon: AlertTriangle },
                    { label: 'Temporal', value: temporal.error ? 'Error' : temporal.workflow_status || (run.temporal_workflow_id ? 'Scheduled' : 'Not linked'), icon: RotateCcw },
                    { label: 'Task', value: run.agent_task_id ? run.agent_task_id.slice(0, 12) : 'Not queued', icon: Terminal },
                ].map(item => {
                    const Icon = item.icon;
                    return (
                        <div key={item.label} style={{ padding: '0.75rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.72rem', marginBottom: '0.35rem', textTransform: 'uppercase' }}>
                                <Icon size={13} /> {item.label}
                            </div>
                            <div style={{ fontWeight: 800, fontSize: '0.95rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.value}</div>
                        </div>
                    );
                })}
            </div>

            {(run.temporal_workflow_id || temporal.error) && (
                <div style={{ padding: '0.75rem 0.85rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.35rem', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <strong>Temporal workflow</strong>
                        <span style={{ color: temporal.available ? 'var(--success)' : 'var(--text-secondary)', fontWeight: 700 }}>
                            {temporal.workflow_status || (temporal.available ? 'Available' : 'Unknown')}
                        </span>
                    </div>
                    {run.temporal_workflow_id && (
                        <div style={{ color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>{run.temporal_workflow_id}</div>
                    )}
                    {(temporal.temporal_namespace || temporal.task_queue) && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            {temporal.temporal_namespace && <span>Namespace: {temporal.temporal_namespace}</span>}
                            {temporal.task_queue && <span>Queue: {temporal.task_queue}</span>}
                        </div>
                    )}
                    {temporal.summary && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            <span>Activities: {temporal.summary.total_activities ?? 0}</span>
                            <span>Retries: {temporal.summary.retry_count ?? 0}</span>
                            <span>Failures: {temporal.summary.failed_activities ?? 0}</span>
                        </div>
                    )}
                    {temporal.task_queue_status && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            <span>Workflow pollers: {temporal.task_queue_status.workflow_pollers ?? 0}</span>
                            <span>Activity pollers: {temporal.task_queue_status.activity_pollers ?? 0}</span>
                        </div>
                    )}
                    {(temporal.activities || []).length > 0 && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            {(temporal.activities || []).slice(-3).map((activity, index) => (
                                <span key={`${activity.activity_type}-${index}`}>
                                    {activity.activity_type}: {activity.status}
                                </span>
                            ))}
                        </div>
                    )}
                    {temporal.summary?.last_failure && (
                        <div style={{ color: 'var(--danger)', overflowWrap: 'anywhere' }}>Last failure: {temporal.summary.last_failure}</div>
                    )}
                    {temporal.error && (
                        <div style={{ color: 'var(--warning)', overflowWrap: 'anywhere' }}>{temporal.error}</div>
                    )}
                    {(temporal.temporal_ui_workflow_url || temporal.temporal_ui_url) && run.temporal_workflow_id && (
                        <a href={temporal.temporal_ui_workflow_url || temporal.temporal_ui_url || '#'} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontWeight: 600 }}>
                            Open Temporal UI <ExternalLink size={13} />
                        </a>
                    )}
                </div>
            )}

            <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                <div style={{ padding: '0.65rem 0.85rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                        {traceTabs.map(tab => {
                            const Icon = tab.icon;
                            return (
                                <button key={tab.key} type="button" onClick={() => changeTraceTab(tab.key)} style={{ border: '1px solid var(--border)', background: selectedTraceTab === tab.key ? 'var(--primary-glow)' : 'var(--surface-hover)', color: selectedTraceTab === tab.key ? 'var(--primary)' : 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.55rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.32rem', fontSize: '0.76rem', fontWeight: 700 }}>
                                    <Icon size={13} /> {tab.label}
                                </button>
                            );
                        })}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                        {traceLoading && <Loader2 size={14} className="spin" style={{ color: 'var(--primary)' }} />}
                        {onExportTrace && (
                            <button type="button" onClick={onExportTrace} title="Export redacted trace" style={{ border: '1px solid var(--border)', background: 'var(--surface-hover)', color: 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.55rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.32rem', fontSize: '0.76rem', fontWeight: 700 }}>
                                <Download size={13} /> Export
                            </button>
                        )}
                    </div>
                </div>

                <div style={{ padding: '0.75rem', display: 'grid', gap: '0.65rem' }}>
                    {(selectedTraceTab === 'timeline' || selectedTraceTab === 'tools') && (
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <div style={{ position: 'relative', flex: '1 1 220px' }}>
                                <Search size={13} style={{ position: 'absolute', left: '0.55rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                                <label htmlFor={`agent-trace-search-${run.id}`} className="agents-visually-hidden">Search trace events and spans</label>
                                <input id={`agent-trace-search-${run.id}`} aria-label="Search trace events and spans" value={traceSearch} onChange={event => onTraceSearch?.(event.target.value)} placeholder="Search trace" style={{ width: '100%', padding: '0.42rem 0.55rem 0.42rem 1.8rem', borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', fontSize: '0.78rem' }} />
                            </div>
                            <label htmlFor={`agent-trace-span-type-${run.id}`} className="agents-visually-hidden">Filter trace by span type</label>
                            <select id={`agent-trace-span-type-${run.id}`} aria-label="Filter trace by span type" value={traceSpanType} onChange={event => onTraceSpanType?.(event.target.value)} style={{ padding: '0.42rem 0.55rem', borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', fontSize: '0.78rem' }}>
                                <option value="">All spans</option>
                                {spanTypes.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>)}
                            </select>
                        </div>
                    )}

                    {selectedTraceTab === 'timeline' && (
                        traceSpans.length > 0 ? (
                            <div style={{ display: 'grid', gap: '0.45rem' }}>
                                {visibleSpans.map(span => (
                                    <details key={span.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                        <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '0.6rem', alignItems: 'center', fontSize: '0.8rem' }}>
                                            <span style={{ color: span.level === 'error' ? 'var(--danger)' : span.level === 'warning' ? 'var(--warning)' : 'var(--primary)', fontWeight: 800 }}>#{span.sequence}</span>
                                            <span style={{ minWidth: 0 }}>
                                                <strong style={{ textTransform: 'capitalize' }}>{span.name || span.span_type.replace(/_/g, ' ')}</strong>
                                                <span style={{ color: 'var(--text-secondary)' }}> · {span.span_type.replace(/_/g, ' ')}</span>
                                                {span.tool_name && <span style={{ color: 'var(--text-secondary)' }}> · {formatToolName(span.tool_name)}</span>}
                                            </span>
                                            <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{new Date(span.created_at).toLocaleTimeString()}</span>
                                        </summary>
                                        <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                            {span.message && <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', overflowWrap: 'anywhere' }}>{span.message}</div>}
                                            <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                                                <TracePill label="duration" value={span.duration_ms != null ? `${Math.round(span.duration_ms)}ms` : null} />
                                                <TracePill label="hash" value={span.content_hash?.slice(0, 16)} />
                                                <TracePill label="event" value={span.agent_run_event_id} />
                                            </div>
                                            <TraceJsonBlock title="Input preview" value={span.input_preview} />
                                            <TraceJsonBlock title="Output preview" value={span.output_preview} />
                                            <TraceJsonBlock title="Payload" value={span.payload} />
                                        </div>
                                    </details>
                                ))}
                            </div>
                        ) : recentEvents.length > 0 ? (
                            <div style={{ display: 'grid' }}>
                                {recentEvents.map((event, index) => (
                                    <div key={event.id} style={{ padding: '0.6rem 0', borderBottom: index === recentEvents.length - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '0.6rem', alignItems: 'start', fontSize: '0.8rem' }}>
                                        <span style={{ color: event.level === 'error' ? 'var(--danger)' : event.level === 'warning' ? 'var(--warning)' : 'var(--primary)', fontWeight: 800 }}>#{event.sequence}</span>
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ fontWeight: 700, textTransform: 'capitalize' }}>{event.event_type.replace(/_/g, ' ')}</div>
                                            <div style={{ color: 'var(--text-secondary)', overflowWrap: 'anywhere', marginTop: '0.15rem' }}>{event.message}</div>
                                        </div>
                                        <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{new Date(event.created_at).toLocaleTimeString()}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No durable events have been recorded yet.</div>
                        )
                    )}

                    {selectedTraceTab === 'context' && (
                        <div style={{ display: 'grid', gap: '0.65rem' }}>
                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                <TracePill label="trace" value={snapshot?.trace_id} />
                                <TracePill label="prompt" value={snapshot?.prompt_hash?.slice(0, 20)} />
                                <TracePill label="context" value={snapshot?.context_hash?.slice(0, 20)} />
                                <TracePill label="memory" value={snapshot?.memory_block_hash?.slice(0, 20)} />
                            </div>
                            {snapshot?.trace_id && <button type="button" onClick={() => copyText(snapshot.trace_id)} style={{ justifySelf: 'start', border: '1px solid var(--border)', background: 'var(--surface-hover)', color: 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.55rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.32rem', fontSize: '0.76rem', fontWeight: 700 }}><Copy size={13} /> Copy trace ID</button>}
                            <TraceJsonBlock title="Prompt preview" value={snapshot?.prompt_preview || 'No prompt snapshot captured yet.'} />
                            <TraceJsonBlock title="Memory/context preview" value={snapshot?.memory_preview} />
                            <TraceJsonBlock title="Allowed tools" value={snapshot?.allowed_tools || []} />
                            <TraceJsonBlock title="Test data refs" value={snapshot?.test_data_refs || []} />
                            {(snapshot?.prompt_artifact_path || snapshot?.context_artifact_path) && (
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    {snapshot.prompt_artifact_path && <a href={`${API_BASE}${snapshot.prompt_artifact_path}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.78rem', textDecoration: 'none' }}>Open redacted prompt</a>}
                                    {snapshot.context_artifact_path && <a href={`${API_BASE}${snapshot.context_artifact_path}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.78rem', textDecoration: 'none' }}>Open redacted context</a>}
                                </div>
                            )}
                        </div>
                    )}

                    {selectedTraceTab === 'tools' && (
                        <div style={{ display: 'grid', gap: '0.45rem' }}>
                            {toolSpans.length > 0 ? toolSpans.slice(-80).reverse().map(span => (
                                <details key={span.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                    <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', fontSize: '0.8rem' }}>
                                        <strong>{formatToolName(span.tool_name || span.name)}</strong>
                                        <span style={{ color: span.success === false ? 'var(--danger)' : 'var(--text-secondary)' }}>{span.duration_ms != null ? `${Math.round(span.duration_ms)}ms` : span.span_type}</span>
                                    </summary>
                                    <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                        {span.message && <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{span.message}</div>}
                                        <TraceJsonBlock title="Input" value={span.input_preview} />
                                        <TraceJsonBlock title="Output" value={span.output_preview} />
                                        <TraceJsonBlock title="Raw span" value={span} />
                                    </div>
                                </details>
                            )) : <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No tool trace spans have been recorded yet.</div>}
                        </div>
                    )}

                    {selectedTraceTab === 'memory' && (
                        <div style={{ display: 'grid', gap: '0.5rem' }}>
                            {memoryInjections.length > 0 ? memoryInjections.map(item => (
                                <details key={item.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                    <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', fontSize: '0.8rem' }}>
                                        <strong>{item.stage || 'memory injection'}</strong>
                                        <span style={{ color: 'var(--text-secondary)' }}>{(item.memory_ids || []).length} memories</span>
                                    </summary>
                                    <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                        <TraceJsonBlock title="Context preview" value={item.context_preview} />
                                        <TraceJsonBlock title="Memory IDs" value={item.memory_ids || []} />
                                        <TraceJsonBlock title="Telemetry" value={item.extra_data || {}} />
                                    </div>
                                </details>
                            )) : <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No linked memory injections were found for this run.</div>}
                        </div>
                    )}

                    {selectedTraceTab === 'runtime' && (
                        <div style={{ display: 'grid', gap: '0.65rem' }}>
                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                <TracePill label="runtime" value={snapshot?.runtime || run.runtime} />
                                <TracePill label="model" value={snapshot?.model} />
                                <TracePill label="tier" value={snapshot?.model_tier} />
                                <TracePill label="task" value={run.agent_task_id} />
                                <TracePill label="workflow" value={run.temporal_workflow_id} />
                            </div>
                            <TraceJsonBlock title="Runtime diagnostics" value={snapshot?.runtime_diagnostics || {}} />
                            <TraceJsonBlock title="Temporal summary" value={trace?.temporal || temporal || {}} />
                            <TraceJsonBlock title="Correlation IDs" value={trace?.correlation || { run_id: run.id, agent_task_id: run.agent_task_id, temporal_workflow_id: run.temporal_workflow_id }} />
                        </div>
                    )}

                    {selectedTraceTab === 'artifacts' && (
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                            {[...traceArtifacts, ...logArtifacts].length > 0 ? [...traceArtifacts, ...logArtifacts].map(artifact => (
                                <a key={`${artifact.type}-${artifact.path}`} href={getArtifactUrl(artifact)} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.38rem 0.6rem', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--primary)', textDecoration: 'none', fontSize: '0.78rem', fontWeight: 600 }}>
                                    <FileText size={13} /> {artifact.name}
                                </a>
                            )) : <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No trace artifacts are available yet.</div>}
                        </div>
                    )}
                </div>
            </div>

            {logArtifacts.length > 0 && (
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {logArtifacts.slice(0, 4).map(artifact => (
                        <a key={artifact.path} href={getArtifactUrl(artifact)} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.38rem 0.6rem', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--primary)', textDecoration: 'none', fontSize: '0.78rem', fontWeight: 600 }}>
                            <FileText size={13} /> {artifact.name}
                        </a>
                    ))}
                </div>
            )}
        </div>
    );
}

function SpecGenerationRunPanel({ run, events }: { run: AgentRun; events: AgentRunEvent[] }) {
    const progress = run.progress || {};
    const latestImage = sortArtifactsByModifiedAt((run.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
    const recentTools = progress.recent_tools || [];
    const errorMessage = run.result?.error || (run.status === 'failed' ? progress.message : null);
    const specFile = run.result?.spec_file;
    const specContent = run.result?.spec_content;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
                gap: '0.5rem',
                padding: '0.75rem',
                background: 'var(--surface-hover)',
                border: '1px solid var(--border)',
                borderRadius: '8px'
            }}>
                {[
                    { label: 'Status', value: run.status },
                    { label: 'Phase', value: progress.phase || 'queued' },
                    { label: 'Current Step', value: progress.last_tool_label || progress.message || 'Preparing browser' },
                    { label: 'Browser Actions', value: progress.browser_tool_calls ?? 0 },
                ].map(item => (
                    <div key={item.label} style={{ minWidth: 0, padding: '0.65rem', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--background)' }}>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>{item.label}</div>
                        <div style={{ fontWeight: 700, overflowWrap: 'anywhere', textTransform: item.label === 'Status' || item.label === 'Phase' ? 'capitalize' : 'none', lineHeight: 1.3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{item.value}</div>
                    </div>
                ))}
            </div>

            {errorMessage && (
                <div style={{ padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '8px', border: '1px solid rgba(248, 113, 113, 0.2)' }}>
                    <h4 style={{ margin: 0, fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <AlertTriangle size={18} /> Spec Generation Failed
                    </h4>
                    <p style={{ margin: '0.5rem 0 0', fontFamily: 'monospace', overflowWrap: 'anywhere' }}>{errorMessage}</p>
                </div>
            )}

            <LiveBrowserView
                runId={run.id}
                isActive={LIVE_AGENT_STATUSES.has(run.status) && run.status !== 'paused'}
                showHeader
                artifacts={run.artifacts || []}
                latestImage={latestImage}
                statusMessage={progress.message}
                liveViewAvailable={Boolean(progress.live_view_available ?? true)}
                runtimeMessage={progress.runtime_message}
                vncUrl={progress.vnc_url}
            />

            <AgentRunCapturePanel activeRun={run} mode={LIVE_AGENT_STATUSES.has(run.status) ? 'live' : 'recording'} />
            <AgentRunObservabilityPanel run={run} events={events} />

            {latestImage && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                        <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <ImageIcon size={15} /> Latest Screenshot
                        </h4>
                        {latestImage.modified_at && <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{new Date(latestImage.modified_at).toLocaleTimeString()}</span>}
                    </div>
                    <a href={getArtifactUrl(latestImage)} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                        <img src={getArtifactUrl(latestImage)} alt="Latest spec generation screenshot" style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', maxHeight: '420px', objectFit: 'contain', background: '#000' }} />
                    </a>
                </div>
            )}

            {recentTools.length > 0 && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>Live Activity</div>
                    {recentTools.slice().reverse().map((tool: any, i: number) => (
                        <div key={`${tool.name}-${tool.at}-${i}`} style={{ padding: '0.65rem 1rem', borderBottom: i === recentTools.length - 1 ? 'none' : '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', fontSize: '0.85rem' }}>
                            <span style={{ fontWeight: 600 }}>{tool.label || formatToolName(tool.name)}</span>
                            {tool.at && <span style={{ color: 'var(--text-secondary)' }}>{new Date(tool.at).toLocaleTimeString()}</span>}
                        </div>
                    ))}
                </div>
            )}

            {run.status === 'completed' && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'center' }}>
                        <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <FileText size={15} /> Generated Spec
                        </h4>
                        {specFile && <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>{specFile}</span>}
                    </div>
                    {specContent ? (
                        <pre style={{ margin: 0, padding: '1rem', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', lineHeight: 1.6, maxHeight: '420px', overflow: 'auto', background: 'var(--code-bg)' }}>{specContent}</pre>
                    ) : (
                        <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                            Spec generated. Open the artifact or specs page to inspect the file.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function QueueStatusPanel({
    queue,
    loading,
    error,
    onRefresh,
}: {
    queue: AgentQueueStatus | null;
    loading: boolean;
    error: string | null;
    onRefresh: () => void;
}) {
    const stale = queue?.stale_running ?? 0;
    const orphaned = queue?.orphaned_tasks ?? 0;
    const workerCount = queue?.workers_alive ?? queue?.worker_processes_alive ?? 0;
    const browserPool = queue?.browser_pool || {};
    const browserMax = Number(browserPool.max_browsers ?? queue?.max ?? 0);
    const browserRunning = Number(browserPool.running ?? queue?.pool_status?.total_running ?? 0);
    const browserAvailable = Number(browserPool.available ?? queue?.available ?? Math.max(0, browserMax - browserRunning));
    const warnings = [
        stale > 0 ? `${stale} stale running task${stale === 1 ? '' : 's'}` : '',
        orphaned > 0 ? `${orphaned} orphaned task${orphaned === 1 ? '' : 's'}` : '',
        (queue?.active || queue?.queued || 0) > 0 && workerCount === 0 ? 'No live workers for active queue work' : '',
    ].filter(Boolean);

    return (
        <div className="card" style={{ padding: '1rem', display: 'grid', gap: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Queue Capacity</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {queue ? `${queue.mode || 'agent'} mode · ${queueStateLabel(queue)}` : 'Queue status has not loaded yet.'}
                    </p>
                </div>
                <Button type="button" variant="outline" onClick={onRefresh} disabled={loading}>
                    {loading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />} Refresh
                </Button>
            </div>
            {error && (
                <Alert variant="destructive">
                    <AlertTriangle size={16} />
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.75rem' }}>
                {[
                    ['Active runs', queue?.active ?? 0],
                    ['Queued runs', queue?.queued ?? 0],
                    ['Workers alive', workerCount],
                    ['Workers idle', queue?.workers_idle ?? 0],
                    ['Browser slots', browserMax ? `${browserRunning}/${browserMax}` : `${browserRunning}`],
                    ['Available slots', browserAvailable],
                    ['Oldest queued', formatQueueAge(queue?.oldest_queued_age_seconds)],
                    ['Health', warnings.length ? 'Watch' : 'Stable'],
                ].map(([label, value]) => (
                    <div key={label} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)', minWidth: 0 }}>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', textTransform: 'uppercase', fontWeight: 800, marginBottom: '0.35rem' }}>{label}</div>
                        <div style={{ fontWeight: 850, fontSize: '1.1rem', overflowWrap: 'anywhere', color: label === 'Health' && warnings.length ? 'var(--warning)' : 'var(--text)' }}>{String(value)}</div>
                    </div>
                ))}
            </div>
            {warnings.length > 0 && (
                <div style={{ padding: '0.85rem', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: '8px', background: 'rgba(245, 158, 11, 0.12)', color: 'var(--warning)', display: 'grid', gap: '0.35rem', fontSize: '0.85rem', fontWeight: 700 }}>
                    {warnings.map(item => <div key={item}>{item}</div>)}
                </div>
            )}
            {(queue?.running_tasks || []).length > 0 && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
                    <div style={{ padding: '0.75rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 800 }}>Running tasks</div>
                    {(queue?.running_tasks || []).slice(0, 8).map((task, index) => (
                        <div key={String(task.id || index)} style={{ padding: '0.65rem 0.9rem', borderBottom: index === Math.min((queue?.running_tasks || []).length, 8) - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '0.75rem', fontSize: '0.82rem' }}>
                            <span style={{ overflowWrap: 'anywhere' }}>
                                {String(task.agent_type || task.operation_type || 'agent task')}
                                {task.id ? ` · ${String(task.id)}` : ''}
                            </span>
                            <span style={{ color: task.orphaned ? 'var(--warning)' : 'var(--text-secondary)', fontWeight: 700 }}>{String(task.status || 'running')}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function ReportsSearchWorkspace({
    query,
    onQueryChange,
    type,
    onTypeChange,
    severity,
    onSeverityChange,
    loading,
    results,
    onRefresh,
}: {
    query: string;
    onQueryChange: (value: string) => void;
    type: ReportSearchTypeFilter;
    onTypeChange: (value: ReportSearchTypeFilter) => void;
    severity: string;
    onSeverityChange: (value: string) => void;
    loading: boolean;
    results: AgentReportSearchItem[];
    onRefresh: () => void;
}) {
    return (
        <div className="card" style={{ padding: '1rem', display: 'grid', gap: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Search Reports</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Findings, test ideas, requirements, evidence, and checked pages.</p>
                </div>
                <Button type="button" variant="outline" onClick={onRefresh} disabled={loading}>
                    {loading ? <Loader2 className="spin" size={14} /> : <Search size={14} />} Search
                </Button>
            </div>
            <div className="agents-report-search-grid">
                <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                    Search reports
                    <Input value={query} onChange={event => onQueryChange(event.target.value)} placeholder="Checkout, REQ, selector, URL" />
                </label>
                <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                    Type
                    <select value={type} onChange={event => onTypeChange(event.target.value as ReportSearchTypeFilter)} style={{ minHeight: 40, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--background-raised)', color: 'var(--text)', padding: '0.5rem' }}>
                        <option value="all">All types</option>
                        <option value="finding">Findings</option>
                        <option value="test_idea">Test ideas</option>
                        <option value="requirement">Requirements</option>
                        <option value="page">Pages checked</option>
                        <option value="evidence">Evidence</option>
                        <option value="action">Actions</option>
                    </select>
                </label>
                <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                    Severity
                    <select value={severity} onChange={event => onSeverityChange(event.target.value)} style={{ minHeight: 40, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--background-raised)', color: 'var(--text)', padding: '0.5rem' }}>
                        <option value="all">All</option>
                        <option value="critical">Critical</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                    </select>
                </label>
            </div>
            <div style={{ display: 'grid', gap: '0.65rem' }}>
                {loading ? (
                    <div style={{ padding: '2rem', color: 'var(--text-secondary)', textAlign: 'center' }}><Loader2 className="spin" size={18} /> Searching reports...</div>
                ) : results.length === 0 ? (
                    <EmptyReportState text="No report items match the current search." />
                ) : results.map(result => {
                    const item = result.item || {};
                    const title = item.title || item.label || item.url || item.id || result.type;
                    const state = reportItemReviewState(item, result.type);
                    return (
                        <div key={`${result.run_id}-${result.type}-${item.id || title}`} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.45rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                                <strong style={{ overflowWrap: 'anywhere' }}>{title}</strong>
                                <span style={{ color: severityColor(item.severity || item.priority), fontWeight: 800, textTransform: 'uppercase', fontSize: '0.76rem' }}>{item.severity || item.priority || state}</span>
                            </div>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                                <span>{result.type.replace(/_/g, ' ')}</span>
                                <span>{result.agent_name || 'Custom Agent'}</span>
                                {result.created_at && <span>{new Date(result.created_at).toLocaleString()}</span>}
                            </div>
                            {(item.description || item.evidence || item.value) && (
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45, overflowWrap: 'anywhere' }}>{item.description || item.evidence || item.value}</div>
                            )}
                            <div>
                                <Link href={`/agents?runId=${encodeURIComponent(result.run_id)}&view=reports&resultTab=${result.type === 'test_idea' ? 'test_ideas' : result.type === 'requirement' ? 'requirements' : result.type === 'evidence' ? 'evidence' : 'findings'}`} style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.82rem' }}>
                                    Open report
                                </Link>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default function AgentsPage() {
    const { currentProject } = useProject();
    const [workspaceView, setWorkspaceView] = useState<AgentWorkspaceView>('run');
    const [selectedAgent, setSelectedAgent] = useState<AgentWorkspaceMode>('exploratory');

    // Basic config
    const [url, setUrl] = useState('');
    const [instructions, setInstructions] = useState('');

    // Enhanced exploratory config
    const [timeLimitMinutes, setTimeLimitMinutes] = useState(15);
    const [authType, setAuthType] = useState<AuthType>('none');
    const [authCredentials, setAuthCredentials] = useState({ username: '', password: '', loginUrl: '/login' });
    const [sessionId, setSessionId] = useState('');
    const [testData, setTestData] = useState('');
    const [testDataRefs, setTestDataRefs] = useState('');
    const [focusAreas, setFocusAreas] = useState('');
    const [excludedPatterns, setExcludedPatterns] = useState('');

    // History & results
    const [history, setHistory] = useState<AgentRun[]>([]);
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
    const [agentEvents, setAgentEvents] = useState<AgentRunEvent[]>([]);
    const [agentTrace, setAgentTrace] = useState<AgentTraceBundle | null>(null);
    const [traceLoading, setTraceLoading] = useState(false);
    const [traceSearch, setTraceSearch] = useState('');
    const [traceSpanType, setTraceSpanType] = useState('');
    const [specResult, setSpecResult] = useState<SpecResult | null>(null);
    const [historySearch, setHistorySearch] = useState('');
    const [historyStatusFilter, setHistoryStatusFilter] = useState<AgentHistoryStatusFilter>('all');
    const [historyTypeFilter, setHistoryTypeFilter] = useState<AgentHistoryTypeFilter>('all');

    // UI state
    const [isStarting, setIsStarting] = useState(false);
    const [runControlPending, setRunControlPending] = useState<'pause' | 'resume' | 'cancel' | null>(null);
    const [isSynthesizing, setIsSynthesizing] = useState(false);
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [sessions, setSessions] = useState<BrowserAuthSession[]>([]);
    const [flowModalOpen, setFlowModalOpen] = useState(false);
    const [selectedFlow, setSelectedFlow] = useState<any | null>(null);
    const [loadingFlowDetails, setLoadingFlowDetails] = useState(false);
    const [generatingSpec, setGeneratingSpec] = useState(false);
    const [flowSpecAgentRunId, setFlowSpecAgentRunId] = useState<string | null>(null);
    const [flowSpecAgentRun, setFlowSpecAgentRun] = useState<AgentRun | null>(null);
    const [flowSpecAgentEvents, setFlowSpecAgentEvents] = useState<AgentRunEvent[]>([]);
    const [flowSpecError, setFlowSpecError] = useState<string | null>(null);
    const [reportSpecAuthMode, setReportSpecAuthMode] = useState<ReportSpecBrowserAuthMode>('none');
    const [reportSpecAuthSessionId, setReportSpecAuthSessionId] = useState('');
    const [generatedSpec, setGeneratedSpec] = useState<any | null>(null);
    const [specModalOpen, setSpecModalOpen] = useState(false);
    const [splittingSpec, setSplittingSpec] = useState(false);
    const [splitResult, setSplitResult] = useState<{ count: number; files: string[]; output_dir: string } | null>(null);
    const [agentDefinitions, setAgentDefinitions] = useState<AgentDefinition[]>([]);
    const [toolCatalog, setToolCatalog] = useState<AgentTool[]>([]);
    const [selectedDefinitionId, setSelectedDefinitionId] = useState<string>('');
    const [customResultTab, setCustomResultTab] = useState<CustomResultTab>('overview');
    const [traceTab, setTraceTab] = useState<TraceTab>('timeline');
    const [reportStatusFilter, setReportStatusFilter] = useState<ReportReviewFilter>('all');
    const [reportSeverityFilter, setReportSeverityFilter] = useState('all');
    const [reportSearchQuery, setReportSearchQuery] = useState('');
    const [reportSearchType, setReportSearchType] = useState<ReportSearchTypeFilter>('all');
    const [reportSearchSeverity, setReportSearchSeverity] = useState('all');
    const [reportSearchResults, setReportSearchResults] = useState<AgentReportSearchItem[]>([]);
    const [reportSearchLoading, setReportSearchLoading] = useState(false);
    const [queueStatus, setQueueStatus] = useState<AgentQueueStatus | null>(null);
    const [queueLoading, setQueueLoading] = useState(false);
    const [queueError, setQueueError] = useState<string | null>(null);
    const [runFormError, setRunFormError] = useState<string | null>(null);
    const [definitionFormError, setDefinitionFormError] = useState<string | null>(null);
    const [workspaceStatus, setWorkspaceStatus] = useState('');
    const [historyOpen, setHistoryOpen] = useState(true);
    const [setupOpen, setSetupOpen] = useState(true);
    const [openDefinitionMenuId, setOpenDefinitionMenuId] = useState<string | null>(null);
    const [archiveCandidate, setArchiveCandidate] = useState<AgentDefinition | null>(null);
    const [cancelRunDialogOpen, setCancelRunDialogOpen] = useState(false);
    const [returnToAfterSave, setReturnToAfterSave] = useState('');
    const [importingRequirementIds, setImportingRequirementIds] = useState<string[]>([]);
    const [reportImportError, setReportImportError] = useState<string | null>(null);
    const [agentRuntime, setAgentRuntime] = useState('claude_sdk');
    const [hermesReachable, setHermesReachable] = useState(false);
    const [hermesStatusMessage, setHermesStatusMessage] = useState('');
    const [builderOpen, setBuilderOpen] = useState(false);
    const [savingDefinition, setSavingDefinition] = useState(false);
    const [definitionForm, setDefinitionForm] = useState({
        id: '',
        name: '',
        description: '',
        system_prompt: 'You are a focused QA automation agent. Use the selected tools to inspect the target, report findings clearly, and avoid actions outside the requested task.',
        runtime: 'claude_sdk',
        timeout_seconds: 1800,
        tool_ids: ['read_file', 'list_files', 'browser_navigate', 'browser_snapshot', 'browser_network', 'browser_console'],
        test_data_refs: '',
    });
    const pollInterval = useRef<NodeJS.Timeout | null>(null);
    const agentEventSourceRef = useRef<EventSource | null>(null);
    const agentEventReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const agentEventsRef = useRef<AgentRunEvent[]>([]);
    const activeBrowserAuthSessions = useMemo(
        () => sessions.filter(isBrowserAuthSessionSelectable),
        [sessions]
    );
    const projectDefaultBrowserAuthSession = useMemo(
        () => activeBrowserAuthSessions.find(item => item.is_default),
        [activeBrowserAuthSessions]
    );

    const updateWorkspaceQuery = useCallback((patch: Parameters<typeof applyAgentWorkspaceQueryPatch>[1]) => {
        if (typeof window === 'undefined') return;
        const nextParams = applyAgentWorkspaceQueryPatch(new URLSearchParams(window.location.search), patch);
        const query = nextParams.toString();
        const nextUrl = `${window.location.pathname}${query ? `?${query}` : ''}`;
        window.history.replaceState(null, '', nextUrl);
    }, []);

    const selectRun = useCallback((runId: string | null) => {
        setSelectedRunId(runId);
        updateWorkspaceQuery({ runId });
    }, [updateWorkspaceQuery]);

    const selectWorkspaceView = useCallback((view: AgentWorkspaceView) => {
        setWorkspaceView(view);
        updateWorkspaceQuery({ view });
    }, [updateWorkspaceQuery]);

    const selectAgentMode = useCallback((mode: AgentWorkspaceMode) => {
        setSelectedAgent(mode);
        updateWorkspaceQuery({ agent: mode });
    }, [updateWorkspaceQuery]);

    const selectDefinition = useCallback((definitionId: string) => {
        setSelectedDefinitionId(definitionId);
        updateWorkspaceQuery({ definitionId });
    }, [updateWorkspaceQuery]);

    const selectCustomResultTab = useCallback((tab: CustomResultTab) => {
        setCustomResultTab(tab);
        updateWorkspaceQuery({ resultTab: tab });
    }, [updateWorkspaceQuery]);

    const selectTraceTab = useCallback((tab: TraceTab) => {
        setTraceTab(tab);
        updateWorkspaceQuery({ traceTab: tab });
    }, [updateWorkspaceQuery]);

    const updateReportStatusFilter = useCallback((value: ReportReviewFilter) => {
        setReportStatusFilter(value);
        updateWorkspaceQuery({ reportStatus: value });
    }, [updateWorkspaceQuery]);

    const updateReportSeverityFilter = useCallback((value: string) => {
        setReportSeverityFilter(value);
        updateWorkspaceQuery({ reportSeverity: value });
    }, [updateWorkspaceQuery]);

    const updateReportSearchQuery = useCallback((value: string) => {
        setReportSearchQuery(value);
        updateWorkspaceQuery({ reportQ: value });
    }, [updateWorkspaceQuery]);

    const updateReportSearchType = useCallback((value: ReportSearchTypeFilter) => {
        setReportSearchType(value);
        updateWorkspaceQuery({ reportType: value });
    }, [updateWorkspaceQuery]);

    const updateReportSearchSeverity = useCallback((value: string) => {
        setReportSearchSeverity(value);
        updateWorkspaceQuery({ reportSeverity: value });
    }, [updateWorkspaceQuery]);

    const updateHistorySearch = useCallback((value: string) => {
        setHistorySearch(value);
        updateWorkspaceQuery({ q: value });
    }, [updateWorkspaceQuery]);

    const updateHistoryStatusFilter = useCallback((value: AgentHistoryStatusFilter) => {
        setHistoryStatusFilter(value);
        updateWorkspaceQuery({ status: value });
    }, [updateWorkspaceQuery]);

    const updateHistoryTypeFilter = useCallback((value: AgentHistoryTypeFilter) => {
        setHistoryTypeFilter(value);
        updateWorkspaceQuery({ type: value });
    }, [updateWorkspaceQuery]);

    const fetchRuntimeSettings = async () => {
        try {
            const res = await fetch(`${API_BASE}/settings`);
            if (!res.ok) return;
            const data = await res.json();
            const runtime = data.agent_runtime || 'claude_sdk';
            setAgentRuntime(runtime);
            setHermesReachable(Boolean(data.hermes_reachable));
            setHermesStatusMessage(data.hermes_status_message || '');
            setDefinitionForm(prev => prev.id ? prev : { ...prev, runtime });
        } catch (e) {
            console.error('Failed to fetch runtime settings', e);
        }
    };

    // Fetch history (filtered by project)
    const fetchHistory = async () => {
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/api/agents/runs${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setHistory(data);
            }
        } catch (e) { console.error("Failed to fetch history", e); }
    };

    const fetchSessions = async () => {
        if (!currentProject?.id) {
            setSessions([]);
            setSessionId('');
            return;
        }
        try {
            setSessions(await fetchProjectBrowserAuthSessions(currentProject.id));
        } catch (e) { console.error("Failed to fetch browser login sessions", e); }
    };

    const fetchToolCatalog = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/tools/catalog`);
            if (res.ok) {
                const data = await res.json();
                setToolCatalog(data.tools || []);
            }
        } catch (e) { console.error("Failed to fetch agent tool catalog", e); }
    };

    const fetchAgentDefinitions = async () => {
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/api/agents/definitions${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setAgentDefinitions(data || []);
                if (!selectedDefinitionId && data?.length) {
                    setSelectedDefinitionId(data[0].id);
                }
            }
        } catch (e) { console.error("Failed to fetch agent definitions", e); }
    };

    const fetchQueueStatus = async () => {
        setQueueLoading(true);
        setQueueError(null);
        try {
            const res = await fetch(`${API_BASE}/api/agents/queue-status`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            setQueueStatus(await res.json());
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to fetch queue status.';
            setQueueError(message);
        } finally {
            setQueueLoading(false);
        }
    };

    const fetchReportSearch = async () => {
        setReportSearchLoading(true);
        try {
            const params = new URLSearchParams({ limit: '50' });
            if (currentProject?.id) params.set('project_id', currentProject.id);
            if (reportSearchQuery.trim()) params.set('query', reportSearchQuery.trim());
            if (reportSearchType !== 'all') params.set('item_type', reportSearchType);
            if (reportSearchSeverity !== 'all') params.set('severity', reportSearchSeverity);
            const res = await fetch(`${API_BASE}/api/agents/reports/search?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            setReportSearchResults(Array.isArray(data.items) ? data.items : []);
        } catch (e) {
            console.error('Failed to search agent reports', e);
            setReportSearchResults([]);
        } finally {
            setReportSearchLoading(false);
        }
    };

    useEffect(() => {
        fetchHistory();
        fetchSessions();
        fetchToolCatalog();
        fetchAgentDefinitions();
        fetchRuntimeSettings();
        fetchQueueStatus();
        if (typeof window !== 'undefined') {
            const queryState = parseAgentWorkspaceQuery(new URLSearchParams(window.location.search));
            setWorkspaceView(queryState.view);
            if (queryState.runId) setSelectedRunId(queryState.runId);
            setSelectedAgent(queryState.agent);
            setSelectedDefinitionId(queryState.definitionId);
            setReturnToAfterSave(queryState.returnTo);
            if (queryState.create) {
                setBuilderOpen(true);
            }
            setCustomResultTab(queryState.resultTab);
            setTraceTab(queryState.traceTab);
            setReportStatusFilter(queryState.reportStatus);
            setReportSeverityFilter(queryState.reportSeverity);
            setReportSearchQuery(queryState.reportQ);
            setReportSearchSeverity(queryState.reportSeverity);
            setReportSearchType(queryState.reportType);
            setHistoryStatusFilter(queryState.status);
            setHistoryTypeFilter(queryState.type);
            setHistorySearch(queryState.q);
        }
        return () => {
            if (pollInterval.current) clearInterval(pollInterval.current);
            agentEventSourceRef.current?.close();
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
        }
    }, [currentProject?.id]);  // Re-fetch when project changes

    useEffect(() => {
        if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('resultTab')) return;
        setCustomResultTab('overview');
    }, [activeRun?.id]);

    useEffect(() => {
        if (workspaceView !== 'reports') return;
        const timer = window.setTimeout(() => {
            void fetchReportSearch();
        }, 200);
        return () => window.clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [workspaceView, currentProject?.id, reportSearchQuery, reportSearchType, reportSearchSeverity]);

    useEffect(() => {
        if (workspaceView !== 'queue') return;
        void fetchQueueStatus();
        const interval = window.setInterval(() => void fetchQueueStatus(), 5000);
        return () => window.clearInterval(interval);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [workspaceView]);

    useEffect(() => {
        agentEventsRef.current = agentEvents;
    }, [agentEvents]);

    const openAssistantWithPrompt = (prompt: string) => {
        window.dispatchEvent(new CustomEvent('open-ai-assistant'));
        setTimeout(() => {
            window.dispatchEvent(new CustomEvent('assistant-prefill', { detail: { prompt } }));
        }, 50);
    };

    // Fetch single run
    const fetchRun = async (id: string) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}`);
            if (res.ok) {
                const data = await res.json();
                setActiveRun(data);
                fetchAgentEvents(id);
                fetchAgentTrace(id);

                // If actively running, keep polling
                if (LIVE_AGENT_STATUSES.has(data.status)) {
                    // Continue polling
                } else {
                    // Run completed or failed - do one final fetch to get the result
                    if (pollInterval.current && selectedRunId === id) {
                        clearInterval(pollInterval.current);
                        pollInterval.current = null;

                        // Fetch one more time after a short delay to ensure result is saved
                        setTimeout(async () => {
                            const finalRes = await fetch(`${API_BASE}/api/agents/runs/${id}`);
                            if (finalRes.ok) {
                                const finalData = await finalRes.json();
                                setActiveRun(finalData);
                                fetchAgentEvents(id);
                                fetchAgentTrace(id);
                            }
                            fetchHistory(); // Refresh list to update status
                        }, 500);
                    }
                }
            }
        } catch (e) {
            console.error("Failed to fetch run", e);
        }
    };

    const mergeAgentEvents = (incoming: AgentRunEvent[]) => {
        setAgentEvents(prev => {
            const bySequence = new Map<number, AgentRunEvent>();
            [...prev, ...incoming].forEach(item => bySequence.set(item.sequence, item));
            return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
        });
    };

    const fetchAgentEvents = async (id: string, afterSequence = 0) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}/events?limit=200&after_sequence=${afterSequence}`);
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data)) {
                    if (afterSequence > 0) mergeAgentEvents(data);
                    else setAgentEvents(data);
                }
            }
        } catch (e) {
            console.error("Failed to fetch agent events", e);
        }
    };

    const fetchAgentTrace = async (id: string) => {
        setTraceLoading(true);
        try {
            const projectQuery = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}/trace${projectQuery}`);
            if (res.ok) {
                setAgentTrace(await res.json());
            }
        } catch (e) {
            console.error("Failed to fetch agent trace", e);
        } finally {
            setTraceLoading(false);
        }
    };

    const fetchFlowSpecAgentRun = async (id: string) => {
        try {
            const [runRes, eventsRes] = await Promise.all([
                fetch(`${API_BASE}/api/agents/runs/${id}`),
                fetch(`${API_BASE}/api/agents/runs/${id}/events?limit=100`),
            ]);
            if (runRes.ok) {
                const data = await runRes.json();
                setFlowSpecAgentRun(data);
            }
            if (eventsRes.ok) {
                const events = await eventsRes.json();
                setFlowSpecAgentEvents(Array.isArray(events) ? events : []);
            }
        } catch (e) {
            console.error("Failed to fetch spec generation run", e);
        }
    };

    useEffect(() => {
        if (!flowSpecAgentRunId || !flowModalOpen) return;
        fetchFlowSpecAgentRun(flowSpecAgentRunId);
        const interval = window.setInterval(() => fetchFlowSpecAgentRun(flowSpecAgentRunId), 3000);
        return () => window.clearInterval(interval);
    }, [flowSpecAgentRunId, flowModalOpen]);

    // Fetch specs for exploration run
    const fetchSpecs = async (runId: string) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/exploratory/${runId}/specs`);
            if (res.ok) {
                const data = await res.json();
                if (data.specs) {
                    setSpecResult(data);
                }
            }
        } catch (e) {
            console.error("Failed to fetch specs", e);
        }
    };

    // Fetch flow details from the API
    const fetchFlowDetails = async (flowId: string) => {
        if (!activeRun?.id) return;

        setLoadingFlowDetails(true);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        try {
            const res = await fetch(`${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}`);
            if (res.ok) {
                const data = await res.json();
                setSelectedFlow(data.flow);
                setFlowModalOpen(true);
            } else {
                const error = await res.json();
                toast.error(`Failed to load flow details: ${error.detail || 'Unknown error'}`);
            }
        } catch (e) {
            console.error("Failed to fetch flow details", e);
            toast.error("Failed to load flow details. Please try again.");
        } finally {
            setLoadingFlowDetails(false);
        }
    };

    // Flow spec generation with async job polling
    const flowSpecPoller = useJobPoller({
        apiBase: API_BASE,
        urlPattern: '/api/agents/exploratory/flow-spec-jobs/{jobId}',
        interval: 3000,
        onComplete: (result, status) => {
            setFlowSpecError(null);
            if (result) {
                setGeneratedSpec({
                    spec_content: result.spec_content as string,
                    spec_file: result.spec_file as string,
                    filename: result.spec_file ? (result.spec_file as string).split('/').pop() : 'spec.md',
                    flow_title: result.flow_title as string,
                    summary: 'Generated with Intelligent Pipeline',
                    cached: false,
                    validated: result.validated as boolean || false,
                    test_code: result.test_code as string,
                    test_file: result.test_file as string,
                    pipeline: result.pipeline as string,
                    requires_auth: result.requires_auth as boolean,
                });
                setSpecModalOpen(true);
            }
            const agentRunId = status.agent_run_id || flowSpecAgentRunId;
            if (agentRunId) {
                setFlowSpecAgentRunId(agentRunId);
                fetchFlowSpecAgentRun(agentRunId);
            }
            setGeneratingSpec(false);
        },
        onFailed: (message, status) => {
            setGeneratingSpec(false);
            setFlowSpecError(message || 'Unknown error');
            const agentRunId = status.agent_run_id || flowSpecAgentRunId;
            if (agentRunId) {
                setFlowSpecAgentRunId(agentRunId);
                fetchFlowSpecAgentRun(agentRunId);
            }
        },
    });

    useEffect(() => {
        const agentRunId = flowSpecPoller.status?.agent_run_id;
        if (agentRunId && agentRunId !== flowSpecAgentRunId) {
            setFlowSpecAgentRunId(agentRunId);
        }
        const agentRun = flowSpecPoller.status?.agent_run as AgentRun | undefined;
        if (agentRun?.id) {
            setFlowSpecAgentRun(agentRun);
        }
    }, [flowSpecPoller.status, flowSpecAgentRunId]);

    // Generate spec for a single flow using Intelligent Pipeline
    const generateFlowSpec = async (flowId: string, forceRegenerate: boolean = false) => {
        if (!activeRun?.id) return;

        setGeneratingSpec(true);
        setSplitResult(null);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        try {
            const url = forceRegenerate
                ? `${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}/generate?force_regenerate=true`
                : `${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}/generate`;

            const res = await fetch(url, { method: 'POST' });
            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                throw new Error(error.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();

            // Cached result → show immediately
            if (data.cached || data.status === 'success') {
                setGeneratedSpec({
                    spec_content: data.spec_content,
                    spec_file: data.spec_file,
                    filename: data.spec_file ? data.spec_file.split('/').pop() : 'spec.md',
                    flow_title: data.flow_title,
                    summary: data.status === 'success' ? 'Generated with Intelligent Pipeline' : data.status,
                    cached: data.cached || false,
                    validated: data.validated || false,
                    test_code: data.test_code,
                    test_file: data.test_file,
                    pipeline: data.pipeline,
                    requires_auth: data.requires_auth
                });
                setSpecModalOpen(true);
                setGeneratingSpec(false);
                return;
            }

            // Async job → start polling
            if (data.job_id) {
                if (data.agent_run_id) {
                    setFlowSpecAgentRunId(data.agent_run_id);
                    fetchFlowSpecAgentRun(data.agent_run_id);
                }
                flowSpecPoller.startPolling(data.job_id);
                return; // generatingSpec stays true until poll resolves
            }

            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            setFlowSpecError(message);
            setGeneratingSpec(false);
        }
    };

    const openSpecFromReportItem = (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
        if (!activeRun?.id) return;
        const defaultSelection = defaultReportSpecBrowserAuthSelection(sessions, sessionId);
        setReportSpecAuthMode(defaultSelection.mode);
        setReportSpecAuthSessionId(defaultSelection.sessionId);
        setSelectedFlow({
            id: item.id,
            title: item.title || item.id,
            pages: item.page ? [item.page] : [],
            happy_path: 'steps' in item && item.steps?.length ? item.steps.join('\n') : ('description' in item ? item.description : undefined),
            edge_cases: kind === 'finding' && 'evidence' in item && item.evidence ? [item.evidence] : [],
            test_ideas: kind === 'test_idea' && 'expected' in item && item.expected ? [item.expected] : [],
            entry_point: item.page || activeRun.config?.url,
            exit_point: item.page || activeRun.config?.url,
            source_type: 'custom_report',
            item_type: kind,
        });
        setFlowModalOpen(true);
        setGeneratingSpec(false);
        setSplitResult(null);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
    };

    const createSpecFromReportItem = async (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
        if (!activeRun?.id) return;
        if (reportSpecAuthMode === 'session') {
            const selected = activeBrowserAuthSessions.find(session => session.id === reportSpecAuthSessionId);
            if (!selected) {
                setFlowSpecError('Select an active browser login session or choose No auth.');
                return;
            }
        }
        if (reportSpecAuthMode === 'project_default' && !projectDefaultBrowserAuthSession) {
            setFlowSpecError('Set an active project default browser login session or choose No auth.');
            return;
        }
        setGeneratingSpec(true);
        setSplitResult(null);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        try {
            const params = new URLSearchParams({ item_type: kind });
            if (currentProject?.id) params.set('project_id', currentProject.id);
            const res = await fetch(`${API_BASE}/api/agents/runs/${activeRun.id}/report-items/${encodeURIComponent(item.id)}/generate-spec?${params}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reportSpecBrowserAuthBody(reportSpecAuthMode, reportSpecAuthSessionId)),
            });
            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                throw new Error(error.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (data.agent_run_id) {
                setFlowSpecAgentRunId(data.agent_run_id);
                fetchFlowSpecAgentRun(data.agent_run_id);
            }
            if (data.job_id) {
                flowSpecPoller.startPolling(data.job_id);
                return;
            }
            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            setFlowSpecError(message);
            setGeneratingSpec(false);
        }
    };

    const importReportRequirements = async (itemIds?: string[]) => {
        if (!activeRun?.id) return;
        const selectedIds = (itemIds || []).filter(Boolean);
        const markers = selectedIds.length > 0 ? selectedIds : ['__all__'];
        setImportingRequirementIds(prev => Array.from(new Set([...prev, ...markers])));
        setReportImportError(null);
        try {
            const params = new URLSearchParams();
            if (currentProject?.id) params.set('project_id', currentProject.id);
            const query = params.toString() ? `?${params}` : '';
            const res = await fetch(`${API_BASE}/api/agents/runs/${activeRun.id}/report-requirements/import${query}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(selectedIds.length > 0 ? { item_ids: selectedIds } : { import_all: true }),
            });
            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message;
                throw new Error(detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (data.run) {
                setActiveRun(data.run);
                setHistory(prev => prev.map(run => run.id === data.run.id ? data.run : run));
            }
        } catch (e: unknown) {
            setReportImportError(e instanceof Error ? e.message : 'Failed to import requirements.');
        } finally {
            setImportingRequirementIds(prev => prev.filter(id => !markers.includes(id)));
        }
    };

    // Download generated spec as file
    const downloadSpec = (content?: string, filename?: string) => {
        // If no arguments provided, use state (for new flow spec generation)
        const specContent = content || generatedSpec?.spec_content;
        const specFilename = filename || generatedSpec?.filename || 'spec.md';

        if (!specContent) return;

        const blob = new Blob([specContent], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = specFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    // Split spec into individual tests
    const splitSpec = async () => {
        if (!generatedSpec?.spec_file) return;

        setSplittingSpec(true);
        setSplitResult(null);
        try {
            // Extract spec name relative to specs directory
            const specFile = generatedSpec.spec_file;
            const specsIndex = specFile.indexOf('/specs/');
            const specName = specsIndex !== -1 ? specFile.substring(specsIndex + 7) : specFile.split('/').slice(-2).join('/');

            const res = await fetch(`${API_BASE}/specs/split`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_name: specName })
            });

            if (res.ok) {
                const data = await res.json();
                setSplitResult(data);
                setWorkspaceStatus(`Split spec into ${data.count} files.`);
                toast.success('Spec split into individual tests');
            } else {
                const error = await res.json();
                toast.error(`Failed to split spec: ${error.detail || 'Unknown error'}`);
            }
        } catch (e) {
            console.error("Failed to split spec", e);
            toast.error("Failed to split spec. Please try again.");
        } finally {
            setSplittingSpec(false);
        }
    };

    // When selection changes
    useEffect(() => {
        if (!selectedRunId) {
            setActiveRun(null);
            setSpecResult(null);
            setAgentEvents([]);
            setAgentTrace(null);
            setTraceSearch('');
            setTraceSpanType('');
            return;
        }

        // Clear existing poll
        if (pollInterval.current) clearInterval(pollInterval.current);

        // Initial fetch
        fetchRun(selectedRunId);
        fetchSpecs(selectedRunId);

        // Start polling
        pollInterval.current = setInterval(() => {
            fetchRun(selectedRunId);
        }, 2000); // 2s poll

        return () => {
            if (pollInterval.current) clearInterval(pollInterval.current);
        };
    }, [selectedRunId]);

    useEffect(() => {
        if (!selectedRunId || !activeRun || !LIVE_AGENT_STATUSES.has(activeRun.status)) return;
        let cancelled = false;
        let attempts = 0;

        const backfillEvents = async () => {
            const lastSequence = agentEventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            await fetchAgentEvents(selectedRunId, lastSequence);
            await fetchAgentTrace(selectedRunId);
        };

        const scheduleReconnect = () => {
            if (cancelled) return;
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
            attempts += 1;
            const delay = Math.min(15000, 750 * Math.pow(2, Math.min(attempts, 5)));
            agentEventReconnectTimerRef.current = setTimeout(async () => {
                agentEventReconnectTimerRef.current = null;
                await backfillEvents();
                connect();
            }, delay);
        };

        const connect = () => {
            if (cancelled || agentEventSourceRef.current) return;
            const lastSequence = agentEventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            const projectQuery = currentProject?.id ? `&project_id=${encodeURIComponent(currentProject.id)}` : '';
            const source = new EventSource(`${API_BASE}/api/agents/runs/${selectedRunId}/events/stream?after_sequence=${lastSequence}${projectQuery}`);
            agentEventSourceRef.current = source;
            source.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    attempts = 0;
                    mergeAgentEvents([data]);
                    void fetchAgentTrace(selectedRunId);
                } catch {
                    source.close();
                    agentEventSourceRef.current = null;
                    scheduleReconnect();
                }
            };
            source.onerror = () => {
                source.close();
                agentEventSourceRef.current = null;
                scheduleReconnect();
            };
        };

        void backfillEvents();
        connect();
        return () => {
            cancelled = true;
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
            agentEventReconnectTimerRef.current = null;
            agentEventSourceRef.current?.close();
            agentEventSourceRef.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedRunId, activeRun?.status, currentProject?.id]);


    const selectedDefinition = agentDefinitions.find(agent => agent.id === selectedDefinitionId);
    const toolsByCategory = toolCatalog.reduce<Record<string, AgentTool[]>>((acc, tool) => {
        acc[tool.category] = acc[tool.category] || [];
        acc[tool.category].push(tool);
        return acc;
    }, {});

    const resetDefinitionForm = () => {
        setDefinitionForm({
            id: '',
            name: '',
            description: '',
            system_prompt: 'You are a focused QA automation agent. Use the selected tools to inspect the target, report findings clearly, and avoid actions outside the requested task.',
            runtime: agentRuntime,
            timeout_seconds: 1800,
            tool_ids: ['read_file', 'list_files', 'browser_navigate', 'browser_snapshot', 'browser_network', 'browser_console', 'browser_screenshot'],
            test_data_refs: '',
        });
        setBuilderOpen(true);
    };

    const editDefinition = (definition: AgentDefinition) => {
        setDefinitionForm({
            id: definition.id,
            name: definition.name,
            description: definition.description || '',
            system_prompt: definition.system_prompt,
            runtime: definition.runtime || 'claude_sdk',
            timeout_seconds: definition.timeout_seconds || 1800,
            tool_ids: definition.tool_ids || [],
            test_data_refs: (definition.test_data_refs || []).join(', '),
        });
        setBuilderOpen(true);
    };

    const editDefinitionFromMenu = (definition: AgentDefinition, event?: Event) => {
        event?.preventDefault();
        event?.stopPropagation();
        setOpenDefinitionMenuId(null);
        editDefinition(definition);
    };

    const archiveDefinitionFromMenu = (definition: AgentDefinition, event?: Event) => {
        event?.preventDefault();
        event?.stopPropagation();
        setOpenDefinitionMenuId(null);
        setArchiveCandidate(definition);
    };

    const toggleDefinitionTool = (toolId: string) => {
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: prev.tool_ids.includes(toolId)
                ? prev.tool_ids.filter(id => id !== toolId)
                : [...prev.tool_ids, toolId],
        }));
    };

    const toggleCategoryTools = (tools: AgentTool[]) => {
        const ids = tools.map(tool => tool.id);
        const allSelected = ids.every(id => definitionForm.tool_ids.includes(id));
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: allSelected
                ? prev.tool_ids.filter(id => !ids.includes(id))
                : Array.from(new Set([...prev.tool_ids, ...ids])),
        }));
    };

    const saveDefinition = async () => {
        setDefinitionFormError(null);
        if (!definitionForm.name.trim()) {
            setDefinitionFormError('Agent name is required.');
            return;
        }
        if (!definitionForm.system_prompt.trim()) {
            setDefinitionFormError('System prompt is required.');
            return;
        }
        if (definitionForm.tool_ids.length === 0) {
            setDefinitionFormError('Select at least one tool.');
            return;
        }

        setSavingDefinition(true);
        try {
            const isEdit = Boolean(definitionForm.id);
            const url = isEdit
                ? `${API_BASE}/api/agents/definitions/${definitionForm.id}${currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : ''}`
                : `${API_BASE}/api/agents/definitions`;
            const res = await fetch(url, {
                method: isEdit ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: definitionForm.name,
                    description: definitionForm.description,
                    system_prompt: definitionForm.system_prompt,
                    runtime: definitionForm.runtime,
                    timeout_seconds: definitionForm.timeout_seconds,
                    tool_ids: definitionForm.tool_ids,
                    test_data_refs: definitionForm.test_data_refs.split(',').map(s => s.trim()).filter(Boolean),
                    project_id: currentProject?.id,
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to save agent');
            }
            const saved = await res.json();
            await fetchAgentDefinitions();
            selectDefinition(saved.id);
            selectAgentMode('custom');
            setWorkspaceView(returnToAfterSave ? 'library' : 'run');
            updateWorkspaceQuery({ create: false, view: returnToAfterSave ? 'library' : 'run' });
            setBuilderOpen(false);
            setWorkspaceStatus(`Saved ${saved.name || 'custom agent'}.`);
            toast.success('Custom agent saved');
        } catch (e: any) {
            const message = e.message || 'Failed to save agent';
            setDefinitionFormError(message);
            toast.error(message);
        } finally {
            setSavingDefinition(false);
        }
    };

    const archiveDefinition = async (definition: AgentDefinition) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/definitions/${definition.id}${currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : ''}`, {
                method: 'DELETE',
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to archive agent');
            }
            await fetchAgentDefinitions();
            if (selectedDefinitionId === definition.id) selectDefinition('');
            setWorkspaceStatus(`Archived ${definition.name}.`);
            toast.success('Custom agent archived');
        } catch (e: any) {
            const message = e.message || 'Failed to archive agent';
            toast.error(message);
        }
    };

    const handleRun = async () => {
        const validationError = validateAgentRunInput({
            selectedAgent,
            selectedDefinitionId,
            url,
            authType,
            sessionId,
            testData,
        });
        setRunFormError(validationError);
        if (validationError) {
            return;
        }

        setIsStarting(true);
        setWorkspaceStatus('Starting agent run...');
        try {
            const selectedBrowserAuthSessionId = selectedAgent !== 'writer' && authType === 'session' ? sessionId.trim() : '';
            if (selectedAgent !== 'writer' && authType === 'session' && !selectedBrowserAuthSessionId) {
                setRunFormError('Select a browser login session.');
                setIsStarting(false);
                return;
            }
            const selectedBrowserAuthSession = selectedBrowserAuthSessionId
                ? sessions.find(session => session.id === selectedBrowserAuthSessionId)
                : undefined;
            if (selectedBrowserAuthSessionId && (!selectedBrowserAuthSession || !isBrowserAuthSessionSelectable(selectedBrowserAuthSession))) {
                setRunFormError('Select an active browser login session.');
                setIsStarting(false);
                return;
            }

            // Build auth config
            let authConfig: any = null;
            if (selectedAgent !== 'custom' && authType !== 'none' && authType !== 'session') {
                authConfig = { type: authType };
                if (authType === 'credentials') {
                    authConfig.credentials = {
                        username: authCredentials.username,
                        password: authCredentials.password
                    };
                    authConfig.login_url = authCredentials.loginUrl;
                }
            }

            // Build test data from JSON
            let testDataObj = {};
            if (testData.trim()) {
                try {
                    testDataObj = JSON.parse(testData);
                } catch (e) {
                    setRunFormError('Test data must be valid JSON.');
                    setIsStarting(false);
                    return;
                }
            }

            // Build focus areas
            const focusAreasList = focusAreas ? focusAreas.split(',').map(s => s.trim()).filter(s => s) : [];
            const testDataRefsList = testDataRefs ? testDataRefs.split(',').map(s => s.trim()).filter(Boolean) : [];

            // Build excluded patterns
            const excludedPatternsList = excludedPatterns ? excludedPatterns.split(',').map(s => s.trim()).filter(s => s) : [];

            // Use new enhanced endpoint for exploratory agent
            const endpoint = selectedAgent === 'custom'
                ? `${API_BASE}/api/agents/definitions/${selectedDefinitionId}/runs`
                : selectedAgent === 'exploratory'
                ? `${API_BASE}/api/agents/exploratory`
                : `${API_BASE}/api/agents/runs`;

            const selectedRuntime = selectedAgent === 'custom'
                ? (selectedDefinition?.runtime || agentRuntime)
                : agentRuntime;

            const body = selectedAgent === 'custom'
                ? {
                    prompt: instructions || `Inspect ${url || 'the current application context'} and report useful QA findings.`,
                    url: url || undefined,
                    runtime: selectedRuntime,
                    test_data_refs: testDataRefsList,
                    config: {
                        auth: authConfig,
                        browser_auth_session_id: selectedBrowserAuthSessionId || undefined,
                        test_data: Object.keys(testDataObj).length > 0 ? testDataObj : undefined,
                        test_data_refs: testDataRefsList.length > 0 ? testDataRefsList : undefined,
                        focus_areas: focusAreasList,
                        excluded_patterns: excludedPatternsList,
                    },
                    project_id: currentProject?.id,
                }
                : selectedAgent === 'exploratory'
                ? {
                    url,
                    time_limit_minutes: timeLimitMinutes,
                    instructions,
                    auth: authConfig,
                    browser_auth_session_id: selectedBrowserAuthSessionId || undefined,
                    test_data: Object.keys(testDataObj).length > 0 ? testDataObj : undefined,
                    focus_areas: focusAreasList.length > 0 ? focusAreasList : undefined,
                    excluded_patterns: excludedPatternsList.length > 0 ? excludedPatternsList : undefined,
                    runtime: selectedRuntime,
                    project_id: currentProject?.id  // Associate generated specs with current project
                }
                : {
                    agent_type: 'writer',
                    runtime: selectedRuntime,
                    config: {
                        url,
                        instructions,
                        max_steps: 10,
                        runtime: selectedRuntime,
                    },
                    project_id: currentProject?.id  // Project isolation for writer agent
                };

            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Agent run failed');
            }

            const data = await res.json();
            // Refresh history but select the new run
            await fetchHistory();
            selectRun(data.run_id);
            setWorkspaceStatus('Agent run started.');
            toast.success('Agent run started');

        } catch (e: any) {
            const message = e.message || 'Failed to start agent run.';
            setRunFormError(message);
            toast.error(message);
        } finally {
            setIsStarting(false);
        }
    };

    const controlAgentRun = async (action: 'pause' | 'resume' | 'cancel') => {
        if (!activeRun) return;
        setRunControlPending(action);
        try {
            const projectQuery = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
            const res = await fetch(`${API_BASE}/api/agents/runs/${activeRun.id}/${action}${projectQuery}`, {
                method: 'POST',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || `Failed to ${action} agent run`);
            }
            setActiveRun(data);
            await fetchHistory();
            setWorkspaceStatus(`Run ${action} request sent.`);
            toast.success(`Run ${action} request sent`);
        } catch (e: any) {
            toast.error(e.message || `Failed to ${action} agent run`);
        } finally {
            setRunControlPending(null);
        }
    };

    const exportAgentTrace = () => {
        if (!activeRun) return;
        const projectQuery = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
        window.open(`${API_BASE}/api/agents/runs/${activeRun.id}/trace/export${projectQuery}`, '_blank', 'noopener,noreferrer');
    };

    const handleSynthesize = async () => {
        if (!selectedRunId || !activeRun || activeRun.agent_type !== 'exploratory') {
            toast.error("Please select a completed exploratory run");
            return;
        }

        if (activeRun.status !== 'completed') {
            toast.error("Please wait for the exploration to complete");
            return;
        }

        setIsSynthesizing(true);
        try {
            const res = await fetch(`${API_BASE}/api/agents/exploratory/${selectedRunId}/synthesize`, {
                method: 'POST'
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Spec synthesis failed');
            }

            const data = await res.json();

            // Poll for specs
            setTimeout(() => {
                fetchSpecs(selectedRunId!);
                setIsSynthesizing(false);
            }, 2000);

        } catch (e: any) {
            toast.error(e.message || 'Spec synthesis failed');
            setIsSynthesizing(false);
        }
    };

    const dateFormatter = useMemo(() => new Intl.DateTimeFormat(undefined, {
        hour: 'numeric',
        minute: 'numeric',
        day: 'numeric',
        month: 'short',
    }), []);

    const formatDate = (iso: string) => {
        return dateFormatter.format(new Date(iso));
    };

    const flowSpecLatestImage = sortArtifactsByModifiedAt((flowSpecAgentRun?.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
    const flowSpecRunLive = Boolean(flowSpecAgentRun && LIVE_AGENT_STATUSES.has(flowSpecAgentRun.status));
    const flowSpecShowBrowser = Boolean(flowSpecAgentRunId && (generatingSpec || flowSpecRunLive || flowSpecLatestImage));
    const sourceRunBrowserAuthSessionId = runBrowserAuthSessionId(activeRun?.config);
    const inheritedBrowserAuthUnavailable = Boolean(
        selectedFlow?.source_type === 'custom_report' &&
        sourceRunBrowserAuthSessionId &&
        !activeBrowserAuthSessions.some(item => item.id === sourceRunBrowserAuthSessionId)
    );
    const flowSpecBrowserAuthFailure = Boolean(
        flowSpecAgentRun?.progress?.browser_auth_failure ||
        flowSpecAgentRun?.result?.browser_auth_failure
    );
    const historyCounts = useMemo(() => getAgentHistoryCounts(history), [history]);
    const filteredHistory = useMemo(
        () => filterAgentHistoryRuns(history, {
            q: historySearch,
            status: historyStatusFilter,
            type: historyTypeFilter,
        }),
        [history, historySearch, historyStatusFilter, historyTypeFilter]
    );
    const queueWarnings = useMemo(() => {
        const stale = queueStatus?.stale_running ?? 0;
        const orphaned = queueStatus?.orphaned_tasks ?? 0;
        const noWorkers = (queueStatus?.active || queueStatus?.queued || 0) > 0 && (queueStatus?.workers_alive ?? queueStatus?.worker_processes_alive ?? 0) === 0;
        return {
            stale,
            orphaned,
            noWorkers,
            degraded: stale > 0 || orphaned > 0 || noWorkers,
        };
    }, [queueStatus]);
    const selectedDefinitionToolLabels = useMemo(() => {
        if (!selectedDefinition) return [];
        return selectedDefinition.tool_ids.map(toolId => toolCatalog.find(tool => tool.id === toolId)?.label || toolId);
    }, [selectedDefinition, toolCatalog]);
    const runPlanRows = useMemo(() => {
        const authMode = selectedAgent === 'writer'
            ? 'N/A'
            : authType === 'session'
            ? (sessions.find(session => session.id === sessionId)?.name || sessionId || 'Session required')
            : authType === 'credentials'
            ? `Credentials via ${authCredentials.loginUrl || '/login'}`
            : 'No auth';
        const runtime = selectedAgent === 'custom' ? (selectedDefinition?.runtime || agentRuntime) : agentRuntime;
        const timeout = selectedAgent === 'custom'
            ? `${Math.ceil((selectedDefinition?.timeout_seconds || 1800) / 60)} minutes`
            : selectedAgent === 'exploratory'
            ? `${timeLimitMinutes} minutes`
            : 'Default';
        return [
            ['Agent', selectedAgent === 'custom' ? selectedDefinition?.name || 'Custom agent required' : selectedAgent === 'writer' ? 'Writer' : 'Enhanced Explorer'],
            ['Runtime', runtime === 'hermes' ? 'Hermes' : 'Claude SDK'],
            ['Target', url.trim() || (selectedAgent === 'custom' ? 'Optional' : 'Required')],
            ['Auth', authMode],
            ['Timeout', timeout],
            ['Tools', selectedAgent === 'custom' ? selectedDefinitionToolLabels.slice(0, 4).join(', ') || 'Select a saved agent' : 'Built-in browser exploration'],
            ['Test data refs', testDataRefs.trim() || selectedDefinition?.test_data_refs?.join(', ') || 'None'],
            ['Focus', focusAreas.trim() || 'General coverage'],
            ['Exclusions', excludedPatterns.trim() || 'None'],
            ['Queue', queueStatus ? `${queueStatus.active ?? 0} active, ${queueStatus.queued ?? 0} queued · ${queueStateLabel(queueStatus)}` : 'Not loaded'],
        ];
    }, [agentRuntime, authCredentials.loginUrl, authType, excludedPatterns, focusAreas, queueStatus, selectedAgent, selectedDefinition, selectedDefinitionToolLabels, sessionId, sessions, testDataRefs, timeLimitMinutes, url]);
    const workspaceTabs: Array<{ key: AgentWorkspaceView; label: string; count?: number }> = [
        { key: 'run', label: 'Run' },
        { key: 'library', label: 'Agent Library', count: agentDefinitions.length },
        { key: 'reports', label: 'Reports', count: reportSearchResults.length || undefined },
        { key: 'queue', label: 'Queue', count: (queueStatus?.active || 0) + (queueStatus?.queued || 0) || undefined },
    ];
    const agentModeTabs: AgentWorkspaceMode[] = ['exploratory', 'custom'];
    const handleAgentModeTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
        if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const currentIndex = agentModeTabs.indexOf(selectedAgent);
        const lastIndex = agentModeTabs.length - 1;
        const nextIndex = event.key === 'Home'
            ? 0
            : event.key === 'End'
            ? lastIndex
            : event.key === 'ArrowRight' || event.key === 'ArrowDown'
            ? (currentIndex + 1) % agentModeTabs.length
            : (currentIndex - 1 + agentModeTabs.length) % agentModeTabs.length;
        const nextMode = agentModeTabs[nextIndex];
        selectAgentMode(nextMode);
        window.requestAnimationFrame(() => document.getElementById(`agents-agent-tab-${nextMode}`)?.focus());
    };

    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
            <style>{`
                .agents-workspace-grid {
                    display: grid;
                    grid-template-columns: minmax(220px, 0.72fr) minmax(300px, 0.95fr) minmax(0, 2fr);
                    gap: 1rem;
                    align-items: start;
                }
                .agents-panel {
                    min-width: 0;
                }
                .agents-panel-scroll {
                    max-height: calc(100vh - 11rem);
                    overflow-y: auto;
                }
                .agents-mobile-trigger {
                    display: none;
                }
                .agents-desktop-content {
                    display: block;
                }
                .agents-history-row {
                    width: 100%;
                    min-height: 44px;
                    text-align: left;
                    border: 0;
                    border-bottom: 1px solid var(--border);
                    background: transparent;
                    color: var(--text);
                    cursor: pointer;
                    transition: background 0.16s var(--ease-smooth), border-color 0.16s var(--ease-smooth);
                }
                .agents-history-row:focus-visible,
                .agents-segment-button:focus-visible,
                .agents-icon-button:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-visually-hidden {
                    position: absolute;
                    width: 1px;
                    height: 1px;
                    padding: 0;
                    margin: -1px;
                    overflow: hidden;
                    clip: rect(0, 0, 0, 0);
                    white-space: nowrap;
                    border: 0;
                }
                .agents-history-filter-grid {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                    gap: 0.5rem;
                    min-width: 0;
                }
                .agents-history-filter-grid > div {
                    min-width: 0;
                }
                .agents-history-filter-trigger {
                    height: 36px !important;
                    min-height: 36px !important;
                    padding: 0 0.65rem !important;
                    font-size: 0.78rem;
                    line-height: 1;
                    white-space: nowrap;
                }
                .agents-history-filter-trigger > span {
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-history-filter-trigger svg {
                    width: 14px;
                    height: 14px;
                }
                .agents-workspace-tabs {
                    display: flex;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                    margin-bottom: 1rem;
                }
                .agents-workspace-tab {
                    min-height: 40px;
                    padding: 0.5rem 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface);
                    color: var(--text-secondary);
                    font-size: 0.86rem;
                    font-weight: 700;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    gap: 0.45rem;
                    transition: background 0.16s var(--ease-smooth), color 0.16s var(--ease-smooth), border-color 0.16s var(--ease-smooth);
                }
                .agents-workspace-tab[data-active="true"] {
                    background: var(--primary-glow);
                    color: var(--primary);
                    border-color: var(--primary);
                }
                .agents-workspace-tab:focus-visible,
                .agents-action-button:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-run-plan {
                    display: grid;
                    gap: 0.45rem;
                    margin-bottom: 0.85rem;
                    padding: 0.8rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface-hover);
                }
                .agents-run-plan-row {
                    display: grid;
                    grid-template-columns: 92px minmax(0, 1fr);
                    gap: 0.5rem;
                    font-size: 0.78rem;
                    line-height: 1.35;
                }
                .agents-run-plan-row strong {
                    color: var(--text-secondary);
                    font-weight: 750;
                }
                .agents-run-plan-row span {
                    min-width: 0;
                    overflow-wrap: anywhere;
                }
                .agents-builder-grid {
                    display: grid;
                    grid-template-columns: minmax(0, 0.9fr) minmax(280px, 1.1fr);
                    gap: 1rem;
                }
                .agents-report-search-grid {
                    display: grid;
                    grid-template-columns: minmax(220px, 1fr) repeat(2, minmax(150px, 0.35fr));
                    gap: 0.65rem;
                }
                .agents-definition-action-trigger {
                    width: 32px;
                    height: 32px;
                    margin-right: 0.45rem;
                    border-radius: 8px;
                    color: var(--text-secondary) !important;
                }
                .agents-definition-action-trigger:hover,
                .agents-definition-action-trigger[data-state="open"] {
                    background: var(--surface-active) !important;
                    color: var(--text) !important;
                }
                .agents-definition-action-trigger:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-definition-action-menu {
                    min-width: 132px;
                    padding: 0.35rem;
                    background: var(--background-raised) !important;
                    border-color: var(--border) !important;
                    border-radius: 10px !important;
                    box-shadow: 0 14px 32px rgba(0, 0, 0, 0.35) !important;
                }
                .agents-definition-action-item {
                    min-height: 32px;
                    padding: 0.4rem 0.55rem;
                    border-radius: 7px;
                    font-size: 0.82rem;
                    font-weight: 650;
                    cursor: pointer;
                }
                .agents-definition-action-item[data-highlighted] {
                    background: var(--surface-hover);
                    color: var(--text);
                }
                .agents-definition-action-item svg {
                    width: 14px;
                    height: 14px;
                }
                .agents-definition-action-item-danger {
                    color: var(--danger) !important;
                }
                .agents-definition-action-item-danger[data-highlighted] {
                    background: var(--danger-muted);
                    color: var(--danger) !important;
                }
                @media (max-width: 1180px) {
                    .agents-workspace-grid {
                        grid-template-columns: minmax(260px, 0.85fr) minmax(0, 1.35fr);
                    }
                    .agents-setup-panel {
                        grid-column: 1;
                    }
                    .agents-output-panel {
                        grid-column: 2;
                        grid-row: 1 / span 2;
                    }
                }
                @media (max-width: 860px) {
                    .agents-workspace-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-setup-panel,
                    .agents-output-panel {
                        grid-column: auto;
                        grid-row: auto;
                    }
                    .agents-panel-scroll {
                        max-height: none;
                        overflow: visible;
                    }
                    .agents-mobile-trigger {
                        display: inline-flex;
                    }
                    .agents-desktop-content[data-open="false"] {
                        display: none;
                    }
                }
                @media (max-width: 720px) {
                    .agents-builder-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-report-search-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                }
            `}</style>
            <PageHeader
                title="Autonomous Agents"
                subtitle="Deploy AI agents to explore, test, and specify your application autonomously."
                icon={<Bot size={20} />}
            />

            <div aria-live="polite" className="agents-visually-hidden">{workspaceStatus}</div>

            <div className="agents-workspace-tabs" role="tablist" aria-label="Agents workspace views">
                {workspaceTabs.map(tab => (
                    <button
                        key={tab.key}
                        type="button"
                        role="tab"
                        aria-selected={workspaceView === tab.key}
                        data-active={workspaceView === tab.key ? 'true' : 'false'}
                        className="agents-workspace-tab"
                        onClick={() => selectWorkspaceView(tab.key)}
                    >
                        {tab.label}
                        {tab.count ? <Badge variant="secondary">{tab.count}</Badge> : null}
                    </button>
                ))}
            </div>

            {workspaceView === 'run' && (
            <div className="agents-workspace-grid">

                {/* History Sidebar */}
                <Collapsible open={historyOpen} onOpenChange={setHistoryOpen} className="agents-panel">
                    <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
                        <div style={{ padding: '0.8rem 0.9rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem' }}>
                            <div>
                                <h3 style={{ fontWeight: 700, fontSize: '0.9rem', margin: 0 }}>Run History</h3>
                                <p style={{ margin: '0.2rem 0 0', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                                    {filteredHistory.length} of {history.length} runs
                                </p>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <button className="btn-icon agents-icon-button" type="button" onClick={fetchHistory} title="Refresh run history" aria-label="Refresh run history">
                                    <RotateCcw size={14} />
                                </button>
                                <CollapsibleTrigger asChild>
                                    <button className="btn-icon agents-icon-button agents-mobile-trigger" type="button" aria-label={historyOpen ? 'Collapse run history' : 'Expand run history'}>
                                        <ChevronDown size={14} />
                                    </button>
                                </CollapsibleTrigger>
                            </div>
                        </div>
                        <CollapsibleContent forceMount>
                            <div className="agents-desktop-content" data-open={historyOpen ? 'true' : 'false'}>
                                <div style={{ padding: '0.75rem', display: 'grid', gap: '0.55rem', borderBottom: '1px solid var(--border)' }}>
                                    <Label htmlFor="agents-history-search" className="agents-visually-hidden">Search run history</Label>
                                    <div style={{ position: 'relative' }}>
                                        <Search size={14} style={{ position: 'absolute', left: '0.65rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                                        <Input
                                            id="agents-history-search"
                                            name="agents-history-search"
                                            value={historySearch}
                                            onChange={event => updateHistorySearch(event.target.value)}
                                            placeholder="Search URL, name, or ID"
                                            autoComplete="off"
                                            style={{ paddingLeft: '2rem', minHeight: 40 }}
                                        />
                                    </div>
                                    <div className="agents-history-filter-grid">
                                        <div>
                                            <Select value={historyStatusFilter} onValueChange={value => updateHistoryStatusFilter(value as AgentHistoryStatusFilter)}>
                                                <SelectTrigger aria-label="Filter history by status" className="agents-history-filter-trigger">
                                                    <span className="truncate">Status: {AGENT_HISTORY_STATUS_FILTER_LABELS[historyStatusFilter]}</span>
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="all">All statuses ({historyCounts.status.all})</SelectItem>
                                                    <SelectItem value="active">Active ({historyCounts.status.active})</SelectItem>
                                                    <SelectItem value="completed">Completed ({historyCounts.status.completed})</SelectItem>
                                                    <SelectItem value="failed">Failed ({historyCounts.status.failed})</SelectItem>
                                                    <SelectItem value="cancelled">Cancelled ({historyCounts.status.cancelled})</SelectItem>
                                                    <SelectItem value="paused">Paused ({historyCounts.status.paused})</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div>
                                            <Select value={historyTypeFilter} onValueChange={value => updateHistoryTypeFilter(value as AgentHistoryTypeFilter)}>
                                                <SelectTrigger aria-label="Filter history by agent type" className="agents-history-filter-trigger">
                                                    <span className="truncate">Type: {AGENT_HISTORY_TYPE_FILTER_LABELS[historyTypeFilter]}</span>
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="all">All types ({historyCounts.type.all})</SelectItem>
                                                    <SelectItem value="exploratory">Explorer ({historyCounts.type.exploratory})</SelectItem>
                                                    <SelectItem value="custom">Custom ({historyCounts.type.custom})</SelectItem>
                                                    <SelectItem value="writer">Writer ({historyCounts.type.writer})</SelectItem>
                                                    <SelectItem value="spec_generation">Spec runs ({historyCounts.type.spec_generation})</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                    </div>
                                </div>
                                <div className="agents-panel-scroll">
                                    {history.length === 0 ? (
                                        <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                            No runs yet.
                                        </div>
                                    ) : filteredHistory.length === 0 ? (
                                        <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                            No runs match the current filters.
                                        </div>
                                    ) : (
                                        filteredHistory.map(run => (
                                            <button
                                                key={run.id}
                                                type="button"
                                                className="agents-history-row"
                                                onClick={() => selectRun(run.id)}
                                                aria-current={selectedRunId === run.id ? 'true' : undefined}
                                                style={{
                                                    padding: '0.75rem 0.85rem',
                                                    background: selectedRunId === run.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                                                    borderLeft: selectedRunId === run.id ? '3px solid var(--primary)' : '3px solid transparent'
                                                }}
                                            >
                                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem', gap: '0.6rem' }}>
                                                    <span style={{ fontWeight: 700, fontSize: '0.84rem', color: run.agent_type === 'custom' ? 'var(--success)' : run.agent_type === 'writer' || run.agent_type === 'spec_generation' ? 'var(--primary)' : 'var(--warning)' }}>
                                                        {agentRunDisplayName(run)}
                                                    </span>
                                                    <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{formatDate(run.created_at)}</span>
                                                </div>
                                                <div style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text)' }}>
                                                    {run.config?.url?.replace('https://', '') || run.config?.agent_name || run.id}
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.45rem', marginTop: '0.45rem' }}>
                                                    <StatusBadge status={run.status} />
                                                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{run.id.slice(0, 8)}</span>
                                                </div>
                                            </button>
                                        ))
                                    )}
                                </div>
                            </div>
                        </CollapsibleContent>
                    </div>
                </Collapsible>

                {/* Left Column: Configuration */}
                <Collapsible open={setupOpen} onOpenChange={setSetupOpen} className="agents-panel agents-setup-panel">
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

                    {/* Agent Selection */}
                    <div className="card" style={{ padding: '0', overflow: 'hidden', flexShrink: 0 }}>
                        <div style={{ padding: '0.8rem 0.9rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
                            <div>
                                <h3 style={{ fontWeight: 700, fontSize: '0.9rem', margin: 0 }}>Run Setup</h3>
                                <p style={{ margin: '0.2rem 0 0', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                                    {selectedAgent === 'custom' ? 'Custom agent' : 'Explorer agent'}
                                </p>
                            </div>
                            <CollapsibleTrigger asChild>
                                <button className="btn-icon agents-icon-button agents-mobile-trigger" type="button" aria-label={setupOpen ? 'Collapse run setup' : 'Expand run setup'}>
                                    <ChevronDown size={14} />
                                </button>
                            </CollapsibleTrigger>
                        </div>
                        <CollapsibleContent forceMount>
                            <div className="agents-desktop-content" data-open={setupOpen ? 'true' : 'false'} style={{ padding: '0.5rem' }}>
                            <div role="tablist" aria-label="Agent type" style={{ display: 'grid', gap: '0.5rem' }}>
                            <button
                                id="agents-agent-tab-exploratory"
                                type="button"
                                role="tab"
                                aria-selected={selectedAgent === 'exploratory'}
                                aria-controls="agents-run-setup-panel"
                                tabIndex={selectedAgent === 'exploratory' ? 0 : -1}
                                className="agents-segment-button"
                                onKeyDown={handleAgentModeTabKeyDown}
                                onClick={() => selectAgentMode('exploratory')}
                                style={{
                                    width: '100%',
                                    padding: '0.75rem',
                                    cursor: 'pointer',
                                    background: selectedAgent === 'exploratory' ? 'var(--primary-glow)' : 'transparent',
                                    border: selectedAgent === 'exploratory' ? '1px solid var(--primary)' : '1px solid transparent',
                                    borderRadius: '8px',
                                    display: 'flex', gap: '0.75rem',
                                    textAlign: 'left',
                                    minHeight: '44px'
                                }}
                            >
                                <Terminal size={20} color={selectedAgent === 'exploratory' ? 'var(--primary)' : 'var(--text-secondary)'} />
                                <div>
                                    <h4 style={{ fontWeight: 600, fontSize: '0.9rem', color: selectedAgent === 'exploratory' ? 'var(--primary)' : 'var(--text)' }}>Enhanced Explorer</h4>
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        15-min autonomous exploration
                                    </p>
                                </div>
                            </button>

                            <button
                                id="agents-agent-tab-custom"
                                type="button"
                                role="tab"
                                aria-selected={selectedAgent === 'custom'}
                                aria-controls="agents-run-setup-panel"
                                tabIndex={selectedAgent === 'custom' ? 0 : -1}
                                className="agents-segment-button"
                                onKeyDown={handleAgentModeTabKeyDown}
                                onClick={() => selectAgentMode('custom')}
                                style={{
                                    width: '100%',
                                    padding: '0.75rem',
                                    cursor: 'pointer',
                                    background: selectedAgent === 'custom' ? 'var(--primary-glow)' : 'transparent',
                                    border: selectedAgent === 'custom' ? '1px solid var(--primary)' : '1px solid transparent',
                                    borderRadius: '8px',
                                    display: 'flex', gap: '0.75rem',
                                    textAlign: 'left',
                                    minHeight: '44px'
                                }}
                            >
                                <Wrench size={20} color={selectedAgent === 'custom' ? 'var(--primary)' : 'var(--text-secondary)'} />
                                <div>
                                    <h4 style={{ fontWeight: 600, fontSize: '0.9rem', color: selectedAgent === 'custom' ? 'var(--primary)' : 'var(--text)' }}>Custom Agent</h4>
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        User-defined tools and prompt
                                    </p>
                                </div>
                            </button>
                            </div>
                            </div>
                        </CollapsibleContent>
                    </div>

                    {/* Custom Agents */}
                    <div className="card" style={{ padding: '1rem', flexShrink: 0 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', gap: '0.75rem' }}>
                            <div>
                                <h3 style={{ fontWeight: 700, fontSize: '0.9rem', margin: 0 }}>Custom Agents</h3>
                                <p style={{ margin: '0.2rem 0 0', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                                    {agentDefinitions.length} saved
                                </p>
                            </div>
                            <Button type="button" size="icon" variant="outline" onClick={resetDefinitionForm} title="Create agent" aria-label="Create custom agent">
                                <Plus size={15} />
                            </Button>
                        </div>

                        {agentDefinitions.length === 0 ? (
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                No custom agents yet.
                            </div>
                        ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                {agentDefinitions.map(definition => (
                                    <div
                                        key={definition.id}
                                        style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'minmax(0, 1fr) auto',
                                            alignItems: 'center',
                                            gap: '0.35rem',
                                            border: selectedDefinitionId === definition.id ? '1px solid var(--primary)' : '1px solid var(--border)',
                                            borderRadius: '6px',
                                            background: selectedDefinitionId === definition.id ? 'var(--primary-glow)' : 'var(--surface-hover)',
                                        }}
                                    >
                                        <button
                                            type="button"
                                            onClick={() => { selectDefinition(definition.id); selectAgentMode('custom'); }}
                                            aria-pressed={selectedDefinitionId === definition.id}
                                            className="agents-segment-button"
                                            style={{
                                                minWidth: 0,
                                                minHeight: 44,
                                                padding: '0.65rem',
                                                border: 0,
                                                background: 'transparent',
                                                color: 'var(--text)',
                                                textAlign: 'left',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            <div style={{ fontSize: '0.85rem', fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{definition.name}</div>
                                            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{definition.tool_ids.length} tools</div>
                                        </button>
                                        <DropdownMenu
                                            modal={false}
                                            open={openDefinitionMenuId === definition.id}
                                            onOpenChange={(open) => setOpenDefinitionMenuId(open ? definition.id : null)}
                                        >
                                            <DropdownMenuTrigger asChild>
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="icon"
                                                    aria-label={`Open actions for ${definition.name}`}
                                                    className="agents-definition-action-trigger"
                                                    onClick={(event) => event.stopPropagation()}
                                                    onPointerDown={(event) => event.stopPropagation()}
                                                >
                                                    <MoreHorizontal size={15} />
                                                </Button>
                                            </DropdownMenuTrigger>
                                            <DropdownMenuContent
                                                align="end"
                                                sideOffset={6}
                                                className="agents-definition-action-menu"
                                                onClick={(event) => event.stopPropagation()}
                                            >
                                                <DropdownMenuItem
                                                    className="agents-definition-action-item"
                                                    onSelect={(event) => {
                                                        editDefinitionFromMenu(definition, event);
                                                    }}
                                                >
                                                    <Settings size={14} />
                                                    Edit
                                                </DropdownMenuItem>
                                                <DropdownMenuItem
                                                    className="agents-definition-action-item agents-definition-action-item-danger"
                                                    onSelect={(event) => {
                                                        archiveDefinitionFromMenu(definition, event);
                                                    }}
                                                >
                                                    <Archive size={14} />
                                                    Archive
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
                                        </DropdownMenu>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Configuration Form */}
                    <div id="agents-run-setup-panel" role="tabpanel" className="card" style={{ padding: '1.25rem', flexShrink: 0 }}>
                        {selectedAgent === 'custom' && (
                            <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                <label htmlFor="agents-definition-select" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Runnable Agent</label>
                                <select
                                    id="agents-definition-select"
                                    name="definitionId"
                                    value={selectedDefinitionId}
                                    onChange={e => selectDefinition(e.target.value)}
                                    style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)' }}
                                >
                                    <option value="">Select an agent</option>
                                    {agentDefinitions.map(definition => (
                                        <option key={definition.id} value={definition.id}>{definition.name}</option>
                                    ))}
                                </select>
                                {selectedDefinition && (
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0' }}>
                                        {selectedDefinition.description || `${selectedDefinition.tool_ids.length} selected tools`} · Runtime: {selectedDefinition.runtime === 'hermes' ? 'Hermes' : 'Claude SDK'}
                                    </p>
                                )}
                            </div>
                        )}

                        {selectedAgent !== 'custom' && (
                            <div style={{ marginBottom: '1rem' }}>
                                <label htmlFor="agents-runtime-select" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Agent Runtime</label>
                                <select
                                    id="agents-runtime-select"
                                    name="runtime"
                                    value={agentRuntime}
                                    onChange={e => setAgentRuntime(e.target.value)}
                                    style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)' }}
                                >
                                    <option value="claude_sdk">Claude SDK</option>
                                    <option value="hermes">Hermes</option>
                                </select>
                                {agentRuntime === 'hermes' && (
                                    <p style={{ fontSize: '0.75rem', color: hermesReachable ? 'var(--success)' : 'var(--warning)', margin: '0.5rem 0 0', lineHeight: 1.4 }}>
                                        {hermesReachable ? 'Hermes API is reachable.' : hermesStatusMessage || 'Hermes API is not reachable yet.'}
                                    </p>
                                )}
                            </div>
                        )}

                        <div style={{ marginBottom: '1rem' }}>
                            <label htmlFor="agents-target-url" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Target URL</label>
                            <input
                                id="agents-target-url"
                                name="targetUrl"
                                type="url"
                                placeholder={selectedAgent === 'custom' ? 'Optional target URL' : 'https://example.com'}
                                value={url}
                                onChange={e => setUrl(e.target.value)}
                                autoComplete="url"
                                style={{
                                    width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                }}
                            />
                        </div>

                        {selectedAgent === 'exploratory' && (
                            <>
                                <div style={{ marginBottom: '1rem' }}>
                                    <label htmlFor="agents-time-limit" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Time Limit (minutes)</label>
                                    <input
                                        id="agents-time-limit"
                                        name="timeLimitMinutes"
                                        type="number"
                                        min="2"
                                        max="60"
                                        value={timeLimitMinutes}
                                        onChange={e => setTimeLimitMinutes(parseInt(e.target.value) || 15)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <label htmlFor="agents-auth-type" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>
                                        <Lock size={14} /> Authentication
                                    </label>
                                    <select
                                        id="agents-auth-type"
                                        name="authType"
                                        value={authType}
                                        onChange={e => setAuthType(e.target.value as AuthType)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    >
                                        <option value="none">No Authentication</option>
                                        <option value="credentials">Credentials (Login Form)</option>
                                        <option value="session">Browser Login Session</option>
                                    </select>
                                </div>

                                {authType === 'credentials' && (
                                    <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px' }}>
                                        <div style={{ marginBottom: '0.5rem' }}>
                                            <label htmlFor="agents-login-url" style={{ fontSize: '0.75rem', fontWeight: 500 }}>Login URL</label>
                                            <input
                                                id="agents-login-url"
                                                name="loginUrl"
                                                type="text"
                                                placeholder="/login"
                                                value={authCredentials.loginUrl}
                                                onChange={e => setAuthCredentials({ ...authCredentials, loginUrl: e.target.value })}
                                                style={{
                                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                                }}
                                            />
                                        </div>
                                        <div style={{ marginBottom: '0.5rem' }}>
                                            <label htmlFor="agents-auth-username" style={{ fontSize: '0.75rem', fontWeight: 500 }}>Username</label>
                                            <input
                                                id="agents-auth-username"
                                                name="username"
                                                type="text"
                                                placeholder="testuser"
                                                value={authCredentials.username}
                                                onChange={e => setAuthCredentials({ ...authCredentials, username: e.target.value })}
                                                autoComplete="username"
                                                style={{
                                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                                }}
                                            />
                                        </div>
                                        <div>
                                            <label htmlFor="agents-auth-password" style={{ fontSize: '0.75rem', fontWeight: 500 }}>Password</label>
                                            <input
                                                id="agents-auth-password"
                                                name="password"
                                                type="password"
                                                placeholder="••••••••"
                                                value={authCredentials.password}
                                                onChange={e => setAuthCredentials({ ...authCredentials, password: e.target.value })}
                                                autoComplete="current-password"
                                                style={{
                                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                                }}
                                            />
                                        </div>
                                    </div>
                                )}

                                {authType === 'session' && (
                                    <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px' }}>
                                        <label htmlFor="agents-session-select" style={{ fontSize: '0.75rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>Browser Login Session</label>
                                        <select
                                            id="agents-session-select"
                                            name="browserAuthSession"
                                            value={sessionId}
                                            onChange={e => setSessionId(e.target.value)}
                                            style={{
                                                width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                            }}
                                        >
                                            <option value="">Select a browser login session</option>
                                            {sessions.map(s => (
                                                <option key={s.id} value={s.id} disabled={!isBrowserAuthSessionSelectable(s)}>
                                                    {browserAuthSessionLabel(s)}
                                                </option>
                                            ))}
                                        </select>
                                        <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                            {sessions.length === 0
                                                ? 'No browser login sessions found in Settings.'
                                                : `${sessions.filter(isBrowserAuthSessionSelectable).length} active browser login session${sessions.filter(isBrowserAuthSessionSelectable).length !== 1 ? 's' : ''} available`}
                                        </p>
                                    </div>
                                )}
                            </>
                        )}

                        {selectedAgent === 'custom' && (
                            <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px' }}>
                                <label htmlFor="agents-custom-session-select" style={{ fontSize: '0.75rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>Browser Login Session</label>
                                <select
                                    id="agents-custom-session-select"
                                    name="customBrowserAuthSession"
                                    value={authType === 'session' ? sessionId : ''}
                                    onChange={e => {
                                        setSessionId(e.target.value);
                                        setAuthType(e.target.value ? 'session' : 'none');
                                    }}
                                    style={{
                                        width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                        border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                    }}
                                >
                                    <option value="">No browser login session</option>
                                    {sessions.map(s => (
                                        <option key={s.id} value={s.id} disabled={!isBrowserAuthSessionSelectable(s)}>
                                            {browserAuthSessionLabel(s)}
                                        </option>
                                    ))}
                                </select>
                                <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                    {sessions.length === 0
                                        ? 'No browser login sessions found in Settings.'
                                        : `${sessions.filter(isBrowserAuthSessionSelectable).length} active browser login session${sessions.filter(isBrowserAuthSessionSelectable).length !== 1 ? 's' : ''} available`}
                                </p>
                            </div>
                        )}

                        <div style={{ marginBottom: '1.25rem' }}>
                            <label htmlFor="agents-instructions" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>
                                {selectedAgent === 'custom' ? 'Task Prompt' : 'Instructions (Optional)'}
                            </label>
                            <textarea
                                id="agents-instructions"
                                name="instructions"
                                placeholder={selectedAgent === 'custom' ? "Inspect the API calls triggered by the login and checkout flows." : selectedAgent === 'exploratory' ? "Focus on checkout flow, test edge cases..." : "Generate spec for login page..."}
                                value={instructions}
                                onChange={e => setInstructions(e.target.value)}
                                rows={3}
                                style={{
                                    width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)',
                                    resize: 'vertical'
                                }}
                            />
                        </div>

                        {selectedAgent === 'custom' && (
                            <div style={{ marginBottom: '1rem' }}>
                                <label htmlFor="agents-test-data-refs" style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                    Project Test Data Refs
                                </label>
                                <Input
                                    id="agents-test-data-refs"
                                    name="testDataRefs"
                                    value={testDataRefs}
                                    onChange={e => setTestDataRefs(e.target.value)}
                                    placeholder="Refs appear here after adding"
                                    autoComplete="off"
                                    style={{ height: '36px', minHeight: '36px', borderRadius: '8px', fontSize: '0.8rem', marginBottom: '0.5rem' }}
                                />
                                <TestDataPicker
                                    projectId={currentProject?.id}
                                    mode="ref"
                                    variant="sidebar"
                                    compact
                                    insertLabel="Add"
                                    editLabel="Edit"
                                    onInsert={(value) => setTestDataRefs(prev => prev ? `${prev}, ${value}` : value)}
                                />
                            </div>
                        )}

                        {selectedAgent === 'exploratory' && (
                            <button
                                onClick={() => setShowAdvanced(!showAdvanced)}
                                style={{
                                    width: '100%', padding: '0.5rem', marginBottom: '0.75rem', borderRadius: '6px', fontSize: '0.85rem',
                                    background: 'var(--surface-hover)', color: 'var(--text)', fontWeight: 500, border: '1px solid var(--border)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', cursor: 'pointer'
                                }}
                            >
                                <Settings size={14} /> {showAdvanced ? 'Hide' : 'Show'} Advanced Options
                            </button>
                        )}

                        {showAdvanced && selectedAgent === 'exploratory' && (
                            <>
                                <div style={{ marginBottom: '1rem' }}>
                                    <label htmlFor="agents-test-data-json" style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                        Test Data (JSON)
                                    </label>
                                    <textarea
                                        id="agents-test-data-json"
                                        name="testDataJson"
                                        placeholder='{"usernames": ["testuser", "admin"], "emails": ["test@example.com", ""]}'
                                        value={testData}
                                        onChange={e => setTestData(e.target.value)}
                                        rows={3}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.85rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)',
                                            resize: 'vertical', fontFamily: 'monospace'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <label htmlFor="agents-focus-areas" style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                        Focus Areas (comma-separated)
                                    </label>
                                    <input
                                        id="agents-focus-areas"
                                        name="focusAreas"
                                        type="text"
                                        placeholder="checkout, user-profile, search"
                                        value={focusAreas}
                                        onChange={e => setFocusAreas(e.target.value)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <label htmlFor="agents-excluded-patterns" style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                        Excluded URL Patterns (comma-separated)
                                    </label>
                                    <input
                                        id="agents-excluded-patterns"
                                        name="excludedPatterns"
                                        type="text"
                                        placeholder="/logout, /delete-account"
                                        value={excludedPatterns}
                                        onChange={e => setExcludedPatterns(e.target.value)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                </div>
                            </>
                        )}

                        {runFormError && (
                            <Alert variant="destructive" style={{ marginBottom: '0.85rem' }}>
                                <AlertTriangle size={16} />
                                <AlertDescription>{runFormError}</AlertDescription>
                            </Alert>
                        )}

                        <div className="agents-run-plan" aria-label="Run plan preview">
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.15rem' }}>
                                <strong style={{ fontSize: '0.84rem' }}>Run Plan</strong>
                                {queueWarnings.degraded && <span style={{ color: 'var(--warning)', fontSize: '0.74rem', fontWeight: 800 }}>Queue needs attention</span>}
                            </div>
                            {runPlanRows.map(([label, value]) => (
                                <div key={label} className="agents-run-plan-row">
                                    <strong>{label}</strong>
                                    <span>{value || '-'}</span>
                                </div>
                            ))}
                        </div>

                        <button
                            onClick={handleRun}
                            disabled={isStarting}
                            style={{
                                width: '100%', padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none', cursor: isStarting ? 'not-allowed' : 'pointer',
                                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                opacity: isStarting ? 0.7 : 1
                            }}
                        >
                            {isStarting ? <><Loader2 className="spin" size={16} /> Starting...</> : <><Play size={16} /> Start Agent</>}
                        </button>
                    </div>
                    </div>
                </Collapsible>

                {/* Right Column: Output */}
                <div className="card agents-panel agents-output-panel" style={{ padding: '0', display: 'flex', flexDirection: 'column', minHeight: '640px', overflow: 'hidden' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.75rem', minHeight: '4.25rem' }}>
                        <h3
                            title={activeRun ? agentRunResultTitle(activeRun) : 'Agent Output'}
                            style={{
                                flex: 1,
                                minWidth: 0,
                                margin: 0,
                                fontWeight: 600,
                                fontSize: '0.9rem',
                                lineHeight: 1.25,
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden',
                                overflowWrap: 'anywhere'
                            }}
                        >
                            {activeRun ? `Result: ${agentRunResultTitle(activeRun)}` : 'Agent Output'}
                        </h3>
                        {activeRun && (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.5rem', flexShrink: 0, flexWrap: 'wrap', maxWidth: '58%' }}>
                                {LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.status !== 'paused' && (
                                    <button
                                        onClick={() => controlAgentRun('pause')}
                                        disabled={runControlPending !== null}
                                        title="Pause agent"
                                        aria-label="Pause agent run"
                                        style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'pause' ? <Loader2 className="spin" size={14} /> : <Pause size={14} />} Pause
                                    </button>
                                )}
                                {activeRun.status === 'paused' && (
                                    <button
                                        onClick={() => controlAgentRun('resume')}
                                        disabled={runControlPending !== null}
                                        title="Resume agent"
                                        aria-label="Resume agent run"
                                        style={{ border: '1px solid var(--primary)', background: 'var(--primary)', color: 'white', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'resume' ? <Loader2 className="spin" size={14} /> : <Play size={14} />} Resume
                                    </button>
                                )}
                                {LIVE_AGENT_STATUSES.has(activeRun.status) && (
                                    <button
                                        onClick={() => setCancelRunDialogOpen(true)}
                                        disabled={runControlPending !== null}
                                        title="Cancel agent"
                                        aria-label="Cancel agent run"
                                        style={{ border: '1px solid var(--danger)', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'cancel' ? <Loader2 className="spin" size={14} /> : <X size={14} />} Cancel
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={exportAgentTrace}
                                    title="Export redacted trace"
                                    aria-label="Export redacted trace"
                                    style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600 }}
                                >
                                    <Download size={14} /> Export
                                </button>
                                <StatusBadge status={activeRun.status} />
                            </div>
                        )}
                    </div>

                    <div style={{ padding: '1.5rem', flex: 1, overflowY: 'auto', background: 'var(--surface)' }}>
                        {!activeRun ? (
                            <div style={{ minHeight: '420px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', textAlign: 'center', gap: '1rem' }}>
                                <Bot size={56} style={{ color: 'var(--primary)' }} />
                                <div>
                                    <h3 style={{ margin: 0, color: 'var(--text)', fontSize: '1.05rem', fontWeight: 800 }}>Start an agent run</h3>
                                    <p style={{ margin: '0.45rem auto 0', maxWidth: 460, lineHeight: 1.5 }}>Choose a saved run from history or use one of the workspace actions to create the next agent task.</p>
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem', justifyContent: 'center' }}>
                                    <Button type="button" onClick={() => { selectAgentMode('exploratory'); setSetupOpen(true); document.getElementById('agents-target-url')?.focus(); }}>
                                        <Play size={14} /> Start Explorer
                                    </Button>
                                    <Button type="button" variant="outline" onClick={() => { selectWorkspaceView('library'); resetDefinitionForm(); }}>
                                        <Plus size={14} /> Create Agent
                                    </Button>
                                    <Button type="button" variant="outline" onClick={() => openAssistantWithPrompt('Help me choose or draft an agent prompt for this project.')}>
                                        <MessageSquare size={14} /> Ask Assistant
                                    </Button>
                                    <Button type="button" variant="outline" asChild>
                                        <Link href="/workflow"><ArrowRight size={14} /> Workflow</Link>
                                    </Button>
                                </div>
                            </div>
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.agent_type === 'exploratory' ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                {activeRun.status === 'paused' && (
                                    <div style={{ padding: '0.9rem 1rem', background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: '8px', color: 'var(--warning)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <Pause size={16} /> Agent is paused. Resume to continue from the current state.
                                    </div>
                                )}

                                <LiveBrowserView
                                    runId={activeRun.id}
                                    isActive={activeRun.status !== 'paused'}
                                    showHeader
                                    artifacts={activeRun.artifacts || []}
                                    latestImage={sortArtifactsByModifiedAt((activeRun.artifacts || []).filter(artifact => artifact.type === 'image'))[0]}
                                    statusMessage={activeRun.progress?.message}
                                    liveViewAvailable={Boolean(activeRun.progress?.live_view_available)}
                                    runtimeMessage={activeRun.progress?.runtime_message}
                                    vncUrl={activeRun.progress?.vnc_url}
                                />
                                <AgentRunCapturePanel activeRun={activeRun} mode="live" />
                                <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />
                                <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                                    {activeRun.status === 'paused'
                                        ? 'Resume to continue from the current state.'
                                        : `Explorer agent is working. This may take up to ${timeLimitMinutes} minutes.`}
                                </p>
                            </div>
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.agent_type === 'spec_generation' ? (
                            <SpecGenerationRunPanel run={activeRun} events={agentEvents} />
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.agent_type === 'custom' ? (
                            (() => {
                                const progress = activeRun.progress || {};
                                const selectedTools = activeRun.config?.selected_tools || [];
                                const hasBrowserTools = Boolean(progress.has_browser_tools) || selectedTools.some((tool: AgentTool) => tool.tool_name?.startsWith('mcp__playwright'));
                                const latestImage = sortArtifactsByModifiedAt((activeRun.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
                                const recentTools = progress.recent_tools || [];
                                const executionStarted = customAgentExecutionStarted(activeRun);
                                const waitingForWorker = (!executionStarted || progress.phase === 'queued') && activeRun.status !== 'paused';
                                const workerMessage = customAgentWorkerMessage(activeRun);
                                return (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                        <div style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                                            gap: '0.75rem',
                                            padding: '1rem',
                                            background: 'var(--surface-hover)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '10px'
                                        }}>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Status</div>
                                                <div style={{ fontWeight: 700, textTransform: 'capitalize' }}>{activeRun.status}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Current Tool</div>
                                                <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{customAgentCurrentActivity(progress)}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Tool Calls</div>
                                                <div style={{ fontWeight: 700 }}>{progress.tool_calls ?? 0}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Browser Actions</div>
                                                <div style={{ fontWeight: 700 }}>{progress.browser_tool_calls ?? 0}</div>
                                            </div>
                                        </div>

                                        {selectedTools.length > 0 && (
                                            <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden', background: 'var(--background)' }}>
                                                <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
                                                    <span>Granted Tools</span>
                                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{selectedTools.length}</span>
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', padding: '0.75rem 1rem' }}>
                                                    {selectedTools.map((tool: AgentTool) => (
                                                        <span key={tool.id || tool.tool_name} title={tool.tool_name} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.32rem 0.5rem', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600 }}>
                                                            <Wrench size={12} /> {tool.label || formatToolName(tool.tool_name)}
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />

                                        {activeRun.status === 'paused' && (
                                            <div style={{ padding: '0.9rem 1rem', background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: '8px', color: 'var(--warning)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <Pause size={16} /> Agent is paused. Resume to continue from the current browser and CLI state.
                                            </div>
                                        )}

                                        {waitingForWorker ? (
                                            <div style={{
                                                padding: '1rem',
                                                background: activeRun.temporal?.error ? 'rgba(239, 68, 68, 0.12)' : 'var(--surface-hover)',
                                                border: `1px solid ${activeRun.temporal?.error ? 'rgba(239, 68, 68, 0.35)' : 'var(--border)'}`,
                                                borderRadius: '10px',
                                                color: activeRun.temporal?.error ? 'var(--danger)' : 'var(--text-secondary)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.65rem',
                                                lineHeight: 1.45
                                            }}>
                                                {activeRun.temporal?.error ? <AlertTriangle size={18} /> : <Loader2 className="spin" size={18} />}
                                                <span>{workerMessage}</span>
                                            </div>
                                        ) : hasBrowserTools ? (
                                            <LiveBrowserView
                                                runId={activeRun.id}
                                                isActive={activeRun.status !== 'paused'}
                                                showHeader
                                                artifacts={activeRun.artifacts || []}
                                                latestImage={latestImage}
                                                statusMessage={progress.message}
                                                liveViewAvailable={Boolean(progress.live_view_available)}
                                                runtimeMessage={progress.runtime_message}
                                                vncUrl={progress.vnc_url}
                                            />
                                        ) : (
                                            <div style={{ padding: '1.25rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                                This custom agent does not have browser tools selected. Follow its tool activity below.
                                            </div>
                                        )}

                                        <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden', background: 'var(--background)' }}>
                                            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                                <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>Latest Screenshot</h4>
                                                {latestImage?.modified_at && (
                                                    <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                                        {new Date(latestImage.modified_at).toLocaleTimeString()}
                                                    </span>
                                                )}
                                            </div>
                                            {latestImage ? (
                                                <a href={getArtifactUrl(latestImage)} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                                                    <img
                                                        src={getArtifactUrl(latestImage)}
                                                        alt="Latest custom agent screenshot"
                                                        style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', maxHeight: '420px', objectFit: 'contain', background: '#000' }}
                                                    />
                                                </a>
                                            ) : (
                                                <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    No screenshots have been captured yet. Select the Screenshot tool for visual fallback.
                                                </div>
                                            )}
                                        </div>

                                        <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden' }}>
                                            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>
                                                Live Activity
                                            </div>
                                            {recentTools.length > 0 ? (
                                                <div style={{ display: 'grid' }}>
                                                    {recentTools.slice().reverse().map((tool: any, i: number) => (
                                                        <div key={`${tool.name}-${tool.at}-${i}`} style={{ padding: '0.65rem 1rem', borderBottom: i === recentTools.length - 1 ? 'none' : '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', fontSize: '0.85rem' }}>
                                                            <span style={{ fontWeight: 600 }}>{tool.label || formatToolName(tool.name)}</span>
                                                            {tool.at && <span style={{ color: 'var(--text-secondary)' }}>{new Date(tool.at).toLocaleTimeString()}</span>}
                                                        </div>
                                                    ))}
                                                </div>
                                            ) : (
                                                <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    {progress.message || 'Waiting for the agent to use its first tool.'}
                                                </div>
                                            )}
                                        </div>

                                        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                                            {progress.message || `This may take up to ${Math.ceil((activeRun.config?.timeout_seconds || 1800) / 60)} minutes.`}
                                        </p>
                                    </div>
                                );
                            })()
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) ? (
                            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                {activeRun.status === 'paused' ? <Pause size={48} style={{ marginBottom: '1rem', color: 'var(--warning)' }} /> : <Loader2 size={48} className="spin" style={{ marginBottom: '1rem', color: 'var(--primary)' }} />}
                                <p>{activeRun.status === 'paused' ? 'Agent is paused.' : 'Agent is working...'}</p>
                                <p style={{ fontSize: '0.9rem', marginTop: '0.5rem' }}>
                                    {activeRun.status === 'paused'
                                        ? 'Resume to continue from the current state.'
                                        : `This may take up to ${activeRun.agent_type === 'custom' ? Math.ceil((activeRun.config?.timeout_seconds || 1800) / 60) : timeLimitMinutes} minutes.`}
                                </p>
                            </div>
                        ) : activeRun.status === 'failed' && activeRun.agent_type === 'spec_generation' ? (
                            <SpecGenerationRunPanel run={activeRun} events={agentEvents} />
                        ) : activeRun.status === 'failed' ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                <div style={{ padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '8px', border: '1px solid rgba(248, 113, 113, 0.2)' }}>
                                    <h4 style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <AlertTriangle size={18} /> Run Failed
                                    </h4>
                                    <p style={{ marginTop: '0.5rem', fontFamily: 'monospace' }}>
                                        {activeRun.result?.error || activeRun.health?.terminal_reason || "Unknown error occurred"}
                                    </p>
                                </div>
                                <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />
                            </div>
                        ) : (
                            // Completed successfully
                            <div className="markdown-content">
                                {activeRun.agent_type !== 'spec_generation' && (
                                    <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />
                                )}
                                {activeRun.agent_type === 'spec_generation' ? (
                                    <SpecGenerationRunPanel run={activeRun} events={agentEvents} />
                                ) : activeRun.agent_type === 'writer' ? (
                                    <>
                                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
                                            <button
                                                onClick={() => downloadSpec(activeRun.result.spec_content || '', 'spec.md')}
                                                style={{ fontSize: '0.85rem', padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                            >
                                                <Download size={14} /> Download Spec
                                            </button>
                                        </div>
                                        <div style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.9rem', color: '#e5e5e5' }}>
                                                {activeRun.result.spec_content || JSON.stringify(activeRun.result, null, 2)}
                                            </pre>
                                        </div>
                                    </>
                                ) : activeRun.agent_type === 'custom' ? (
                                    <CustomAgentReportView
                                        run={activeRun}
                                        activeTab={customResultTab}
                                        onTabChange={selectCustomResultTab}
                                        onAskAssistant={openAssistantWithPrompt}
                                        onCreateSpecFromReport={openSpecFromReportItem}
                                        onImportRequirements={importReportRequirements}
                                        importingRequirementIds={importingRequirementIds}
                                        importError={reportImportError}
                                        reportStatusFilter={reportStatusFilter}
                                        onReportStatusFilterChange={updateReportStatusFilter}
                                        reportSeverityFilter={reportSeverityFilter}
                                        onReportSeverityFilterChange={updateReportSeverityFilter}
                                    />
                                ) : (
                                    // Exploratory Result - User Friendly Display
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                                        {!activeRun.result ? (
                                            <div style={{ padding: '2rem', background: 'var(--primary-glow)', borderRadius: '12px', color: 'var(--primary)', textAlign: 'center' }}>
                                                <Loader2 size={32} className="spin" style={{ marginBottom: '1rem' }} />
                                                <p style={{ fontSize: '1rem', fontWeight: 500 }}>Loading exploration results...</p>
                                                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                                    This may take a moment while we compile the findings.
                                                </p>
                                            </div>
                                        ) : (
                                            <>
                                                <AgentRunCapturePanel activeRun={activeRun} mode="recording" />

                                                {/* Main Summary Card */}
                                                <div style={{ padding: '1.5rem', background: 'linear-gradient(135deg, var(--primary-glow) 0%, rgba(192, 132, 252, 0.1) 100%)', borderRadius: '12px', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                                                        <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                                            <Sparkles size={20} style={{ color: 'white' }} />
                                                        </div>
                                                        <div>
                                                            <h3 style={{ fontWeight: 700, fontSize: '1.2rem', margin: 0 }}>Exploration Complete!</h3>
                                                            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0 0' }}>
                                                                {activeRun.result.elapsed_time_minutes ? `Completed in ${activeRun.result.elapsed_time_minutes.toFixed(1)} minutes` : 'Completed'}
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <p style={{ fontSize: '1rem', lineHeight: '1.6', margin: 0 }}>
                                                        {activeRun.result.summary || 'The agent explored the application and discovered user flows.'}
                                                    </p>
                                                </div>

                                                {/* Key Metrics */}
                                                {activeRun.result.coverage && (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            📊 What Was Explored
                                                        </h4>
                                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                                                            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--primary)' }}>
                                                                    {activeRun.result.coverage.pages_visited || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Pages Visited
                                                                </div>
                                                            </div>
                                                            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--success)' }}>
                                                                    {activeRun.result.coverage.flows_discovered || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    User Flows Found
                                                                </div>
                                                            </div>
                                                            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--warning)' }}>
                                                                    {activeRun.result.coverage.forms_interacted || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Forms Tested
                                                                </div>
                                                            </div>
                                                            {activeRun.result.coverage.errors_found !== undefined && (
                                                                <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                    <div style={{ fontSize: '2rem', fontWeight: 700, color: activeRun.result.coverage.errors_found > 0 ? 'var(--danger)' : 'var(--success)' }}>
                                                                        {activeRun.result.coverage.errors_found || 0}
                                                                    </div>
                                                                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                        Issues Found
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                        {activeRun.result.coverage.coverage_score !== undefined && (
                                                            <div style={{ marginTop: '1rem', padding: '0.75rem', background: activeRun.result.coverage.coverage_score > 0.7 ? 'var(--success-muted)' : 'var(--warning-muted)', borderRadius: '8px', border: `1px solid ${activeRun.result.coverage.coverage_score > 0.7 ? 'rgba(52, 211, 153, 0.2)' : 'rgba(251, 191, 36, 0.2)'}` }}>
                                                                <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>
                                                                    Coverage Score: <strong>{(activeRun.result.coverage.coverage_score * 100).toFixed(0)}%</strong>
                                                                    {activeRun.result.coverage.coverage_score > 0.7 ? ' ✅ Good coverage' : ' ⚠️ Consider exploring more'}
                                                                </span>
                                                            </div>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Discovered Flows - Clear Display */}
                                                {activeRun.result.discovered_flow_summaries && activeRun.result.discovered_flow_summaries.length > 0 ? (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            🔍 Discovered User Flows ({activeRun.result.total_flows_discovered || activeRun.result.discovered_flow_summaries.length})
                                                        </h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                                            These are the complete user journeys the agent found. Each one can be turned into a test.
                                                        </p>
                                                        <div style={{ display: 'grid', gap: '1rem' }}>
                                                            {activeRun.result.discovered_flow_summaries.map((flow: any, i: number) => (
                                                                <div key={i} style={{
                                                                    padding: '1rem',
                                                                    background: 'var(--surface)',
                                                                    borderRadius: '10px',
                                                                    border: '1px solid var(--border)',
                                                                    transition: 'background 0.2s var(--ease-smooth), border-color 0.2s var(--ease-smooth)'
                                                                }}>
                                                                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                                                                        <div style={{
                                                                            width: '32px',
                                                                            height: '32px',
                                                                            borderRadius: '8px',
                                                                            background: 'var(--primary-glow)',
                                                                            display: 'flex',
                                                                            alignItems: 'center',
                                                                            justifyContent: 'center',
                                                                            flexShrink: 0,
                                                                            fontSize: '1.2rem'
                                                                        }}>
                                                                            {i + 1}
                                                                        </div>
                                                                        <div style={{ flex: 1 }}>
                                                                            <h5 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.5rem 0' }}>
                                                                                {flow.title}
                                                                            </h5>
                                                                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                                                <span style={{ fontWeight: 500 }}>{flow.steps_count} steps</span>
                                                                                {flow.entry_point && <span> • Starts: {flow.entry_point}</span>}
                                                                                {flow.exit_point && <span> • Ends: {flow.exit_point}</span>}
                                                                            </div>
                                                                            {flow.pages && flow.pages.length > 0 && (
                                                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                                                    <span style={{ fontWeight: 500 }}>Pages:</span> {flow.pages.join(' → ')}
                                                                                </div>
                                                                            )}
                                                                            {flow.has_edge_cases && (
                                                                                <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'var(--warning-muted)', borderRadius: '6px' }}>
                                                                                    <div style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--warning)' }}>
                                                                                        ⚠️ Includes edge cases
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                        <button
                                                                            onClick={() => fetchFlowDetails(flow.id)}
                                                                            disabled={loadingFlowDetails}
                                                                            style={{
                                                                                padding: '0.5rem 1rem',
                                                                                background: 'var(--primary)',
                                                                                color: 'white',
                                                                                border: 'none',
                                                                                borderRadius: '6px',
                                                                                fontSize: '0.85rem',
                                                                                fontWeight: 500,
                                                                                cursor: loadingFlowDetails ? 'not-allowed' : 'pointer',
                                                                                opacity: loadingFlowDetails ? 0.6 : 1,
                                                                                whiteSpace: 'nowrap'
                                                                            }}
                                                                        >
                                                                            {loadingFlowDetails ? 'Loading...' : 'View Details'}
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div style={{ padding: '2rem', background: 'var(--warning-muted)', borderRadius: '12px', textAlign: 'center' }}>
                                                        <h4 style={{ margin: '0 0 0.5rem 0' }}>No flows discovered</h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: 0 }}>
                                                            The agent didn't find any complete user flows. Try increasing the time limit or exploring a different area.
                                                        </p>
                                                    </div>
                                                )}

                                            {/* Next Steps */}
                                            <div style={{ marginTop: '1.5rem', padding: '1.25rem', background: 'linear-gradient(135deg, var(--success-muted) 0%, var(--primary-glow) 100%)', borderRadius: '12px', border: '1px solid rgba(52, 211, 153, 0.2)' }}>
                                                <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text)' }}>
                                                    <ArrowRight size={18} style={{ color: 'var(--success)' }} /> Next Steps
                                                </h4>
                                                <div style={{ fontSize: '0.9rem', lineHeight: '1.6' }}>
                                                    <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text)' }}>
                                                        <strong>1. Review the discovered flows above</strong> - Make sure they capture the user journeys you want to test
                                                    </p>
                                                    <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text)' }}>
                                                        <strong>2. Click "Generate Test Specs" below</strong> - This creates detailed test specifications for each flow
                                                    </p>
                                                    <p style={{ margin: '0 0 0.75rem 0', color: 'var(--text)' }}>
                                                        <strong>3. Download and run the specs</strong> - Use them with the existing pipeline to generate Playwright tests
                                                    </p>
                                                    <div style={{ padding: '0.75rem', background: 'var(--primary-glow)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                        <Info size={14} style={{ marginRight: '0.5rem', display: 'inline', verticalAlign: 'middle' }} />
                                                        <span style={{ fontStyle: 'italic' }}>Tip: Each discovered flow becomes a separate test spec. You can edit them before running if needed.</span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Spec Synthesis Button */}
                                            {activeRun.agent_type === 'exploratory' && (
                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                <button
                                                    onClick={handleSynthesize}
                                                    disabled={isSynthesizing}
                                                    style={{
                                                        flex: 1, padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                                        background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none',
                                                        cursor: isSynthesizing ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                                        opacity: isSynthesizing ? 0.7 : 1
                                                    }}
                                                >
                                                    {isSynthesizing ? <><Loader2 className="spin" size={16} /> Generating...</> : <><Sparkles size={16} /> Generate Test Specs</>}
                                                </button>
                                            </div>
                                        )}

                                        {/* Generated Specs */}
                                        {specResult && specResult.specs && (
                                            <div>
                                                <h4 style={{ fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <FileText size={18} /> Generated Specs ({specResult.total_specs || 0})
                                                </h4>
                                                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>{specResult.summary}</p>

                                                {/* Happy Path Specs */}
                                                {specResult.specs.happy_path && Object.keys(specResult.specs.happy_path).length > 0 && (
                                                    <div style={{ marginBottom: '1rem' }}>
                                                        <h5 style={{ fontSize: '0.85rem', color: 'var(--success)', marginBottom: '0.5rem' }}>Happy Path Specs</h5>
                                                        {Object.entries(specResult.specs.happy_path).map(([filename, content]) => (
                                                            <div key={filename} style={{ marginBottom: '0.5rem' }}>
                                                                <button
                                                                    onClick={() => downloadSpec(content, filename)}
                                                                    style={{
                                                                        fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--surface-hover)',
                                                                        border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer',
                                                                        display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%'
                                                                    }}
                                                                >
                                                                    <Download size={12} /> {filename}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Edge Case Specs */}
                                                {specResult.specs.edge_cases && Object.keys(specResult.specs.edge_cases).length > 0 && (
                                                    <div>
                                                        <h5 style={{ fontSize: '0.85rem', color: 'var(--warning)', marginBottom: '0.5rem' }}>Edge Case Specs</h5>
                                                        {Object.entries(specResult.specs.edge_cases).map(([filename, content]) => (
                                                            <div key={filename} style={{ marginBottom: '0.5rem' }}>
                                                                <button
                                                                    onClick={() => downloadSpec(content, filename)}
                                                                    style={{
                                                                        fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--surface-hover)',
                                                                        border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer',
                                                                        display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%'
                                                                    }}
                                                                >
                                                                    <Download size={12} /> {filename}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Action Trace */}
                                        {activeRun.result.action_trace && activeRun.result.action_trace.length > 0 && (
                                            <details style={{ marginTop: '1.5rem' }}>
                                                <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <Terminal size={16} /> What the Agent Did ({activeRun.result.action_trace.length} actions)
                                                </summary>
                                                <div style={{ marginTop: '0.5rem', background: '#0f0f0f', padding: '1rem', borderRadius: '8px', fontSize: '0.85rem', fontFamily: 'monospace', maxHeight: '250px', overflowY: 'auto' }}>
                                                    {activeRun.result.action_trace.map((action: any, i: number) => (
                                                        <div key={i} style={{ marginBottom: '0.25rem', color: '#a3a3a3', lineHeight: '1.4' }}>
                                                            <span style={{ color: 'var(--primary)', fontWeight: 500 }}>[{action.step}]</span> {action.action} {action.target} - {action.outcome}
                                                            {action.is_new_discovery && <span style={{ color: 'var(--success)', marginLeft: '0.5rem' }}>✨ New Discovery</span>}
                                                        </div>
                                                    ))}
                                                </div>
                                                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                                                    This shows every action the agent took during exploration. "New Discovery" means the agent found something new.
                                                </p>
                                            </details>
                                        )}
                                        </>
                                    )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
            )}

                <Dialog open={builderOpen} onOpenChange={(open) => { setBuilderOpen(open); if (!open) setDefinitionFormError(null); }}>
                    <DialogContent className="max-w-[920px]" style={{ width: 'min(920px, calc(100vw - 2rem))', maxHeight: '86vh', overflowY: 'auto' }}>
                        <DialogHeader>
                            <DialogTitle>{definitionForm.id ? 'Edit Custom Agent' : 'Create Custom Agent'}</DialogTitle>
                            <DialogDescription>
                                Configure the system prompt, runtime, default test data, and allowed tools.
                            </DialogDescription>
                        </DialogHeader>

                        {definitionFormError && (
                            <Alert variant="destructive">
                                <AlertTriangle size={16} />
                                <AlertDescription>{definitionFormError}</AlertDescription>
                            </Alert>
                        )}

                        <div className="agents-builder-grid">
                            <div style={{ display: 'grid', gap: '0.85rem', alignContent: 'start' }}>
                                <div style={{ display: 'grid', gap: '0.35rem' }}>
                                    <Label htmlFor="definition-name">Name</Label>
                                    <Input id="definition-name" name="definitionName" value={definitionForm.name} onChange={e => setDefinitionForm({ ...definitionForm, name: e.target.value })} placeholder="API explorer" autoComplete="off" />
                                </div>
                                <div style={{ display: 'grid', gap: '0.35rem' }}>
                                    <Label htmlFor="definition-description">Description</Label>
                                    <Input id="definition-description" name="definitionDescription" value={definitionForm.description} onChange={e => setDefinitionForm({ ...definitionForm, description: e.target.value })} placeholder="Explores pages and reports API calls" autoComplete="off" />
                                </div>
                                <div style={{ display: 'grid', gap: '0.35rem' }}>
                                    <Label htmlFor="definition-system-prompt">System Prompt</Label>
                                    <textarea
                                        id="definition-system-prompt"
                                        name="definitionSystemPrompt"
                                        value={definitionForm.system_prompt}
                                        onChange={e => setDefinitionForm({ ...definitionForm, system_prompt: e.target.value })}
                                        rows={7}
                                        style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', fontSize: '0.86rem', border: '1px solid var(--border)', background: 'var(--background-raised)', color: 'var(--text)', resize: 'vertical' }}
                                    />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                                        <Label htmlFor="definition-runtime">Runtime</Label>
                                        <Select value={definitionForm.runtime} onValueChange={value => setDefinitionForm({ ...definitionForm, runtime: value })}>
                                            <SelectTrigger id="definition-runtime" aria-label="Runtime">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="claude_sdk">Claude SDK</SelectItem>
                                                <SelectItem value="hermes">Hermes</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                                        <Label htmlFor="definition-timeout">Timeout seconds</Label>
                                        <Input id="definition-timeout" name="definitionTimeoutSeconds" type="number" min={60} max={7200} value={definitionForm.timeout_seconds} onChange={e => setDefinitionForm({ ...definitionForm, timeout_seconds: parseInt(e.target.value) || 1800 })} />
                                    </div>
                                </div>
                                <div style={{ display: 'grid', gap: '0.35rem' }}>
                                    <Label htmlFor="definition-test-data-refs">Default Test Data Refs</Label>
                                    <Input id="definition-test-data-refs" name="definitionTestDataRefs" value={definitionForm.test_data_refs} onChange={e => setDefinitionForm({ ...definitionForm, test_data_refs: e.target.value })} placeholder="login-users.valid-admin" autoComplete="off" />
                                    <TestDataPicker
                                        projectId={currentProject?.id}
                                        mode="ref"
                                        onInsert={(value) => setDefinitionForm(prev => ({
                                            ...prev,
                                            test_data_refs: prev.test_data_refs ? `${prev.test_data_refs}, ${value}` : value,
                                        }))}
                                    />
                                </div>
                            </div>

                            <div style={{ display: 'grid', gap: '0.65rem', alignContent: 'start' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', alignItems: 'center' }}>
                                    <Label>Tools</Label>
                                    <Badge variant="secondary">{definitionForm.tool_ids.length} of {toolCatalog.length} selected</Badge>
                                </div>
                                <div style={{ maxHeight: '520px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '8px', padding: '0.75rem', display: 'grid', gap: '0.9rem' }}>
                                    {Object.entries(toolsByCategory).map(([category, tools]) => (
                                        <fieldset key={category} style={{ border: 0, margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                                                <legend style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', fontWeight: 800, textTransform: 'uppercase' }}>
                                                    {category} ({tools.length})
                                                </legend>
                                                <Button type="button" variant="ghost" size="sm" onClick={() => toggleCategoryTools(tools)}>
                                                    {tools.every(tool => definitionForm.tool_ids.includes(tool.id)) ? 'Clear' : 'Select all'}
                                                </Button>
                                            </div>
                                            {tools.map(tool => (
                                                <label key={tool.id} style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0, 1fr)', gap: '0.5rem', alignItems: 'start', minHeight: 44, cursor: 'pointer' }}>
                                                    <input
                                                        type="checkbox"
                                                        checked={definitionForm.tool_ids.includes(tool.id)}
                                                        onChange={() => toggleDefinitionTool(tool.id)}
                                                        style={{ marginTop: '0.25rem' }}
                                                    />
                                                    <span style={{ minWidth: 0 }}>
                                                        <span style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                                            <span style={{ fontWeight: 700, fontSize: '0.82rem' }}>{tool.label}</span>
                                                            <Badge variant={tool.risk === 'destructive' || tool.risk === 'high' ? 'destructive' : 'secondary'}>{tool.risk}</Badge>
                                                        </span>
                                                        <span style={{ display: 'block', color: 'var(--text-secondary)', lineHeight: 1.35, fontSize: '0.78rem' }}>{tool.description}</span>
                                                    </span>
                                                </label>
                                            ))}
                                        </fieldset>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <DialogFooter style={{ gap: '0.6rem' }}>
                            <Button type="button" variant="outline" onClick={() => setBuilderOpen(false)}>Cancel</Button>
                            <Button type="button" onClick={saveDefinition} disabled={savingDefinition}>
                                {savingDefinition ? <Loader2 className="spin" size={14} /> : <Save size={14} />} Save Agent
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                <Dialog open={Boolean(archiveCandidate)} onOpenChange={(open) => !open && setArchiveCandidate(null)}>
                    <DialogContent>
                        <DialogHeader>
                            <DialogTitle>Archive Custom Agent</DialogTitle>
                            <DialogDescription>
                                Existing run history will remain. The agent will no longer appear as runnable.
                            </DialogDescription>
                        </DialogHeader>
                        <p style={{ margin: 0, color: 'var(--text)' }}>
                            Archive "{archiveCandidate?.name}"?
                        </p>
                        <DialogFooter style={{ gap: '0.6rem' }}>
                            <Button type="button" variant="outline" onClick={() => setArchiveCandidate(null)}>Cancel</Button>
                            <Button
                                type="button"
                                variant="destructive"
                                onClick={async () => {
                                    if (!archiveCandidate) return;
                                    await archiveDefinition(archiveCandidate);
                                    setArchiveCandidate(null);
                                }}
                            >
                                <Archive size={14} /> Archive
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                <ConfirmDialog
                    open={cancelRunDialogOpen}
                    onOpenChange={setCancelRunDialogOpen}
                    title="Cancel Agent Run"
                    description={activeRun ? `Cancel ${agentRunResultTitle(activeRun)}? The run will stop and current evidence will remain available in history.` : 'Cancel this agent run?'}
                    confirmLabel="Cancel Run"
                    variant="danger"
                    loading={runControlPending === 'cancel'}
                    onConfirm={() => controlAgentRun('cancel')}
                />

                {/* Flow Details Modal */}
                <Dialog open={flowModalOpen && Boolean(selectedFlow)} onOpenChange={setFlowModalOpen}>
                    {selectedFlow && (
                        <DialogContent style={{ width: 'min(980px, calc(100vw - 2rem))', maxWidth: '980px', maxHeight: '84vh', overflowY: 'auto' }}>
                            <DialogHeader>
                                <DialogTitle>{selectedFlow.title}</DialogTitle>
                                <DialogDescription>Review the discovered flow and generate a test spec.</DialogDescription>
                            </DialogHeader>

                            {selectedFlow.pages && selectedFlow.pages.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Pages</h4>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {selectedFlow.pages.map((page: string, i: number) => (
                                            <span key={i} style={{
                                                padding: '0.25rem 0.5rem',
                                                background: 'var(--surface-hover)',
                                                borderRadius: '4px',
                                                fontSize: '0.8rem'
                                            }}>
                                                {page}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {selectedFlow.happy_path && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--success)' }}>Happy Path</h4>
                                    <p style={{ fontSize: '0.9rem', lineHeight: '1.5', margin: 0 }}>
                                        {selectedFlow.happy_path}
                                    </p>
                                </div>
                            )}

                            {selectedFlow.edge_cases && selectedFlow.edge_cases.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--warning)' }}>Edge Cases</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {selectedFlow.edge_cases.map((ec: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{ec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {selectedFlow.test_ideas && selectedFlow.test_ideas.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Test Ideas</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {selectedFlow.test_ideas.map((idea: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{idea}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {selectedFlow.entry_point && (
                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                    Entry: {selectedFlow.entry_point}
                                    {selectedFlow.exit_point && ` → Exit: ${selectedFlow.exit_point}`}
                                </div>
                            )}

                            {selectedFlow.source_type === 'custom_report' && (
                                <div style={{ marginBottom: '1rem', padding: '0.85rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)', display: 'grid', gap: '0.65rem' }}>
                                    <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.82rem', fontWeight: 700 }}>
                                        Browser login for spec generation
                                        <select
                                            value={reportSpecAuthMode === 'session' ? `session:${reportSpecAuthSessionId}` : reportSpecAuthMode}
                                            onChange={(event) => {
                                                const value = event.target.value;
                                                if (value.startsWith('session:')) {
                                                    setReportSpecAuthMode('session');
                                                    setReportSpecAuthSessionId(value.slice('session:'.length));
                                                } else {
                                                    setReportSpecAuthMode(value as ReportSpecBrowserAuthMode);
                                                    setReportSpecAuthSessionId('');
                                                }
                                            }}
                                            disabled={generatingSpec}
                                            style={{ minHeight: 38, borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', padding: '0.45rem 0.6rem', fontSize: '0.85rem' }}
                                        >
                                            <option value="project_default" disabled={!projectDefaultBrowserAuthSession}>
                                                {projectDefaultBrowserAuthSession ? `Project default: ${projectDefaultBrowserAuthSession.name || projectDefaultBrowserAuthSession.id}` : 'Project default unavailable'}
                                            </option>
                                            <option value="none">No auth</option>
                                            {activeBrowserAuthSessions.map(item => (
                                                <option key={item.id} value={`session:${item.id}`}>
                                                    {browserAuthSessionLabel(item)}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                    {inheritedBrowserAuthUnavailable && (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--warning)', fontSize: '0.8rem', fontWeight: 600 }}>
                                            <AlertTriangle size={15} /> Original browser login session is no longer active.
                                        </div>
                                    )}
                                </div>
                            )}

                            {(generatingSpec || flowSpecAgentRun) && flowSpecAgentRunId && (
                                <div style={{ display: 'grid', gap: '1rem', margin: '1rem 0', padding: '1rem 0', borderTop: '1px solid var(--border)' }}>
                                    {flowSpecShowBrowser && (
                                        <LiveBrowserView
                                            runId={flowSpecAgentRunId}
                                            isActive={generatingSpec && flowSpecAgentRun?.status !== 'failed'}
                                            showHeader
                                            artifacts={flowSpecAgentRun?.artifacts || []}
                                            latestImage={flowSpecLatestImage}
                                            statusMessage={flowSpecAgentRun?.progress?.message || flowSpecPoller.status?.message}
                                            liveViewAvailable={Boolean(flowSpecAgentRun?.progress?.live_view_available ?? true)}
                                            runtimeMessage={flowSpecAgentRun?.progress?.runtime_message}
                                            vncUrl={flowSpecAgentRun?.progress?.vnc_url}
                                        />
                                    )}
                                    {flowSpecAgentRun?.status === 'completed' && !flowSpecShowBrowser && (
                                        <div style={{ padding: '0.85rem 1rem', background: 'var(--success-muted)', color: 'var(--success)', border: '1px solid rgba(52, 211, 153, 0.2)', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700 }}>
                                            <CheckCircle2 size={16} /> Spec generation completed.
                                        </div>
                                    )}
                                    {flowSpecAgentRun && (
                                        <AgentRunObservabilityPanel run={flowSpecAgentRun} events={flowSpecAgentEvents} />
                                    )}
                                </div>
                            )}

                            {(flowSpecError || flowSpecAgentRun?.status === 'failed') && (
                                <div style={{ margin: '1rem 0', padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', border: '1px solid rgba(248, 113, 113, 0.2)', borderRadius: '8px' }}>
                                    <h4 style={{ margin: 0, fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <AlertTriangle size={18} /> Spec Generation Failed
                                    </h4>
                                    <p style={{ margin: '0.5rem 0 0', fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                        {flowSpecError || flowSpecAgentRun?.result?.error || flowSpecAgentRun?.progress?.message || 'Unknown error'}
                                    </p>
                                    {flowSpecBrowserAuthFailure && (
                                        <div style={{ marginTop: '0.75rem', fontWeight: 700 }}>
                                            Refresh or choose a browser login session.
                                        </div>
                                    )}
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                                <button
                                    onClick={() => {
                                        if (selectedFlow.source_type === 'custom_report') {
                                            const item = {
                                                id: selectedFlow.id,
                                                title: selectedFlow.title,
                                                page: selectedFlow.entry_point,
                                                description: selectedFlow.happy_path,
                                            } as ReportFinding;
                                            createSpecFromReportItem(item, selectedFlow.item_type || 'finding');
                                        } else {
                                            generateFlowSpec(selectedFlow.id);
                                        }
                                    }}
                                    disabled={generatingSpec}
                                    style={{
                                        flex: 1,
                                        padding: '0.75rem 1rem',
                                        background: 'var(--primary)',
                                        color: 'white',
                                        border: 'none',
                                        borderRadius: '8px',
                                        fontSize: '0.9rem',
                                        fontWeight: 500,
                                        cursor: generatingSpec ? 'not-allowed' : 'pointer',
                                        opacity: generatingSpec ? 0.6 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: '0.5rem'
                                    }}
                                >
                                    {generatingSpec ? (
                                        <>
                                            <Loader2 size={16} className="spin" />
                                            {flowSpecPoller.status?.message || 'Generating...'}
                                        </>
                                    ) : selectedFlow.generated_spec ? (
                                        <>
                                            <FileText size={16} />
                                            View Test Spec
                                        </>
                                    ) : (
                                        <>
                                            <FileText size={16} />
                                            Generate Test Spec
                                        </>
                                    )}
                                </button>
                                <button
                                    onClick={() => setFlowModalOpen(false)}
                                    style={{
                                        padding: '0.75rem 1.5rem',
                                        background: 'transparent',
                                        color: 'var(--text-secondary)',
                                        border: '1px solid var(--border)',
                                        borderRadius: '8px',
                                        fontSize: '0.9rem',
                                        fontWeight: 500,
                                        cursor: 'pointer'
                                    }}
                                >
                                    Close
                                </button>
                            </div>
                        </DialogContent>
                    )}
                </Dialog>

                {/* Generated Spec Modal */}
                <Dialog open={specModalOpen && Boolean(generatedSpec)} onOpenChange={setSpecModalOpen}>
                    {generatedSpec && (
                        <DialogContent style={{
                            maxWidth: '800px',
                            maxHeight: '85vh',
                            width: 'min(800px, calc(100vw - 2rem))',
                            overflow: 'hidden',
                            display: 'flex',
                            flexDirection: 'column',
                            padding: 0
                        }}>
                            <DialogTitle className="sr-only">Generated test spec</DialogTitle>
                            <DialogDescription className="sr-only">Generated spec preview and export actions.</DialogDescription>
                            <div style={{
                                padding: '1.25rem 1.5rem',
                                borderBottom: '1px solid var(--border)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between'
                            }}>
                                <div>
                                    <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>
                                        {generatedSpec.flow_title}
                                    </h3>
                                    <div style={{ margin: '0.5rem 0 0 0', display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                        {generatedSpec.cached && (
                                            <span style={{ background: 'var(--primary-glow)', color: 'var(--primary)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Cached</span>
                                        )}
                                        {generatedSpec.pipeline === 'native_planner_generator' && (
                                            <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Intelligent Pipeline</span>
                                        )}
                                        {generatedSpec.validated && (
                                            <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>✓ Validated</span>
                                        )}
                                        {generatedSpec.requires_auth && (
                                            <span style={{ background: 'var(--warning-muted)', color: 'var(--warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Auth Required</span>
                                        )}
                                    </div>
                                    <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                        {generatedSpec.cached
                                            ? 'Previously generated spec'
                                            : 'Generated with real browser exploration'}
                                    </p>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                    {generatedSpec.cached && (
                                        <button
                                            onClick={() => {
                                                if (selectedFlow) {
                                                    generateFlowSpec(selectedFlow.id, true);
                                                }
                                            }}
                                            disabled={generatingSpec}
                                            style={{
                                                padding: '0.5rem 0.75rem',
                                                background: 'transparent',
                                                color: 'var(--text)',
                                                border: '1px solid var(--border)',
                                                borderRadius: '6px',
                                                fontSize: '0.8rem',
                                                fontWeight: 500,
                                                cursor: generatingSpec ? 'not-allowed' : 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.4rem'
                                            }}
                                            title="Generate new version"
                                        >
                                            <RefreshCw size={14} />
                                            Regenerate
                                        </button>
                                    )}
                                    <button
                                        onClick={() => setSpecModalOpen(false)}
                                        type="button"
                                        aria-label="Close generated spec"
                                        style={{
                                            background: 'transparent',
                                            border: 'none',
                                            cursor: 'pointer',
                                            color: 'var(--text-secondary)'
                                        }}
                                    >
                                        <X size={20} />
                                    </button>
                                </div>
                            </div>

                            <div style={{
                                padding: '1.5rem',
                                overflowY: 'auto',
                                flex: 1,
                                background: 'var(--code-bg)',
                                borderRadius: '8px',
                                margin: '1rem',
                                fontSize: '0.85rem',
                                lineHeight: '1.6',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                fontFamily: 'var(--font-mono)'
                            }}>
                                {generatedSpec.spec_content}
                            </div>

                            {/* Split Results Section */}
                            {splitResult && (
                                <div style={{
                                    margin: '0 1rem 1rem 1rem',
                                    padding: '1rem',
                                    background: 'var(--success-muted)',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(52, 211, 153, 0.2)'
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                        <CheckCircle2 size={16} style={{ color: 'var(--success)' }} />
                                        <span style={{ fontWeight: 600, color: 'var(--success)' }}>
                                            Split into {splitResult.count} individual test specs
                                        </span>
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                        Output: specs/{splitResult.output_dir}/
                                    </div>
                                    <div style={{ maxHeight: '150px', overflowY: 'auto' }}>
                                        {splitResult.files.map((file, i) => (
                                            <div key={i} style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.5rem',
                                                padding: '0.35rem 0',
                                                fontSize: '0.8rem',
                                                borderBottom: i < splitResult.files.length - 1 ? '1px solid var(--border)' : 'none'
                                            }}>
                                                <FileText size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {file.split('/').pop()}
                                                </span>
                                                <Link
                                                    href={`/specs?file=${encodeURIComponent(file)}`}
                                                    style={{
                                                        color: 'var(--primary)',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '0.25rem',
                                                        fontSize: '0.75rem',
                                                        textDecoration: 'none'
                                                    }}
                                                >
                                                    <ExternalLink size={12} />
                                                    View
                                                </Link>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div style={{
                                padding: '1rem 1.5rem',
                                borderTop: '1px solid var(--border)',
                                display: 'flex',
                                gap: '0.75rem',
                                justifyContent: 'space-between',
                                flexWrap: 'wrap'
                            }}>
                                {/* Left side - Split button */}
                                <button
                                    onClick={splitSpec}
                                    disabled={splittingSpec || !generatedSpec.spec_file}
                                    style={{
                                        padding: '0.6rem 1rem',
                                        background: splitResult ? 'var(--success-muted)' : 'rgba(192, 132, 252, 0.1)',
                                        color: splitResult ? 'var(--success)' : '#a855f7',
                                        border: `1px solid ${splitResult ? 'rgba(52, 211, 153, 0.3)' : 'rgba(192, 132, 252, 0.3)'}`,
                                        borderRadius: '6px',
                                        fontSize: '0.85rem',
                                        fontWeight: 500,
                                        cursor: splittingSpec ? 'not-allowed' : 'pointer',
                                        opacity: splittingSpec ? 0.6 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem'
                                    }}
                                    title="Split this multi-test spec into individual test files for easier automation"
                                >
                                    {splittingSpec ? (
                                        <>
                                            <Loader2 size={16} className="spin" />
                                            Splitting...
                                        </>
                                    ) : splitResult ? (
                                        <>
                                            <CheckCircle2 size={16} />
                                            Split Complete
                                        </>
                                    ) : (
                                        <>
                                            <Scissors size={16} />
                                            Split into Individual Tests
                                        </>
                                    )}
                                </button>

                                {/* Right side - Copy and Download */}
                                <div style={{ display: 'flex', gap: '0.75rem' }}>
                                    <button
                                        onClick={() => {
                                            navigator.clipboard.writeText(generatedSpec.spec_content);
                                            setWorkspaceStatus('Spec copied to clipboard.');
                                            toast.success('Spec copied to clipboard');
                                        }}
                                        style={{
                                            padding: '0.6rem 1rem',
                                            background: 'transparent',
                                            color: 'var(--text)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '6px',
                                            fontSize: '0.85rem',
                                            fontWeight: 500,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Copy
                                    </button>
                                    <button
                                        onClick={() => downloadSpec()}
                                        style={{
                                            padding: '0.6rem 1rem',
                                            background: 'var(--primary)',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: '6px',
                                            fontSize: '0.85rem',
                                            fontWeight: 500,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        <Download size={16} />
                                        Download
                                    </button>
                                </div>
                            </div>
                        </DialogContent>
                    )}
                </Dialog>

            {workspaceView === 'library' && (
                <div className="card" style={{ padding: '1rem', display: 'grid', gap: '1rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                        <div>
                            <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Agent Library</h2>
                            <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Create, edit, archive, and choose reusable custom agents.</p>
                        </div>
                        <Button type="button" onClick={resetDefinitionForm}>
                            <Plus size={14} /> Create Agent
                        </Button>
                    </div>
                    {returnToAfterSave && selectedDefinition && (
                        <div style={{ padding: '0.85rem', border: '1px solid var(--primary)', borderRadius: '8px', background: 'var(--primary-glow)', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 700 }}>Saved {selectedDefinition.name}. It is ready for workflow use.</span>
                            <Link href={returnToAfterSave} style={{ color: 'var(--primary)', fontWeight: 800, textDecoration: 'none' }}>
                                {returnToAfterSave.includes('workflow') ? 'Return to Workflow' : 'Use in Workflow'}
                            </Link>
                        </div>
                    )}
                    {agentDefinitions.length === 0 ? (
                        <div style={{ padding: '2rem', textAlign: 'center', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-secondary)' }}>
                            No custom agents yet.
                        </div>
                    ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem' }}>
                            {agentDefinitions.map(definition => (
                                <div key={definition.id} style={{ padding: '0.95rem', border: selectedDefinitionId === definition.id ? '1px solid var(--primary)' : '1px solid var(--border)', borderRadius: '8px', background: selectedDefinitionId === definition.id ? 'var(--primary-glow)' : 'var(--surface-hover)', display: 'grid', gap: '0.65rem' }}>
                                    <div>
                                        <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 800, overflowWrap: 'anywhere' }}>{definition.name}</h3>
                                        <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45 }}>{definition.description || 'No description provided.'}</p>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                                        <Badge variant="secondary">{definition.tool_ids.length} tools</Badge>
                                        <Badge variant="secondary">{definition.runtime === 'hermes' ? 'Hermes' : 'Claude SDK'}</Badge>
                                        <Badge variant="secondary">{Math.ceil((definition.timeout_seconds || 1800) / 60)}m</Badge>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        <Button type="button" size="sm" onClick={() => { selectDefinition(definition.id); selectAgentMode('custom'); selectWorkspaceView('run'); }}>
                                            <Play size={13} /> Run Agent
                                        </Button>
                                        <Button type="button" size="sm" variant="outline" onClick={() => { selectDefinition(definition.id); editDefinition(definition); }}>
                                            <Settings size={13} /> Edit
                                        </Button>
                                        <Button type="button" size="sm" variant="ghost" onClick={() => setArchiveCandidate(definition)} style={{ color: 'var(--danger)' }}>
                                            <Archive size={13} /> Archive
                                        </Button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {workspaceView === 'reports' && (
                <ReportsSearchWorkspace
                    query={reportSearchQuery}
                    onQueryChange={updateReportSearchQuery}
                    type={reportSearchType}
                    onTypeChange={updateReportSearchType}
                    severity={reportSearchSeverity}
                    onSeverityChange={updateReportSearchSeverity}
                    loading={reportSearchLoading}
                    results={reportSearchResults}
                    onRefresh={fetchReportSearch}
                />
            )}

            {workspaceView === 'queue' && (
                <QueueStatusPanel queue={queueStatus} loading={queueLoading} error={queueError} onRefresh={fetchQueueStatus} />
            )}
        </PageLayout>
    );
}
