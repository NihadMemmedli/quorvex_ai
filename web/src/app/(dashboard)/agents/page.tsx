'use client';
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
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
import Pencil from 'lucide-react/dist/esm/icons/pencil';
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
import { StatusBadge } from '@/components/shared/StatusBadge';
import type { BrowserAuthSession } from '@/lib/browser-auth-sessions';
import {
    browserAuthSessionLabel,
    fetchProjectBrowserAuthSessions,
    isBrowserAuthSessionSelectable,
} from '@/lib/browser-auth-sessions';
import {
    applyAgentWorkspaceQueryPatch,
    parseAgentWorkspaceQuery,
    validateAgentRunInput,
    type AgentHistoryStatusFilter,
    type AgentHistoryTypeFilter,
    type AgentTraceTab,
    type AgentWorkspaceMode,
    type AgentWorkspaceView,
    type ReportReviewFilter,
    type ReportSpecItemType,
    type ReportSearchTypeFilter,
} from './agents-workspace-state';

const LiveBrowserView = dynamic<any>(() => import('@/components/LiveBrowserView').then(mod => mod.LiveBrowserView), { ssr: false });
const TestDataPicker = dynamic<any>(() => import('@/components/TestDataPicker').then(mod => mod.TestDataPicker), { ssr: false });

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

interface AgentHistoryCounts {
    status: Record<AgentHistoryStatusFilter, number>;
    type: Record<AgentHistoryTypeFilter, number>;
}

interface AgentRunHistoryResponse {
    items: AgentRun[];
    total: number;
    counts: AgentHistoryCounts;
    next_cursor?: string | null;
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
    run_id?: string;
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

const TOOL_RISK_PILL_STYLES: Record<AgentTool['risk'], { background: string; borderColor: string; color: string }> = {
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

function defaultDefinitionForm(runtime: string) {
    return {
        id: '',
        name: '',
        description: '',
        system_prompt: 'You are a focused QA automation agent. Use the selected tools to inspect the target, report findings clearly, and avoid actions outside the requested task.',
        runtime,
        timeout_seconds: 1800,
        tool_ids: ['read_file', 'list_files', 'browser_navigate', 'browser_snapshot', 'browser_network', 'browser_console', 'browser_screenshot'],
        test_data_refs: '',
    };
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
type ReportEditableItemType = 'finding' | 'test_idea' | 'requirement';
type AgentActionIntent =
    | { type: 'none' }
    | { type: 'createAgent' }
    | { type: 'reviewReportSpec'; runId: string; itemId: string; itemType: ReportSpecItemType };

interface FlowModalData {
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

const REPORT_PRIORITY_OPTIONS = ['critical', 'high', 'medium', 'low'] as const;
const REPORT_SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low', 'info'] as const;
const REPORT_SELECT_EMPTY_VALUE = '__empty__';

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

type ReportEditTarget =
    | { type: 'overview'; runId: string }
    | { type: ReportEditableItemType; runId: string; itemId: string };

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

function reportSearchResultTab(type: AgentReportSearchItem['type']): CustomResultTab {
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

function reportSearchResultHref(result: AgentReportSearchItem) {
    const params = new URLSearchParams({
        runId: result.run_id,
        view: 'run',
        resultTab: reportSearchResultTab(result.type),
    });
    const itemId = result.item?.id != null ? String(result.item.id) : '';

    if ((result.type === 'finding' || result.type === 'test_idea') && itemId) {
        params.set('specItemId', itemId);
        params.set('specItemType', result.type);
    }

    return `/agents?${params.toString()}`;
}

function formatToolName(toolName?: string) {
    if (!toolName) return 'Waiting for first tool';
    const short = toolName.includes('__') ? toolName.split('__').pop() || toolName : toolName;
    return short.replace(/^browser_/, '').replace(/_/g, ' ');
}

function customAgentCurrentActivity(progress: any = {}) {
    if (progress.current_tool_label || progress.last_tool_label || progress.current_tool || progress.last_tool) {
        return progress.current_tool_label || progress.last_tool_label || formatToolName(progress.current_tool || progress.last_tool);
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

const LIVE_AGENT_STATUSES = new Set(['running', 'pending', 'queued', 'in_progress', 'waiting', 'paused']);
const TERMINAL_AGENT_STATUSES = new Set(['completed', 'completed_partial', 'failed', 'cancelled', 'canceled', 'timeout']);

function isAgentRunTerminal(status?: string) {
    return TERMINAL_AGENT_STATUSES.has(String(status || '').toLowerCase());
}

function agentStatusTone(status?: string) {
    if (status === 'completed') return { bg: 'var(--success-muted)', color: 'var(--success)' };
    if (status === 'completed_partial') return { bg: 'var(--warning-muted)', color: 'var(--warning)' };
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

function markAgentsAction(payload: Record<string, unknown>) {
    if (typeof window === 'undefined' || process.env.NODE_ENV === 'production') return;
    (window as typeof window & { __agentsLastAction?: Record<string, unknown> }).__agentsLastAction = payload;
}

function reportItemToFlow(item: ReportFinding | ReportTestIdea, kind: ReportSpecItemType, run: AgentRun): FlowModalData {
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

function linesToText(value?: string[]) {
    return Array.isArray(value) ? value.join('\n') : '';
}

function textToLines(value?: string) {
    return (value || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
}

function normalizeReportPatchResponse(data: any): AgentRun | null {
    if (data?.run?.id) return data.run as AgentRun;
    if (data?.id) return data as AgentRun;
    return null;
}

function reportEditDialogTitle(target: ReportEditTarget | null) {
    if (!target) return 'Edit Report Summary';
    if (target.type === 'overview') return 'Edit Report Summary';
    if (target.type === 'finding') return `Edit finding ${target.itemId}`;
    if (target.type === 'test_idea') return `Edit test idea ${target.itemId}`;
    return `Edit requirement ${target.itemId}`;
}

function findReportSpecItem(run: AgentRun | null, itemId: string, itemType: ReportSpecItemType) {
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

function CustomAgentReportView({
    run,
    activeTab,
    onTabChange,
    onAskAssistant,
    onCreateSpecFromReport,
    onEditOverview,
    onEditReportItem,
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
    onEditOverview: (report: StructuredAgentReport) => void;
    onEditReportItem: (item: ReportFinding | ReportTestIdea | ReportRequirement, kind: ReportEditableItemType) => void;
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
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <button
                            type="button"
                            onClick={() => onEditOverview(report)}
                            style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.45rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}
                        >
                            <Pencil size={14} /> Edit Report Summary
                        </button>
                        <button
                            type="button"
                            onClick={() => onAskAssistant(basePrompt)}
                            style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.45rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}
                        >
                            <MessageSquare size={14} /> Ask Assistant
                        </button>
                    </div>
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
                                <ReportActionButton onClick={() => onEditReportItem(finding, 'finding')} label={`Edit finding ${finding.id}`} icon={Pencil} />
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
                                <ReportActionButton onClick={() => onEditReportItem(idea, 'test_idea')} label={`Edit test idea ${idea.id}`} icon={Pencil} />
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
                                    <ReportActionButton
                                        onClick={() => onEditReportItem(requirement, 'requirement')}
                                        label={`Edit requirement ${requirement.id}`}
                                        icon={Pencil}
                                        disabled={imported}
                                    />
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

function ReportActionButton({ onClick, label, icon: Icon, disabled = false }: { onClick: () => void | Promise<void>; label: string; icon: any; disabled?: boolean }) {
    const handleClick = async () => {
        try {
            await onClick();
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Action failed. Please try again.';
            toast.error(message);
        }
    };

    return (
        <button
            type="button"
            onClick={handleClick}
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
    const traceSpans = useMemo(() => trace?.spans || [], [trace?.spans]);
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
    onCleanStaleTasks,
    cleaningStaleTasks,
}: {
    queue: AgentQueueStatus | null;
    loading: boolean;
    error: string | null;
    onRefresh: () => void;
    onCleanStaleTasks: () => Promise<void>;
    cleaningStaleTasks: boolean;
}) {
    const stale = queue?.stale_running ?? 0;
    const orphaned = queue?.orphaned_tasks ?? 0;
    const hasCleanupWork = stale > 0 || orphaned > 0;
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
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {hasCleanupWork && (
                        <Button type="button" variant="outline" onClick={onCleanStaleTasks} disabled={loading || cleaningStaleTasks}>
                            {cleaningStaleTasks ? <Loader2 className="spin" size={14} /> : <Wrench size={14} />} Clean stale tasks
                        </Button>
                    )}
                    <Button type="button" variant="outline" onClick={onRefresh} disabled={loading}>
                        {loading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />} Refresh
                    </Button>
                </div>
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
                                <Link href={reportSearchResultHref(result)} style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.82rem' }}>
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
    const { currentProject, isLoading: projectLoading } = useProject();
    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const searchParamsString = searchParams.toString();
    const [workspaceView, setWorkspaceView] = useState<AgentWorkspaceView>('run');
    // Basic config
    const [url, setUrl] = useState('');
    const [instructions, setInstructions] = useState('');

    // Enhanced exploratory config
    const [timeLimitMinutes] = useState(15);
    const [authType, setAuthType] = useState<AuthType>('none');
    const [sessionId, setSessionId] = useState('');
    const [testDataRefs, setTestDataRefs] = useState('');

    // History & results
    const [history, setHistory] = useState<AgentRun[]>([]);
    const [historyTotal, setHistoryTotal] = useState(0);
    const [historyCounts, setHistoryCounts] = useState<AgentHistoryCounts>({
        status: { all: 0, active: 0, completed: 0, failed: 0, cancelled: 0, paused: 0 },
        type: { all: 0, exploratory: 0, custom: 0, writer: 0, spec_generation: 0 },
    });
    const [historyNextCursor, setHistoryNextCursor] = useState<string | null>(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState<string | null>(null);
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
    const [agentEvents, setAgentEvents] = useState<AgentRunEvent[]>([]);
    const [agentTrace, setAgentTrace] = useState<AgentTraceBundle | null>(null);
    const [traceLoading, setTraceLoading] = useState(false);
    const [traceSearch, setTraceSearch] = useState('');
    const [traceSpanType, setTraceSpanType] = useState('');
    const [specResult, setSpecResult] = useState<SpecResult | null>(null);
    const [historySearch, setHistorySearch] = useState('');
    const [debouncedHistorySearch, setDebouncedHistorySearch] = useState('');
    const [historyStatusFilter, setHistoryStatusFilter] = useState<AgentHistoryStatusFilter>('all');
    const [historyTypeFilter, setHistoryTypeFilter] = useState<AgentHistoryTypeFilter>('all');

    // UI state
    const [isStarting, setIsStarting] = useState(false);
    const [runControlPending, setRunControlPending] = useState<'pause' | 'resume' | 'cancel' | 'retry' | null>(null);
    const [isSynthesizing, setIsSynthesizing] = useState(false);
    const [sessions, setSessions] = useState<BrowserAuthSession[]>([]);
    const [flowModalOpen, setFlowModalOpen] = useState(false);
    const [selectedFlow, setSelectedFlow] = useState<FlowModalData | null>(null);
    const [agentActionIntent, setAgentActionIntent] = useState<AgentActionIntent>({ type: 'none' });
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
    const [queueCleanupLoading, setQueueCleanupLoading] = useState(false);
    const [queueError, setQueueError] = useState<string | null>(null);
    const [runFormError, setRunFormError] = useState<string | null>(null);
    const [definitionFormError, setDefinitionFormError] = useState<string | null>(null);
    const [workspaceStatus, setWorkspaceStatus] = useState('');
    const [setupOpen, setSetupOpen] = useState(true);
    const [contextDataOpen, setContextDataOpen] = useState(false);
    const [runPlanDetailsOpen, setRunPlanDetailsOpen] = useState(false);
    const [openDefinitionMenuId, setOpenDefinitionMenuId] = useState<string | null>(null);
    const [archiveCandidate, setArchiveCandidate] = useState<AgentDefinition | null>(null);
    const [cancelRunDialogOpen, setCancelRunDialogOpen] = useState(false);
    const [returnToAfterSave, setReturnToAfterSave] = useState('');
    const [importingRequirementIds, setImportingRequirementIds] = useState<string[]>([]);
    const [reportImportError, setReportImportError] = useState<string | null>(null);
    const [reportEditTarget, setReportEditTarget] = useState<ReportEditTarget | null>(null);
    const [reportEditForm, setReportEditForm] = useState<Record<string, string>>({});
    const [reportEditError, setReportEditError] = useState<string | null>(null);
    const [savingReportEdit, setSavingReportEdit] = useState(false);
    const [agentRuntime, setAgentRuntime] = useState('claude_sdk');
    const [builderOpen, setBuilderOpen] = useState(false);
    const [savingDefinition, setSavingDefinition] = useState(false);
    const [definitionForm, setDefinitionForm] = useState(() => defaultDefinitionForm('claude_sdk'));
    const pollInterval = useRef<NodeJS.Timeout | null>(null);
    const agentEventSourceRef = useRef<EventSource | null>(null);
    const agentEventReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const historyAbortRef = useRef<AbortController | null>(null);
    const reportSearchAbortRef = useRef<AbortController | null>(null);
    const runDetailAbortRef = useRef<AbortController | null>(null);
    const historyRequestIdRef = useRef(0);
    const traceRequestIdRef = useRef(0);
    const toolCatalogLoadedProjectRef = useRef<string | null>(null);
    const definitionsLoadedProjectRef = useRef<string | null>(null);
    const agentEventsRef = useRef<AgentRunEvent[]>([]);
    const workspaceQueryRef = useRef(searchParamsString);
    const queryCreateOpenRef = useRef(false);
    const activeBrowserAuthSessions = useMemo(
        () => sessions.filter(isBrowserAuthSessionSelectable),
        [sessions]
    );
    const projectDefaultBrowserAuthSession = useMemo(
        () => activeBrowserAuthSessions.find(item => item.is_default),
        [activeBrowserAuthSessions]
    );

    const updateWorkspaceQuery = useCallback((patch: Parameters<typeof applyAgentWorkspaceQueryPatch>[1]) => {
        const nextParams = applyAgentWorkspaceQueryPatch(new URLSearchParams(workspaceQueryRef.current || searchParamsString), patch);
        const query = nextParams.toString();
        workspaceQueryRef.current = query;
        router.replace(`${pathname}${query ? `?${query}` : ''}`, { scroll: false });
    }, [pathname, router, searchParamsString]);

    const selectRun = useCallback((runId: string | null) => {
        setSelectedRunId(runId);
        updateWorkspaceQuery({ runId });
    }, [updateWorkspaceQuery]);

    const selectHistoryRun = useCallback((runId: string) => {
        setSelectedRunId(runId);
        setWorkspaceView('run');
        updateWorkspaceQuery({ runId, view: 'run' });
    }, [updateWorkspaceQuery]);

    const selectWorkspaceView = useCallback((view: AgentWorkspaceView) => {
        setWorkspaceView(view);
        updateWorkspaceQuery({ view });
    }, [updateWorkspaceQuery]);

    const selectAgentMode = useCallback((mode: AgentWorkspaceMode) => {
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
    }, []);

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
            setDefinitionForm(prev => prev.id ? prev : { ...prev, runtime });
        } catch (e) {
            console.error('Failed to fetch runtime settings', e);
        }
    };

    // Fetch history summaries (filtered and paged by the API).
    const fetchHistory = useCallback(async (options: { append?: boolean; cursor?: string | null } = {}) => {
        if (projectLoading) return;
        historyAbortRef.current?.abort();
        const controller = new AbortController();
        historyAbortRef.current = controller;
        const requestId = historyRequestIdRef.current + 1;
        historyRequestIdRef.current = requestId;
        setHistoryLoading(true);
        setHistoryError(null);
        try {
            const params = new URLSearchParams({ limit: '40' });
            if (currentProject?.id) params.set('project_id', currentProject.id);
            if (historyStatusFilter !== 'all') params.set('status', historyStatusFilter);
            if (historyTypeFilter !== 'all') params.set('agent_type', historyTypeFilter);
            if (debouncedHistorySearch.trim()) params.set('q', debouncedHistorySearch.trim());
            if (options.cursor) params.set('cursor', options.cursor);
            const res = await fetch(`${API_BASE}/api/agents/runs?${params}`, { signal: controller.signal });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (controller.signal.aborted || historyRequestIdRef.current !== requestId) return;
            const payload: AgentRunHistoryResponse = Array.isArray(data)
                ? {
                    items: data,
                    total: data.length,
                    counts: {
                        status: { all: data.length, active: 0, completed: 0, failed: 0, cancelled: 0, paused: 0 },
                        type: { all: data.length, exploratory: 0, custom: 0, writer: 0, spec_generation: 0 },
                    },
                    next_cursor: null,
                }
                : data;
            setHistory(prev => options.append ? [...prev, ...(payload.items || [])] : (payload.items || []));
            setHistoryTotal(Number(payload.total || 0));
            setHistoryCounts(payload.counts || {
                status: { all: 0, active: 0, completed: 0, failed: 0, cancelled: 0, paused: 0 },
                type: { all: 0, exploratory: 0, custom: 0, writer: 0, spec_generation: 0 },
            });
            setHistoryNextCursor(payload.next_cursor || null);
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            const message = e instanceof Error ? e.message : 'Failed to fetch history';
            setHistoryError(message);
            console.error("Failed to fetch history", e);
        } finally {
            if (historyRequestIdRef.current === requestId) {
                setHistoryLoading(false);
            }
        }
    }, [currentProject?.id, debouncedHistorySearch, historyStatusFilter, historyTypeFilter, projectLoading]);

    const loadMoreHistory = useCallback(() => {
        if (!historyNextCursor || historyLoading) return;
        void fetchHistory({ append: true, cursor: historyNextCursor });
    }, [fetchHistory, historyLoading, historyNextCursor]);

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

    const fetchToolCatalog = useCallback(async () => {
        if (projectLoading) return;
        const projectKey = currentProject?.id || 'unscoped';
        if (toolCatalogLoadedProjectRef.current === projectKey && toolCatalog.length > 0) return;
        try {
            const res = await fetch(`${API_BASE}/api/agents/tools/catalog`);
            if (res.ok) {
                const data = await res.json();
                setToolCatalog(data.tools || []);
                toolCatalogLoadedProjectRef.current = projectKey;
            }
        } catch (e) { console.error("Failed to fetch agent tool catalog", e); }
    }, [currentProject?.id, projectLoading, toolCatalog.length]);

    const fetchAgentDefinitions = useCallback(async () => {
        if (projectLoading) return;
        const projectKey = currentProject?.id || 'unscoped';
        if (definitionsLoadedProjectRef.current === projectKey && agentDefinitions.length > 0) return;
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/api/agents/definitions${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setAgentDefinitions(data || []);
                definitionsLoadedProjectRef.current = projectKey;
                if (!selectedDefinitionId && data?.length) {
                    setSelectedDefinitionId(data[0].id);
                }
            }
        } catch (e) { console.error("Failed to fetch agent definitions", e); }
    }, [agentDefinitions.length, currentProject?.id, projectLoading, selectedDefinitionId]);

    const fetchAgentDefinitionsFresh = useCallback(async () => {
        definitionsLoadedProjectRef.current = null;
        await fetchAgentDefinitions();
    }, [fetchAgentDefinitions]);

    const ensureAgentLibraryData = useCallback(async () => {
        await Promise.all([fetchToolCatalog(), fetchAgentDefinitions()]);
    }, [fetchAgentDefinitions, fetchToolCatalog]);

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

    const cleanStaleQueueTasks = async () => {
        setQueueCleanupLoading(true);
        try {
            const res = await fetch(`${API_BASE}/api/agents/queue-clean-stale`, { method: 'POST' });
            let data: Record<string, any> = {};
            try {
                data = await res.json();
            } catch {
                data = {};
            }
            if (!res.ok || data.status === 'error') {
                throw new Error(String(data.message || data.detail || `HTTP ${res.status}`));
            }
            const cleaned = Number(data.cleaned ?? 0);
            const cleanupDetails = [
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
            toast.success(cleaned > 0 ? `Cleaned ${cleaned} stale queue task${cleaned === 1 ? '' : 's'}${cleanupDetails ? ` (${cleanupDetails})` : ''}` : 'No stale queue tasks needed cleanup');
            await fetchQueueStatus();
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to clean stale queue tasks.';
            toast.error(message);
        } finally {
            setQueueCleanupLoading(false);
        }
    };

    const fetchReportSearch = async () => {
        if (projectLoading) return;
        reportSearchAbortRef.current?.abort();
        const controller = new AbortController();
        reportSearchAbortRef.current = controller;
        setReportSearchLoading(true);
        try {
            const params = new URLSearchParams({ limit: '50' });
            if (currentProject?.id) params.set('project_id', currentProject.id);
            if (reportSearchQuery.trim()) params.set('query', reportSearchQuery.trim());
            if (reportSearchType !== 'all') params.set('item_type', reportSearchType);
            if (reportSearchSeverity !== 'all') params.set('severity', reportSearchSeverity);
            const res = await fetch(`${API_BASE}/api/agents/reports/search?${params}`, { signal: controller.signal });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (controller.signal.aborted) return;
            setReportSearchResults(Array.isArray(data.items) ? data.items : []);
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            console.error('Failed to search agent reports', e);
            setReportSearchResults([]);
        } finally {
            if (!controller.signal.aborted) {
                setReportSearchLoading(false);
            }
        }
    };

    useEffect(() => {
        workspaceQueryRef.current = searchParamsString;
        const queryState = parseAgentWorkspaceQuery(new URLSearchParams(searchParamsString));
        setWorkspaceView(queryState.view);
        if (queryState.runId) setSelectedRunId(queryState.runId);
        if (queryState.definitionId) setSelectedDefinitionId(queryState.definitionId);
        setReturnToAfterSave(queryState.returnTo);
        if (queryState.create) {
            if (!queryCreateOpenRef.current) {
                setDefinitionForm(defaultDefinitionForm(agentRuntime));
                setDefinitionFormError(null);
            }
            queryCreateOpenRef.current = true;
            setAgentActionIntent({ type: 'createAgent' });
            setBuilderOpen(true);
        } else {
            queryCreateOpenRef.current = false;
        }
        if (queryState.runId && queryState.specItemId && queryState.specItemType) {
            setAgentActionIntent({
                type: 'reviewReportSpec',
                runId: queryState.runId,
                itemId: queryState.specItemId,
                itemType: queryState.specItemType,
            });
            setFlowModalOpen(true);
            setWorkspaceStatus(`Opening report item ${queryState.specItemId} for spec review.`);
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
        setDebouncedHistorySearch(queryState.q);
    }, [agentRuntime, searchParamsString]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebouncedHistorySearch(historySearch);
            updateWorkspaceQuery({ q: historySearch });
        }, 300);
        return () => window.clearTimeout(timer);
    }, [historySearch, updateWorkspaceQuery]);

    useEffect(() => {
        if (projectLoading) return;
        toolCatalogLoadedProjectRef.current = null;
        definitionsLoadedProjectRef.current = null;
        setToolCatalog([]);
        setAgentDefinitions([]);
        setSelectedDefinitionId('');
        setSessions([]);
        setSessionId('');
    }, [currentProject?.id, projectLoading]);

    useEffect(() => {
        if (projectLoading) return;
        void fetchRuntimeSettings();
    }, [currentProject?.id, projectLoading]);

    useEffect(() => {
        if (projectLoading) return;
        void fetchHistory();
    }, [fetchHistory, projectLoading]);

    useEffect(() => {
        if (projectLoading) return;
        if (!['run', 'library'].includes(workspaceView) && !builderOpen) return;
        void ensureAgentLibraryData();
    }, [builderOpen, ensureAgentLibraryData, projectLoading, workspaceView]);

    useEffect(() => {
        if (projectLoading) return;
        const needsSessions =
            workspaceView === 'run' ||
            flowModalOpen ||
            builderOpen;
        if (!needsSessions) return;
        void fetchSessions();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [builderOpen, currentProject?.id, flowModalOpen, projectLoading, workspaceView]);

    useEffect(() => {
        return () => {
            if (pollInterval.current) clearInterval(pollInterval.current);
            agentEventSourceRef.current?.close();
            historyAbortRef.current?.abort();
            reportSearchAbortRef.current?.abort();
            runDetailAbortRef.current?.abort();
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
        }
    }, []);

    useEffect(() => {
        if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('resultTab')) return;
        setCustomResultTab('overview');
    }, [activeRun?.id]);

    useEffect(() => {
        if (projectLoading || workspaceView !== 'reports') return;
        const timer = window.setTimeout(() => {
            void fetchReportSearch();
        }, 200);
        return () => window.clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [workspaceView, currentProject?.id, reportSearchQuery, reportSearchType, reportSearchSeverity, projectLoading]);

    useEffect(() => {
        if (projectLoading || workspaceView !== 'queue') return;
        void fetchQueueStatus();
        const interval = window.setInterval(() => void fetchQueueStatus(), 5000);
        return () => window.clearInterval(interval);
    }, [workspaceView, projectLoading]);

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
        runDetailAbortRef.current?.abort();
        const controller = new AbortController();
        runDetailAbortRef.current = controller;
        try {
            const projectQuery = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}${projectQuery}`, { signal: controller.signal });
            if (res.ok) {
                const data = await res.json();
                if (controller.signal.aborted) return;
                setActiveRun(prev => {
                    const wasActive = prev?.id === id && !isAgentRunTerminal(prev.status);
                    const isTerminal = isAgentRunTerminal(data.status);
                    if (wasActive && isTerminal) {
                        void fetchHistory();
                        void fetchAgentEvents(id);
                        void fetchAgentTrace(id);
                    }
                    return data;
                });
            }
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
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
        const requestId = traceRequestIdRef.current + 1;
        traceRequestIdRef.current = requestId;
        setTraceLoading(true);
        try {
            const projectQuery = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}/trace${projectQuery}`);
            if (res.ok) {
                const data = await res.json();
                if (traceRequestIdRef.current === requestId) {
                    setAgentTrace(data);
                }
            }
        } catch (e) {
            console.error("Failed to fetch agent trace", e);
        } finally {
            if (traceRequestIdRef.current === requestId) {
                setTraceLoading(false);
            }
        }
    };

    const mergeProgressFromAgentEvent = (event: AgentRunEvent) => {
        if (!event || !['tool_call', 'browser_action'].includes(event.event_type)) return;
        const payload = event.payload || {};
        const eventRunId = event.run_id || selectedRunId;
        const toolName = payload.tool_name || payload.current_tool || payload.last_tool;
        const toolLabel = payload.tool_label || payload.current_tool_label || payload.last_tool_label || payload.short_name;
        const events = [...agentEventsRef.current, event];
        const uniqueEvents = [...new Map(events.map(item => [item.sequence, item])).values()];
        const toolEventCount = uniqueEvents.filter(item => ['tool_call', 'browser_action'].includes(item.event_type)).length;
        const browserEventCount = uniqueEvents.filter(item => item.event_type === 'browser_action').length;

        setActiveRun(prev => {
            if (!prev || prev.id !== eventRunId) return prev;
            const currentProgress = prev.progress || {};
            return {
                ...prev,
                progress: {
                    ...currentProgress,
                    phase: currentProgress.phase || 'tool_use',
                    last_tool: toolName || currentProgress.last_tool,
                    current_tool: toolName || currentProgress.current_tool,
                    last_tool_label: toolLabel || currentProgress.last_tool_label,
                    current_tool_label: toolLabel || currentProgress.current_tool_label,
                    tool_calls: Math.max(Number(currentProgress.tool_calls ?? 0), toolEventCount),
                    browser_tool_calls: Math.max(Number(currentProgress.browser_tool_calls ?? currentProgress.interactions ?? 0), browserEventCount),
                    updated_at: event.created_at || currentProgress.updated_at,
                },
            };
        });
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
                setAgentActionIntent({ type: 'none' });
                updateWorkspaceQuery({ specItemId: '', specItemType: '' });
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
                setWorkspaceStatus('Test spec generated.');
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
            setWorkspaceStatus(`Spec generation failed: ${message || 'Unknown error'}`);
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
        markAgentsAction({ action: 'reviewReportSpec', runId: activeRun?.id, itemId: item?.id, itemType: kind, phase: 'click' });
        if (!activeRun?.id) {
            const message = 'Select a completed custom agent run before creating a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            setAgentActionIntent({ type: 'none' });
            toast.error(message);
            markAgentsAction({ action: 'reviewReportSpec', runId: null, itemId: item?.id, itemType: kind, phase: 'missing-run' });
            return;
        }
        if (!item?.id) {
            const message = 'This report item is missing an id and cannot be used to create a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            setAgentActionIntent({ type: 'none' });
            toast.error(message);
            markAgentsAction({ action: 'reviewReportSpec', runId: activeRun.id, itemId: null, itemType: kind, phase: 'missing-item-id' });
            return;
        }
        const defaultSelection = defaultReportSpecBrowserAuthSelection(sessions, sessionId);
        setReportSpecAuthMode(defaultSelection.mode);
        setReportSpecAuthSessionId(defaultSelection.sessionId);
        setSelectedFlow(null);
        setAgentActionIntent({ type: 'reviewReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind });
        setFlowModalOpen(true);
        setWorkspaceStatus(`Reviewing ${kind === 'finding' ? 'finding' : 'test idea'} ${item.id} for spec generation.`);
        updateWorkspaceQuery({ runId: activeRun.id, specItemId: item.id, specItemType: kind });
        setGeneratingSpec(false);
        setSplitResult(null);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        markAgentsAction({ action: 'reviewReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'modal-open' });
    };

    const closeFlowModal = () => {
        setFlowModalOpen(false);
        setGeneratingSpec(false);
        setFlowSpecError(null);
        setSelectedFlow(null);
        if (agentActionIntent.type === 'reviewReportSpec') {
            setAgentActionIntent({ type: 'none' });
            updateWorkspaceQuery({ specItemId: '', specItemType: '' });
        }
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        markAgentsAction({ action: 'flowModal', phase: 'closed' });
    };

    const createSpecFromReportItem = async (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
        markAgentsAction({ action: 'generateReportSpec', runId: activeRun?.id, itemId: item?.id, itemType: kind, phase: 'click' });
        if (!activeRun?.id) {
            const message = 'Select a completed custom agent run before generating a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            toast.error(message);
            return;
        }
        if (!item?.id) {
            const message = 'This report item is missing an id and cannot be used to generate a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            toast.error(message);
            return;
        }
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
        setWorkspaceStatus(`Generating test spec from ${kind === 'finding' ? 'finding' : 'test idea'} ${item.id}.`);
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
                markAgentsAction({ action: 'generateReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'polling-started', jobId: data.job_id });
                return;
            }
            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            setFlowSpecError(message);
            setWorkspaceStatus(`Spec generation failed: ${message}`);
            setGeneratingSpec(false);
            markAgentsAction({ action: 'generateReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'failed', message });
        }
    };

    const updateRunFromReportPatch = (updatedRun: AgentRun) => {
        setActiveRun(updatedRun);
        setHistory(prev => prev.map(run => run.id === updatedRun.id ? updatedRun : run));
    };

    const openReportOverviewEdit = (report: StructuredAgentReport) => {
        if (!activeRun?.id) return;
        setReportEditTarget({ type: 'overview', runId: activeRun.id });
        setReportEditForm({
            summary: report.summary || '',
            scope: report.scope || '',
        });
        setReportEditError(null);
    };

    const openReportItemEdit = (item: ReportFinding | ReportTestIdea | ReportRequirement, kind: ReportEditableItemType) => {
        if (!activeRun?.id) return;
        setReportEditTarget({ type: kind, runId: activeRun.id, itemId: item.id });
        if (kind === 'finding') {
            const finding = item as ReportFinding;
            setReportEditForm({
                title: finding.title || '',
                severity: finding.severity || '',
                page: finding.page || '',
                description: finding.description || '',
                evidence: finding.evidence || '',
                suggested_action: finding.suggested_action || '',
            });
        } else if (kind === 'test_idea') {
            const idea = item as ReportTestIdea;
            setReportEditForm({
                title: idea.title || '',
                priority: idea.priority || '',
                page: idea.page || '',
                steps: linesToText(idea.steps),
                expected: idea.expected || '',
                source_finding_id: idea.source_finding_id || '',
            });
        } else {
            const requirement = item as ReportRequirement;
            setReportEditForm({
                title: requirement.title || '',
                description: requirement.description || '',
                category: requirement.category || '',
                priority: requirement.priority || '',
                acceptance_criteria: linesToText(requirement.acceptance_criteria),
                page: requirement.page || '',
                evidence: requirement.evidence || '',
                confidence: requirement.confidence === undefined || requirement.confidence === null ? '' : String(requirement.confidence),
            });
        }
        setReportEditError(null);
    };

    const closeReportEditDialog = () => {
        if (savingReportEdit) return;
        setReportEditTarget(null);
        setReportEditForm({});
        setReportEditError(null);
    };

    const updateReportEditField = (field: string, value: string) => {
        setReportEditForm(prev => ({ ...prev, [field]: value }));
    };

    const reportEditFieldId = (field: string) => `agents-report-edit-${reportEditTarget?.type || 'report'}-${field}`;

    const reportEditKicker = () => {
        if (!reportEditTarget || reportEditTarget.type === 'overview') return 'Report summary';
        if (reportEditTarget.type === 'finding') return `Finding ${reportEditTarget.itemId}`;
        if (reportEditTarget.type === 'test_idea') return `Test idea ${reportEditTarget.itemId}`;
        return `Requirement ${reportEditTarget.itemId}`;
    };

    const reportEditSelectValue = (field: string, options: readonly string[]) => {
        const value = (reportEditForm[field] || '').trim();
        if (!value) return REPORT_SELECT_EMPTY_VALUE;
        const normalized = value.toLowerCase();
        return options.includes(normalized) ? normalized : value;
    };

    const renderReportTextField = (label: string, field: string, type = 'text') => {
        const id = reportEditFieldId(field);
        return (
            <div className="agents-report-edit-field">
                <Label htmlFor={id}>{label}</Label>
                <Input
                    id={id}
                    type={type}
                    className="agents-report-edit-input"
                    value={reportEditForm[field] || ''}
                    onChange={event => updateReportEditField(field, event.target.value)}
                />
            </div>
        );
    };

    const renderReportTextareaField = (label: string, field: string, rows: number, size: 'md' | 'lg' = 'md') => {
        const id = reportEditFieldId(field);
        return (
            <div className="agents-report-edit-field">
                <Label htmlFor={id}>{label}</Label>
                <textarea
                    id={id}
                    className="agents-report-edit-textarea"
                    data-size={size}
                    value={reportEditForm[field] || ''}
                    onChange={event => updateReportEditField(field, event.target.value)}
                    rows={rows}
                />
            </div>
        );
    };

    const renderReportSelectField = (label: string, field: 'priority' | 'severity', options: readonly string[]) => {
        const id = reportEditFieldId(field);
        const rawValue = (reportEditForm[field] || '').trim();
        const normalizedValue = rawValue.toLowerCase();
        const hasKnownValue = options.includes(normalizedValue);
        const selectValue = reportEditSelectValue(field, options);
        return (
            <div className="agents-report-edit-field">
                <Label htmlFor={id}>{label}</Label>
                <Select
                    value={selectValue}
                    onValueChange={value => updateReportEditField(field, value === REPORT_SELECT_EMPTY_VALUE ? '' : value)}
                >
                    <SelectTrigger id={id} className="agents-report-edit-select-trigger">
                        <SelectValue placeholder={`Select ${label.toLowerCase()}`} />
                    </SelectTrigger>
                    <SelectContent className="agents-report-edit-select-content" sideOffset={8}>
                        <SelectItem value={REPORT_SELECT_EMPTY_VALUE}>Not set</SelectItem>
                        {options.map(option => (
                            <SelectItem key={option} value={option}>{option.charAt(0).toUpperCase() + option.slice(1)}</SelectItem>
                        ))}
                        {rawValue && !hasKnownValue && (
                            <SelectItem value={rawValue}>{rawValue}</SelectItem>
                        )}
                    </SelectContent>
                </Select>
            </div>
        );
    };

    const reportEditPayload = () => {
        if (!reportEditTarget) return {};
        if (reportEditTarget.type === 'overview') {
            return {
                summary: reportEditForm.summary || '',
                scope: reportEditForm.scope || '',
            };
        }
        if (reportEditTarget.type === 'finding') {
            return {
                title: reportEditForm.title || '',
                severity: reportEditForm.severity || '',
                page: reportEditForm.page || '',
                description: reportEditForm.description || '',
                evidence: reportEditForm.evidence || '',
                suggested_action: reportEditForm.suggested_action || '',
            };
        }
        if (reportEditTarget.type === 'test_idea') {
            return {
                title: reportEditForm.title || '',
                priority: reportEditForm.priority || '',
                page: reportEditForm.page || '',
                steps: textToLines(reportEditForm.steps),
                expected: reportEditForm.expected || '',
                source_finding_id: reportEditForm.source_finding_id || '',
            };
        }
        return {
            title: reportEditForm.title || '',
            description: reportEditForm.description || '',
            category: reportEditForm.category || '',
            priority: reportEditForm.priority || '',
            acceptance_criteria: textToLines(reportEditForm.acceptance_criteria),
            page: reportEditForm.page || '',
            evidence: reportEditForm.evidence || '',
            confidence: reportEditForm.confidence || '',
        };
    };

    const saveReportEdit = async () => {
        if (!reportEditTarget || !activeRun?.id) return;
        setSavingReportEdit(true);
        setReportEditError(null);
        try {
            const params = new URLSearchParams();
            if (currentProject?.id) params.set('project_id', currentProject.id);
            let url = `${API_BASE}/api/agents/runs/${reportEditTarget.runId}/report`;
            if (reportEditTarget.type !== 'overview') {
                params.set('item_type', reportEditTarget.type);
                url = `${API_BASE}/api/agents/runs/${reportEditTarget.runId}/report-items/${encodeURIComponent(reportEditTarget.itemId)}`;
            }
            const query = params.toString() ? `?${params}` : '';
            const res = await fetch(`${url}${query}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reportEditTarget.type === 'overview' ? reportEditPayload() : { patch: reportEditPayload() }),
            });
            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message;
                throw new Error(detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            const updatedRun = normalizeReportPatchResponse(data);
            if (!updatedRun) throw new Error('The server did not return the updated run.');
            updateRunFromReportPatch(updatedRun);
            setReportEditTarget(null);
            setReportEditForm({});
            setWorkspaceStatus('Report content saved.');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to save report content.';
            setReportEditError(message);
            setWorkspaceStatus(`Report edit failed: ${message}`);
        } finally {
            setSavingReportEdit(false);
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

        if (pollInterval.current) clearInterval(pollInterval.current);
        pollInterval.current = null;
        runDetailAbortRef.current?.abort();

        fetchRun(selectedRunId);
        fetchAgentEvents(selectedRunId);
        fetchSpecs(selectedRunId);

        return () => {
            if (pollInterval.current) clearInterval(pollInterval.current);
            pollInterval.current = null;
            runDetailAbortRef.current?.abort();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedRunId, currentProject?.id]);

    useEffect(() => {
        if (!selectedRunId || !activeRun || !LIVE_AGENT_STATUSES.has(activeRun.status)) return;
        let cancelled = false;
        let attempts = 0;

        const backfillEvents = async () => {
            const lastSequence = agentEventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            await fetchAgentEvents(selectedRunId, lastSequence);
        };

        const scheduleReconnect = () => {
            if (cancelled) return;
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
            attempts += 1;
            const delay = Math.min(15000, 750 * Math.pow(2, Math.min(attempts, 5)));
            agentEventReconnectTimerRef.current = setTimeout(async () => {
                agentEventReconnectTimerRef.current = null;
                await backfillEvents();
                await fetchRun(selectedRunId);
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
                    mergeProgressFromAgentEvent(data);
                } catch {
                    source.close();
                    agentEventSourceRef.current = null;
                    scheduleReconnect();
                }
            };
            source.addEventListener('complete', () => {
                source.close();
                agentEventSourceRef.current = null;
                window.setTimeout(() => {
                    void fetchRun(selectedRunId);
                    void fetchAgentTrace(selectedRunId);
                    void fetchHistory();
                }, 500);
            });
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

    useEffect(() => {
        if (!selectedRunId || !activeRun) return;
        if (traceTab === 'timeline' && !isAgentRunTerminal(activeRun.status)) return;
        void fetchAgentTrace(selectedRunId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedRunId, activeRun?.status, traceTab, currentProject?.id]);


    const definitionById = useMemo(() => new Map(agentDefinitions.map(definition => [definition.id, definition])), [agentDefinitions]);
    const selectedDefinition = useMemo(() => definitionById.get(selectedDefinitionId), [definitionById, selectedDefinitionId]);
    const toolsByCategory = useMemo(() => toolCatalog.reduce<Record<string, AgentTool[]>>((acc, tool) => {
        acc[tool.category] = acc[tool.category] || [];
        acc[tool.category].push(tool);
        return acc;
    }, {}), [toolCatalog]);
    const toolById = useMemo(() => new Map(toolCatalog.map(tool => [tool.id, tool])), [toolCatalog]);

    const resetDefinitionForm = () => {
        setDefinitionForm(defaultDefinitionForm(agentRuntime));
        setDefinitionFormError(null);
    };

    const openCreateAgentBuilder = () => {
        resetDefinitionForm();
        selectAgentMode('custom');
        setAgentActionIntent({ type: 'createAgent' });
        queryCreateOpenRef.current = true;
        setBuilderOpen(true);
        setWorkspaceStatus('Opening custom agent builder.');
        updateWorkspaceQuery({ agent: 'custom', create: true });
        markAgentsAction({ action: 'createAgent', phase: 'modal-open' });
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
        setDefinitionFormError(null);
        setBuilderOpen(true);
    };

    const closeCustomAgentBuilder = () => {
        setBuilderOpen(false);
        setDefinitionFormError(null);
        if (agentActionIntent.type === 'createAgent') {
            setAgentActionIntent({ type: 'none' });
        }
        queryCreateOpenRef.current = false;
        updateWorkspaceQuery({ create: false });
        markAgentsAction({ action: 'createAgent', phase: 'closed' });
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
            await fetchAgentDefinitionsFresh();
            selectDefinition(saved.id);
            selectAgentMode('custom');
            const nextView = returnToAfterSave || (isEdit && workspaceView === 'library') ? 'library' : 'run';
            setWorkspaceView(nextView);
            updateWorkspaceQuery({ create: false, view: nextView });
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
            await fetchAgentDefinitionsFresh();
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
            selectedAgent: 'custom',
            selectedDefinitionId,
            url,
            authType,
            sessionId,
            testData: '',
        });
        setRunFormError(validationError);
        if (validationError) {
            return;
        }

        setIsStarting(true);
        setWorkspaceStatus('Starting agent run...');
        try {
            const selectedBrowserAuthSessionId = authType === 'session' ? sessionId.trim() : '';
            const selectedBrowserAuthSession = selectedBrowserAuthSessionId
                ? sessions.find(session => session.id === selectedBrowserAuthSessionId)
                : undefined;
            if (selectedBrowserAuthSessionId && (!selectedBrowserAuthSession || !isBrowserAuthSessionSelectable(selectedBrowserAuthSession))) {
                setRunFormError('Select an active browser login session.');
                setIsStarting(false);
                return;
            }

            const testDataRefsList = testDataRefs ? testDataRefs.split(',').map(s => s.trim()).filter(Boolean) : [];

            const endpoint = `${API_BASE}/api/agents/definitions/${selectedDefinitionId}/runs`;
            const selectedRuntime = selectedDefinition?.runtime || agentRuntime;
            const body = {
                prompt: instructions || `Inspect ${url || 'the current application context'} and report useful QA findings.`,
                url: url || undefined,
                runtime: selectedRuntime,
                test_data_refs: testDataRefsList,
                config: {
                    browser_auth_session_id: selectedBrowserAuthSessionId || undefined,
                    test_data_refs: testDataRefsList.length > 0 ? testDataRefsList : undefined,
                },
                project_id: currentProject?.id,
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

    const retryAgentRun = async () => {
        if (!activeRun || !isAgentRunTerminal(activeRun.status)) return;
        setRunControlPending('retry');
        try {
            const projectQuery = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
            const res = await fetch(`${API_BASE}/api/agents/runs/${activeRun.id}/retry${projectQuery}`, {
                method: 'POST',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || 'Failed to retry agent run');
            }
            setActiveRun(data);
            await fetchHistory();
            selectRun(activeRun.id);
            setWorkspaceStatus('Retrying in same run using saved browser auth/session artifacts.');
            toast.success('Retrying in same run');
        } catch (e: any) {
            toast.error(e.message || 'Failed to retry agent run');
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

        if (!['completed', 'completed_partial'].includes(activeRun.status)) {
            toast.error("Please wait for the exploration to complete");
            return;
        }
        if (!explorerCanGenerateSpecs) {
            toast.error("This exploration has no evidence-backed flows to synthesize");
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

    const reportSpecReview = useMemo(() => {
        if (agentActionIntent.type !== 'reviewReportSpec') return null;
        if (activeRun?.id !== agentActionIntent.runId) return null;
        return findReportSpecItem(activeRun, agentActionIntent.itemId, agentActionIntent.itemType);
    }, [activeRun, agentActionIntent]);
    const activeFlow = agentActionIntent.type === 'reviewReportSpec'
        ? reportSpecReview?.flow || null
        : selectedFlow;
    const flowModalVisible = flowModalOpen && (Boolean(activeFlow) || agentActionIntent.type === 'reviewReportSpec');
    const missingReportSpecItemMessage = agentActionIntent.type === 'reviewReportSpec' && activeRun?.id === agentActionIntent.runId && activeRun.result && !reportSpecReview
        ? `Report item ${agentActionIntent.itemId} was not found in the refreshed agent report.`
        : '';

    useEffect(() => {
        if (!missingReportSpecItemMessage) return;
        setWorkspaceStatus(missingReportSpecItemMessage);
        setFlowSpecError(missingReportSpecItemMessage);
        markAgentsAction({
            action: 'reviewReportSpec',
            runId: agentActionIntent.type === 'reviewReportSpec' ? agentActionIntent.runId : null,
            itemId: agentActionIntent.type === 'reviewReportSpec' ? agentActionIntent.itemId : null,
            itemType: agentActionIntent.type === 'reviewReportSpec' ? agentActionIntent.itemType : null,
            phase: 'item-not-found',
        });
    }, [missingReportSpecItemMessage, agentActionIntent]);

    const flowSpecLatestImage = sortArtifactsByModifiedAt((flowSpecAgentRun?.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
    const flowSpecRunLive = Boolean(flowSpecAgentRun && LIVE_AGENT_STATUSES.has(flowSpecAgentRun.status));
    const flowSpecShowBrowser = Boolean(flowSpecAgentRunId && (generatingSpec || flowSpecRunLive || flowSpecLatestImage));
    const sourceRunBrowserAuthSessionId = runBrowserAuthSessionId(activeRun?.config);
    const inheritedBrowserAuthUnavailable = Boolean(
        activeFlow?.source_type === 'custom_report' &&
        sourceRunBrowserAuthSessionId &&
        !activeBrowserAuthSessions.some(item => item.id === sourceRunBrowserAuthSessionId)
    );
    const flowSpecBrowserAuthFailure = Boolean(
        flowSpecAgentRun?.progress?.browser_auth_failure ||
        flowSpecAgentRun?.result?.browser_auth_failure
    );
    const explorerResult = activeRun?.agent_type === 'exploratory' ? activeRun.result || {} : {};
    const explorerDiagnostics = explorerResult?.diagnostics || {};
    const explorerFinalizerDiagnostics = explorerDiagnostics?.finalizer || {};
    const explorerEventCounts = explorerResult?.event_counts || {};
    const explorerEvidenceEventCount = explorerDiagnostics.evidence_event_count
        ?? Object.values(explorerEventCounts).reduce((sum: number, value: any) => sum + Number(value || 0), 0);
    const explorerArtifactEvidence = explorerResult?.artifact_evidence && typeof explorerResult.artifact_evidence === 'object'
        ? explorerResult.artifact_evidence
        : {};
    const explorerArtifactEvidenceItems = Array.isArray(explorerArtifactEvidence.artifacts)
        ? explorerArtifactEvidence.artifacts
        : [];
    const explorerRunArtifacts = (activeRun?.artifacts || []).length > 0
        ? activeRun?.artifacts || []
        : explorerArtifactEvidenceItems;
    const explorerCapturedArtifacts = sortArtifactsByModifiedAt(explorerRunArtifacts as AgentArtifact[]);
    const explorerScreenshotArtifacts = sortArtifactsByModifiedAt(
        explorerCapturedArtifacts.filter((artifact: AgentArtifact) => artifact.type === 'image' || /\.(png|jpe?g)$/i.test(artifact.name || ''))
    );
    const explorerArtifactCount = explorerFinalizerDiagnostics.artifact_count
        ?? explorerDiagnostics.artifact_count
        ?? explorerArtifactEvidence.artifact_count
        ?? explorerCapturedArtifacts.length;
    const explorerScreenshotCount = explorerFinalizerDiagnostics.screenshot_count
        ?? explorerDiagnostics.screenshot_count
        ?? explorerArtifactEvidence.screenshot_count
        ?? explorerScreenshotArtifacts.length;
    const explorerFlowSummaries = Array.isArray(explorerResult?.discovered_flow_summaries)
        ? explorerResult.discovered_flow_summaries
        : [];
    const explorerUnsupportedFlowCandidates = Array.isArray(explorerResult?.unsupported_flow_candidates)
        ? explorerResult.unsupported_flow_candidates
        : [];
    const explorerStructuredFlowCount = explorerFlowSummaries.length;
    const explorerContractWarnings = Array.from(new Set([
        explorerResult?.contract_warning,
        ...(Array.isArray(explorerResult?.contract_warnings) ? explorerResult.contract_warnings : []),
    ].filter(Boolean).map((warning: any) => String(warning).trim()).filter(Boolean)));
    const explorerCanGenerateSpecs = explorerStructuredFlowCount > 0;
    const visibleHistory = history;
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
        return selectedDefinition.tool_ids.map(toolId => toolById.get(toolId)?.label || toolId);
    }, [selectedDefinition, toolById]);
    const visibleTestDataRefs = useMemo(() => {
        const explicitRefs = testDataRefs.split(',').map(ref => ref.trim()).filter(Boolean);
        if (explicitRefs.length > 0) return explicitRefs;
        return selectedDefinition?.test_data_refs || [];
    }, [selectedDefinition?.test_data_refs, testDataRefs]);
    const testDataRefsSummary = visibleTestDataRefs.length === 0
        ? 'No refs selected'
        : `${visibleTestDataRefs.length} ref${visibleTestDataRefs.length === 1 ? '' : 's'} selected`;
    const runPlanRows = useMemo(() => {
        const authMode = authType === 'session'
            ? (sessions.find(session => session.id === sessionId)?.name || sessionId || 'Session required')
            : 'No auth';
        const runtime = selectedDefinition?.runtime || agentRuntime;
        const timeout = `${Math.ceil((selectedDefinition?.timeout_seconds || 1800) / 60)} minutes`;
        return [
            ['Agent', selectedDefinition?.name || 'Custom agent required'],
            ['Runtime', 'Claude SDK'],
            ['Target', url.trim() || 'Optional'],
            ['Auth', authMode],
            ['Timeout', timeout],
            ['Tools', selectedDefinitionToolLabels.slice(0, 4).join(', ') || 'Select a saved agent'],
            ['Test data refs', testDataRefs.trim() || selectedDefinition?.test_data_refs?.join(', ') || 'None'],
            ['Queue', queueStatus ? `${queueStatus.active ?? 0} active, ${queueStatus.queued ?? 0} queued · ${queueStateLabel(queueStatus)}` : 'Not loaded'],
        ];
    }, [agentRuntime, authType, queueStatus, selectedDefinition, selectedDefinitionToolLabels, sessionId, sessions, testDataRefs, url]);
    const workspaceTabs: Array<{ key: AgentWorkspaceView; label: string; count?: number }> = [
        { key: 'run', label: 'Run' },
        { key: 'history', label: 'History', count: historyTotal || undefined },
        { key: 'library', label: 'Agent Library', count: agentDefinitions.length },
        { key: 'reports', label: 'Reports', count: reportSearchResults.length || undefined },
        { key: 'queue', label: 'Queue', count: (queueStatus?.active || 0) + (queueStatus?.queued || 0) || undefined },
    ];

    const renderExplorerCapturedEvidence = () => {
        if (explorerCapturedArtifacts.length === 0 && Number(explorerScreenshotCount || 0) === 0) return null;
        const previewImages = explorerScreenshotArtifacts.slice(0, 6);
        const otherArtifacts = explorerCapturedArtifacts
            .filter((artifact: AgentArtifact) => !previewImages.some((image: AgentArtifact) => image.path === artifact.path))
            .slice(0, 8);
        return (
            <div data-testid="explorer-captured-evidence" style={{ display: 'grid', gap: '0.75rem' }}>
                <div>
                    <h4 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.25rem', color: 'var(--text)' }}>Captured Evidence</h4>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                        Browser artifacts captured during the run are shown for review. They do not count as completed flows unless structured event IDs support a flow candidate.
                    </p>
                </div>
                {previewImages.length > 0 && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
                        {previewImages.map((artifact: AgentArtifact) => (
                            <a
                                key={artifact.path}
                                href={getArtifactUrl(artifact)}
                                target="_blank"
                                rel="noreferrer"
                                data-testid="explorer-captured-screenshot"
                                style={{ display: 'grid', gap: '0.45rem', padding: '0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', textDecoration: 'none' }}
                            >
                                <img
                                    src={getArtifactUrl(artifact)}
                                    alt={artifact.name}
                                    style={{ width: '100%', aspectRatio: '16 / 10', objectFit: 'cover', borderRadius: '6px', border: '1px solid var(--border)' }}
                                />
                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', overflowWrap: 'anywhere' }}>{artifact.name}</span>
                            </a>
                        ))}
                    </div>
                )}
                {otherArtifacts.length > 0 && (
                    <div style={{ display: 'grid', gap: '0.4rem' }}>
                        {otherArtifacts.map((artifact: AgentArtifact) => (
                            <a
                                key={artifact.path}
                                href={getArtifactUrl(artifact)}
                                target="_blank"
                                rel="noreferrer"
                                data-testid="explorer-captured-artifact"
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.65rem 0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text)', textDecoration: 'none', fontSize: '0.84rem' }}
                            >
                                {artifact.type === 'video' ? <VideoIcon size={15} /> : artifact.type === 'image' ? <ImageIcon size={15} /> : <FileText size={15} />}
                                <span style={{ overflowWrap: 'anywhere' }}>{artifact.name}</span>
                                <ExternalLink size={13} style={{ marginLeft: 'auto', color: 'var(--text-secondary)' }} />
                            </a>
                        ))}
                    </div>
                )}
            </div>
        );
    };

    const renderExplorerUnsupportedFlowCandidates = () => {
        if (explorerUnsupportedFlowCandidates.length === 0) return null;
        return (
            <div data-testid="explorer-unsupported-flow-candidates" style={{ display: 'grid', gap: '0.75rem' }}>
                <div>
                    <h4 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.25rem', color: 'var(--text)' }}>Unsupported Flow Candidates ({explorerUnsupportedFlowCandidates.length})</h4>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                        The model reported these candidates, but their cited evidence event IDs were missing or empty. They are visible for review and are not eligible for test generation.
                    </p>
                </div>
                <div style={{ display: 'grid', gap: '0.65rem' }}>
                    {explorerUnsupportedFlowCandidates.map((flow: any, i: number) => (
                        <div key={flow.id || i} data-testid="explorer-unsupported-flow-card" style={{ padding: '0.9rem', background: 'var(--surface)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                            <h5 style={{ margin: '0 0 0.4rem', fontWeight: 650, color: 'var(--text)' }}>{flow.title || `Unsupported candidate ${i + 1}`}</h5>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45, overflowWrap: 'anywhere' }}>
                                Missing evidence IDs: {(flow.missing_evidence_event_ids || []).join(', ') || 'not reported'}
                            </div>
                            {(flow.entry_point || flow.exit_point) && (
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45, overflowWrap: 'anywhere', marginTop: '0.3rem' }}>
                                    {flow.entry_point ? `Starts: ${flow.entry_point}` : ''}{flow.entry_point && flow.exit_point ? ' · ' : ''}{flow.exit_point ? `Ends: ${flow.exit_point}` : ''}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        );
    };

    const renderHistoryWorkspace = () => (
        <div className="card agents-history-workspace">
            <div className="agents-history-workspace-header">
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Run History</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {visibleHistory.length} of {historyTotal} runs
                    </p>
                </div>
                <button className="btn-icon agents-icon-button" type="button" onClick={() => void fetchHistory()} title="Refresh run history" aria-label="Refresh run history" disabled={historyLoading}>
                    {historyLoading ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />}
                </button>
            </div>

            <div className="agents-history-toolbar">
                <Label htmlFor="agents-history-search" className="agents-visually-hidden">Search run history</Label>
                <div style={{ position: 'relative', minWidth: 0 }}>
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

            <div className="agents-history-list">
                {historyError ? (
                    <div style={{ padding: '1rem', color: 'var(--danger)', fontSize: '0.85rem' }}>
                        {historyError}
                    </div>
                ) : history.length === 0 && historyLoading ? (
                    <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        Loading runs...
                    </div>
                ) : history.length === 0 ? (
                    <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        No runs yet.
                    </div>
                ) : visibleHistory.length === 0 ? (
                    <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        No runs match the current filters.
                    </div>
                ) : (
                    <>
                        {visibleHistory.map(run => (
                            <button
                                key={run.id}
                                type="button"
                                className="agents-history-row agents-history-row-wide"
                                onClick={() => selectHistoryRun(run.id)}
                                aria-current={selectedRunId === run.id ? 'true' : undefined}
                                style={{
                                    background: selectedRunId === run.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                                    borderLeft: selectedRunId === run.id ? '3px solid var(--primary)' : '3px solid transparent'
                                }}
                            >
                                <div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flexWrap: 'wrap' }}>
                                        <span style={{ fontWeight: 800, color: run.agent_type === 'custom' ? 'var(--success)' : run.agent_type === 'writer' || run.agent_type === 'spec_generation' ? 'var(--primary)' : 'var(--warning)' }}>
                                            {agentRunDisplayName(run)}
                                        </span>
                                        <StatusBadge status={run.status} />
                                    </div>
                                    <div style={{ marginTop: '0.35rem', fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text)' }}>
                                        {run.config?.url?.replace('https://', '') || run.config?.agent_name || run.id}
                                    </div>
                                </div>
                                <div className="agents-history-row-meta">
                                    <span>{formatDate(run.created_at)}</span>
                                    <span>{run.id.slice(0, 8)}</span>
                                </div>
                            </button>
                        ))}
                        {historyNextCursor && (
                            <div style={{ padding: '0.9rem' }}>
                                <Button type="button" variant="outline" size="sm" onClick={loadMoreHistory} disabled={historyLoading} style={{ width: '100%' }}>
                                    {historyLoading ? <Loader2 className="spin" size={14} /> : <ChevronDown size={14} />} Load more
                                </Button>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );

    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
            <style>{`
                .agents-workspace-grid {
                    display: grid;
                    grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.65fr);
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
                .agents-history-workspace {
                    padding: 0;
                    overflow: hidden;
                }
                .agents-history-workspace-header {
                    padding: 0.9rem 1rem;
                    border-bottom: 1px solid var(--border);
                    background: var(--surface-hover);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 0.75rem;
                }
                .agents-history-toolbar {
                    padding: 0.9rem 1rem;
                    border-bottom: 1px solid var(--border);
                    display: grid;
                    grid-template-columns: minmax(280px, 1fr) minmax(300px, 0.75fr);
                    gap: 0.75rem;
                    align-items: center;
                }
                .agents-history-list {
                    display: grid;
                }
                .agents-history-row-wide {
                    padding: 0.9rem 1rem;
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 1rem;
                    align-items: center;
                }
                .agents-history-row-meta {
                    display: grid;
                    gap: 0.3rem;
                    justify-items: end;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    white-space: nowrap;
                }
                .agents-history-row:focus-visible,
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
                .agents-action-status {
                    display: flex;
                    align-items: flex-start;
                    gap: 0.55rem;
                    margin: 0 0 1rem;
                    padding: 0.75rem 0.9rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface-hover);
                    color: var(--text);
                    font-size: 0.86rem;
                    line-height: 1.4;
                }
                .agents-action-status[data-tone="error"] {
                    border-color: rgba(248, 113, 113, 0.35);
                    background: var(--danger-muted);
                    color: var(--danger);
                }
                .agents-action-status svg {
                    width: 16px;
                    height: 16px;
                    flex: 0 0 auto;
                    margin-top: 0.1rem;
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
                .agents-workspace-tab-count {
                    display: inline-flex;
                    align-items: center;
                    align-self: center;
                    color: #8f9bb7;
                    font-size: 0.78em;
                    font-weight: 800;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.2;
                }
                .agents-workspace-tab[data-active="true"] .agents-workspace-tab-count {
                    color: #8bb8ff;
                }
                .agents-workspace-tab:focus-visible,
                .agents-action-button:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-setup-stack {
                    display: flex;
                    flex-direction: column;
                    gap: 0.8rem;
                    min-width: 0;
                }
                .agents-run-empty-compact {
                    display: flex;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 0.65rem;
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface);
                    min-width: 0;
                }
                .agents-run-empty-icon {
                    width: 36px;
                    height: 36px;
                    border-radius: 8px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    color: var(--primary);
                    background: var(--primary-glow);
                    border: 1px solid rgba(59, 130, 246, 0.22);
                    flex: 0 0 auto;
                }
                .agents-run-empty-copy {
                    flex: 1 1 170px;
                    min-width: 0;
                }
                .agents-run-empty-copy strong {
                    display: block;
                    color: var(--text);
                    font-size: 0.82rem;
                    font-weight: 750;
                    line-height: 1.2;
                }
                .agents-run-empty-compact p {
                    margin: 0.18rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }
                .agents-run-empty-action {
                    margin-left: auto;
                    min-height: 36px;
                    padding-left: 0.65rem;
                    padding-right: 0.65rem;
                }
                .agents-custom-picker-row {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) 40px;
                    gap: 0.5rem;
                    align-items: end;
                    min-width: 0;
                }
                .agents-run-details-card {
                    display: flex;
                    flex-direction: column;
                    min-width: 0;
                    overflow: hidden;
                }
                .agents-run-details-body {
                    padding: 0.85rem;
                    flex: 1 1 auto;
                    display: grid;
                    gap: 0.8rem;
                    min-height: 0;
                    min-width: 0;
                    padding-bottom: 0.85rem;
                }
                .agents-run-details-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
                    gap: 0.75rem;
                    align-items: start;
                    min-width: 0;
                }
                .agents-run-field {
                    min-width: 0;
                    display: grid;
                    gap: 0.42rem;
                }
                .agents-run-field label,
                .agents-run-field-label {
                    display: flex;
                    align-items: center;
                    gap: 0.4rem;
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 750;
                    line-height: 1.2;
                }
                .agents-run-field input,
                .agents-run-field select,
                .agents-run-field textarea {
                    box-sizing: border-box;
                    max-width: 100%;
                    min-width: 0;
                }
                .agents-run-field input,
                .agents-run-field select {
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-run-field-note {
                    margin: 0;
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                    min-width: 0;
                }
                .agents-run-field-wide {
                    grid-column: 1 / -1;
                }
                .agents-task-prompt {
                    min-height: 74px;
                    max-height: 148px;
                    line-height: 1.4;
                }
                .agents-disclosure {
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface-hover);
                    display: grid;
                    grid-template-rows: auto;
                    overflow: hidden;
                    min-width: 0;
                    max-width: 100%;
                }
                .agents-disclosure-trigger {
                    width: 100%;
                    min-height: 40px;
                    padding: 0.55rem 0.7rem;
                    border: 0;
                    background: transparent;
                    color: var(--text);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.7rem;
                    cursor: pointer;
                    text-align: left;
                    font-size: 0.82rem;
                    font-weight: 800;
                }
                .agents-disclosure-trigger-main {
                    display: flex;
                    flex-direction: column;
                    gap: 0.12rem;
                    min-width: 0;
                }
                .agents-disclosure-trigger-label,
                .agents-disclosure-trigger-summary {
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-disclosure-trigger-summary {
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                    font-weight: 700;
                }
                .agents-disclosure-trigger:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: -2px;
                }
                .agents-disclosure-body {
                    padding: 0 0.7rem 0.75rem;
                    display: grid;
                    gap: 0.55rem;
                    min-width: 0;
                }
                .agents-context-disclosure {
                    grid-column: 1 / -1;
                }
                .agents-context-disclosure-custom {
                    background: var(--background);
                }
                .agents-context-disclosure-open {
                    min-height: 250px;
                }
                .agents-run-summary {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    align-items: center;
                    min-width: 0;
                    max-width: 100%;
                    overflow: hidden;
                }
                .agents-run-chip {
                    flex: 0 1 auto;
                    min-width: 0;
                    max-width: 100%;
                    min-height: 28px;
                    padding: 0.3rem 0.55rem;
                    border: 1px solid var(--border);
                    border-radius: 999px;
                    background: var(--background);
                    color: var(--text-secondary);
                    font-size: 0.73rem;
                    font-weight: 750;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-run-plan {
                    display: grid;
                    gap: 0.45rem;
                    padding-top: 0.2rem;
                    min-width: 0;
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
                .agents-run-footer {
                    padding: 0.75rem 0.85rem;
                    border-top: 1px solid var(--border);
                    background: color-mix(in srgb, var(--background-raised) 92%, transparent);
                    backdrop-filter: blur(10px);
                }
                .agents-run-details-card-custom .agents-run-footer {
                    z-index: 2;
                    flex: 0 0 auto;
                }
                .agents-start-button {
                    width: 100%;
                    min-height: 44px;
                    padding: 0.75rem;
                    border-radius: 6px;
                    font-size: 0.9rem;
                    background: var(--primary);
                    color: white;
                    font-weight: 700;
                    border: none;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.5rem;
                }
                .agents-start-button:disabled {
                    cursor: not-allowed;
                    opacity: 0.7;
                }
                .agents-builder-grid {
                    display: grid;
                    grid-template-columns: minmax(330px, 0.92fr) minmax(360px, 1.08fr);
                    gap: 1.1rem;
                    align-items: start;
                }
                .agents-builder-dialog {
                    padding: 1.35rem !important;
                }
                .agents-builder-form {
                    display: grid;
                    gap: 0.85rem;
                    align-content: start;
                    min-width: 0;
                }
                .agents-builder-field {
                    display: grid;
                    gap: 0.38rem;
                    min-width: 0;
                }
                .agents-builder-split {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(130px, 0.8fr);
                    gap: 0.7rem;
                }
                .agents-runtime-select-content {
                    width: var(--radix-select-trigger-width) !important;
                    min-width: var(--radix-select-trigger-width) !important;
                }
                .agents-builder-textarea {
                    width: 100%;
                    min-height: 178px;
                    padding: 0.75rem;
                    border-radius: var(--radius);
                    font-size: 0.86rem;
                    border: 1px solid var(--border);
                    background: var(--background-raised);
                    color: var(--text);
                    resize: vertical;
                    line-height: 1.35;
                }
                .agents-builder-tools {
                    display: grid;
                    gap: 0.65rem;
                    align-content: start;
                    min-width: 0;
                }
                .agents-builder-tools-header {
                    display: flex;
                    justify-content: space-between;
                    gap: 0.75rem;
                    align-items: center;
                    min-width: 0;
                }
                .agents-builder-selected-count {
                    min-height: 26px;
                    padding: 0.25rem 0.6rem;
                    border-radius: 999px;
                    background: var(--surface-hover);
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    font-weight: 750;
                    white-space: nowrap;
                }
                .agents-builder-tools-list {
                    max-height: min(520px, calc(86vh - 210px));
                    overflow-y: auto;
                    border: 1px solid var(--border);
                    border-radius: 10px;
                    padding: 0.8rem;
                    display: grid;
                    gap: 1rem;
                    background: rgba(15, 22, 41, 0.32);
                }
                .agents-tool-category-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.5rem;
                }
                .agents-tool-category-title {
                    font-size: 0.74rem;
                    color: var(--text-secondary);
                    font-weight: 800;
                    text-transform: uppercase;
                    letter-spacing: 0;
                }
                .agents-tool-row {
                    display: grid;
                    grid-template-columns: 24px minmax(0, 1fr);
                    gap: 0.55rem;
                    align-items: start;
                    min-height: 48px;
                    cursor: pointer;
                }
                .agents-tool-row input {
                    width: 16px;
                    height: 16px;
                    margin-top: 0.18rem;
                    accent-color: var(--primary);
                }
                .agents-tool-title-line {
                    display: flex;
                    gap: 0.45rem;
                    align-items: center;
                    flex-wrap: wrap;
                    min-width: 0;
                }
                .agents-tool-label {
                    font-weight: 750;
                    font-size: 0.83rem;
                    line-height: 1.2;
                }
                .agents-tool-risk-pill {
                    display: inline-flex;
                    align-items: center;
                    min-height: 22px;
                    padding: 0.18rem 0.52rem;
                    border: 1px solid;
                    border-radius: 999px;
                    font-size: 0.68rem;
                    font-weight: 800;
                    line-height: 1;
                    text-transform: lowercase;
                }
                .agents-tool-description {
                    display: block;
                    margin-top: 0.18rem;
                    color: var(--text-secondary);
                    line-height: 1.35;
                    font-size: 0.78rem;
                }
                .agents-builder-footer {
                    gap: 0.6rem;
                }
                .agents-report-edit-dialog {
                    background: linear-gradient(180deg, rgba(21, 29, 48, 0.98), rgba(15, 22, 41, 0.98)) !important;
                    border-color: var(--border-bright) !important;
                    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.48), 0 0 0 1px rgba(148, 163, 184, 0.05) !important;
                }
                .agents-report-edit-header {
                    padding: 1.35rem 4.5rem 1rem 1.35rem;
                    border-bottom: 1px solid var(--border);
                    background: rgba(10, 15, 26, 0.24);
                    text-align: left;
                    gap: 0.3rem;
                }
                .agents-report-edit-kicker {
                    width: fit-content;
                    max-width: 100%;
                    padding: 0.24rem 0.55rem;
                    border: 1px solid rgba(147, 197, 253, 0.22);
                    border-radius: 999px;
                    background: rgba(59, 130, 246, 0.11);
                    color: #bfdbfe;
                    font-size: 0.72rem;
                    font-weight: 800;
                    line-height: 1;
                    letter-spacing: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-report-edit-title {
                    margin: 0.15rem 0 0;
                    font-size: 1.05rem;
                    line-height: 1.25;
                    letter-spacing: 0;
                }
                .agents-report-edit-description {
                    margin: 0;
                    max-width: 560px;
                    color: var(--text-secondary) !important;
                    font-size: 0.86rem;
                    line-height: 1.45;
                    letter-spacing: 0;
                }
                .agents-report-edit-body {
                    min-height: 0;
                    overflow-y: auto;
                    padding: 1.15rem 1.35rem 1.25rem;
                }
                .agents-report-edit-form {
                    display: grid;
                    gap: 0.9rem;
                }
                .agents-report-edit-grid {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 0.85rem;
                    align-items: start;
                }
                .agents-report-edit-grid--title {
                    grid-template-columns: minmax(0, 1fr) minmax(150px, 190px);
                }
                .agents-report-edit-field {
                    display: grid;
                    gap: 0.42rem;
                    min-width: 0;
                }
                .agents-report-edit-field label {
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 800;
                    line-height: 1.2;
                    letter-spacing: 0;
                }
                .agents-report-edit-input,
                .agents-report-edit-select-trigger,
                .agents-report-edit-textarea {
                    border-color: var(--border-bright) !important;
                    background: rgba(10, 15, 26, 0.58) !important;
                    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
                }
                .agents-report-edit-input,
                .agents-report-edit-select-trigger {
                    min-height: 42px;
                    font-size: 0.88rem;
                }
                .agents-report-edit-select-trigger {
                    color: var(--text);
                    border-radius: var(--radius);
                }
                .agents-report-edit-textarea {
                    width: 100%;
                    min-height: 96px;
                    padding: 0.7rem 0.78rem;
                    border: 1px solid var(--border-bright);
                    border-radius: var(--radius);
                    color: var(--text);
                    font-family: inherit;
                    font-size: 0.88rem;
                    line-height: 1.5;
                    resize: vertical;
                    outline: none;
                }
                .agents-report-edit-textarea[data-size="lg"] {
                    min-height: 126px;
                }
                .agents-report-edit-input:focus,
                .agents-report-edit-textarea:focus,
                .agents-report-edit-select-trigger:focus,
                .agents-report-edit-select-trigger[data-state="open"] {
                    border-color: rgba(96, 165, 250, 0.82) !important;
                    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.03) !important;
                }
                .agents-report-edit-input:disabled,
                .agents-report-edit-textarea:disabled,
                .agents-report-edit-select-trigger:disabled {
                    cursor: not-allowed;
                    opacity: 0.58;
                }
                .agents-report-edit-select-content {
                    width: var(--radix-select-trigger-width) !important;
                    min-width: var(--radix-select-trigger-width) !important;
                }
                .agents-report-edit-footer {
                    gap: 0.65rem;
                    justify-content: flex-end;
                    padding: 1rem 1.35rem;
                    border-top: 1px solid var(--border);
                    background: rgba(10, 15, 26, 0.36);
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
                .agents-library-panel {
                    padding: 1rem;
                    display: grid;
                    gap: 1rem;
                }
                .agents-library-header {
                    display: flex;
                    justify-content: space-between;
                    gap: 1rem;
                    align-items: flex-start;
                    flex-wrap: wrap;
                }
                .agents-library-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 0.85rem;
                }
                .agents-library-card {
                    min-width: 0;
                    padding: 1rem;
                    border: 1px solid var(--border);
                    border-radius: 10px;
                    background: linear-gradient(180deg, rgba(38, 52, 80, 0.72), rgba(30, 42, 66, 0.92));
                    display: grid;
                    gap: 0.85rem;
                    align-content: space-between;
                    transition: border-color 0.16s var(--ease-smooth), background 0.16s var(--ease-smooth), box-shadow 0.16s var(--ease-smooth);
                }
                .agents-library-card[data-selected="true"] {
                    border-color: var(--primary);
                    background: linear-gradient(180deg, rgba(59, 130, 246, 0.2), rgba(30, 42, 66, 0.94));
                    box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.18);
                }
                .agents-library-card-header {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.7rem;
                    align-items: start;
                }
                .agents-library-card-title {
                    margin: 0;
                    font-size: 0.98rem;
                    font-weight: 800;
                    line-height: 1.25;
                    overflow-wrap: anywhere;
                }
                .agents-library-card-description {
                    margin: 0.28rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    line-height: 1.45;
                    overflow-wrap: anywhere;
                }
                .agents-library-menu-trigger {
                    width: 36px;
                    height: 36px;
                    margin-right: 0;
                }
                .agents-library-card-meta {
                    display: flex;
                    gap: 0.45rem;
                    flex-wrap: wrap;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                }
                .agents-library-run-button {
                    width: 100%;
                    min-height: 44px;
                    padding: 0 1rem;
                    border: 1px solid rgba(147, 197, 253, 0.32) !important;
                    box-shadow: 0 10px 22px -16px rgba(59, 130, 246, 0.82);
                    font-size: 0.9rem;
                    font-weight: 800;
                }
                .agents-library-run-button:hover:not(:disabled) {
                    background: var(--primary-hover) !important;
                    border-color: rgba(191, 219, 254, 0.5) !important;
                }
                .agents-library-empty {
                    padding: 2rem;
                    text-align: center;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    color: var(--text-secondary);
                }
                @media (max-width: 1180px) {
                    .agents-workspace-grid {
                        grid-template-columns: minmax(300px, 0.85fr) minmax(0, 1.35fr);
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
                    .agents-setup-panel {
                        order: -1;
                    }
                    .agents-run-details-body {
                        padding: 0.65rem;
                        gap: 0.55rem;
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
                    .agents-history-toolbar,
                    .agents-history-row-wide {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-history-row-meta {
                        justify-items: start;
                    }
                }
                @media (max-width: 720px) {
                    .agents-run-details-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-run-empty-compact {
                        align-items: flex-start;
                    }
                    .agents-run-empty-icon {
                        width: 32px;
                        height: 32px;
                    }
                    .agents-run-empty-action {
                        width: 100%;
                        margin-left: 0;
                    }
                    .agents-builder-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-builder-split {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-builder-tools-list {
                        max-height: 420px;
                    }
                    .agents-report-search-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-report-edit-header {
                        padding: 1.15rem 3.75rem 0.9rem 1rem;
                    }
                    .agents-report-edit-body {
                        padding: 1rem;
                    }
                    .agents-report-edit-grid,
                    .agents-report-edit-grid--title {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-report-edit-footer {
                        padding: 0.9rem 1rem;
                        flex-direction: column-reverse;
                    }
                    .agents-report-edit-footer button {
                        width: 100%;
                    }
                    .agents-library-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-library-header .agents-library-create-button {
                        width: 100%;
                    }
                }
            `}</style>
            <PageHeader
                title="Autonomous Agents"
                subtitle="Deploy AI agents to explore, test, and specify your application autonomously."
                icon={<Bot size={20} />}
            />

            <div aria-live="polite" className="agents-visually-hidden">{workspaceStatus}</div>
            {workspaceStatus && (
                <div
                    role="status"
                    data-testid="agents-action-status"
                    className="agents-action-status"
                    data-tone={workspaceStatus.toLowerCase().includes('failed') || workspaceStatus.toLowerCase().includes('missing') || workspaceStatus.toLowerCase().includes('not found') ? 'error' : 'info'}
                >
                    {workspaceStatus.toLowerCase().includes('failed') || workspaceStatus.toLowerCase().includes('missing') || workspaceStatus.toLowerCase().includes('not found') ? (
                        <AlertTriangle aria-hidden="true" />
                    ) : (
                        <Info aria-hidden="true" />
                    )}
                    <span>{workspaceStatus}</span>
                </div>
            )}

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
                        {tab.count ? <span className="agents-workspace-tab-count">{tab.count}</span> : null}
                    </button>
                ))}
            </div>

            {workspaceView === 'run' && (
            <div className="agents-workspace-grid">

                {/* Left Column: Configuration */}
                <Collapsible open={setupOpen} onOpenChange={setSetupOpen} className="agents-panel agents-setup-panel">
                    <div className="agents-setup-stack">
                    <div
                        id="agents-run-setup-panel"
                        className="card agents-run-details-card agents-run-details-card-custom"
                    >
                        <div style={{ padding: '0.8rem 0.85rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
                            <div>
                                <h3 style={{ fontWeight: 700, fontSize: '0.9rem', margin: 0 }}>Run Setup</h3>
                                <p style={{ margin: '0.2rem 0 0', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                                    {agentDefinitions.length} custom saved
                                </p>
                            </div>
                            <CollapsibleTrigger asChild>
                                <button className="btn-icon agents-icon-button agents-mobile-trigger" type="button" aria-label={setupOpen ? 'Collapse run setup' : 'Expand run setup'}>
                                    <ChevronDown size={14} />
                                </button>
                            </CollapsibleTrigger>
                        </div>
                        <CollapsibleContent forceMount>
                        <div className="agents-desktop-content" data-open={setupOpen ? 'true' : 'false'}>
                        <div className="agents-run-details-body">
                        <div className="agents-run-details-grid">
                        <div className="agents-run-field agents-run-field-wide">
                            {agentDefinitions.length === 0 ? (
                                <div className="agents-run-empty-compact">
                                    <span className="agents-run-empty-icon" aria-hidden="true">
                                        <PackageOpen size={16} />
                                    </span>
                                    <div className="agents-run-empty-copy">
                                        <strong>No runnable agents yet.</strong>
                                        <p>Create a saved custom agent to run it from this workspace.</p>
                                    </div>
                                    <Button type="button" size="sm" variant="outline" className="agents-run-empty-action" onClick={openCreateAgentBuilder} aria-label="Create custom agent">
                                        <Plus size={14} /> Create Agent
                                    </Button>
                                </div>
                            ) : (
                                <div className="agents-custom-picker-row">
                                    <div className="agents-run-field">
                                        <label htmlFor="agents-definition-select">Runnable Agent</label>
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
                                            <p className="agents-run-field-note">
                                                {selectedDefinition.description || `${selectedDefinition.tool_ids.length} selected tools`} · Runtime: Claude SDK
                                            </p>
                                        )}
                                    </div>
                                    <Button type="button" size="icon" variant="outline" onClick={openCreateAgentBuilder} title="Create agent" aria-label="Create custom agent">
                                        <Plus size={15} />
                                    </Button>
                                </div>
                            )}
                        </div>

                        <div className="agents-run-field">
                            <label htmlFor="agents-target-url">Target URL</label>
                            <input
                                id="agents-target-url"
                                name="targetUrl"
                                type="url"
                                placeholder="Optional target URL"
                                value={url}
                                onChange={e => setUrl(e.target.value)}
                                autoComplete="url"
                                style={{
                                    width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                }}
                            />
                        </div>

                        <div className="agents-run-field">
                            <label htmlFor="agents-custom-session-select">Browser Login Session</label>
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

                        <div className="agents-run-field agents-run-field-wide">
                            <label htmlFor="agents-instructions">Task Prompt</label>
                            <textarea
                                className="agents-task-prompt"
                                id="agents-instructions"
                                name="instructions"
                                placeholder="Inspect the API calls triggered by the login and checkout flows."
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
                        </div>

                        <div className={`agents-disclosure agents-context-disclosure agents-context-disclosure-custom${contextDataOpen ? ' agents-context-disclosure-open' : ''}`}>
                            <button
                                type="button"
                                className="agents-disclosure-trigger"
                                aria-expanded={contextDataOpen}
                                aria-controls="agents-context-test-data-panel"
                                onClick={() => setContextDataOpen(open => !open)}
                            >
                                <span className="agents-disclosure-trigger-main">
                                    <span className="agents-disclosure-trigger-label">Context & Test Data</span>
                                    <span className="agents-disclosure-trigger-summary">{testDataRefsSummary}</span>
                                </span>
                                <ChevronDown size={15} aria-hidden="true" />
                            </button>
                            {contextDataOpen && (
                                <div id="agents-context-test-data-panel" className="agents-disclosure-body">
                                    <div className="agents-run-field">
                                        <label htmlFor="agents-test-data-refs">Project Test Data Refs</label>
                                        <Input
                                            id="agents-test-data-refs"
                                            name="testDataRefs"
                                            value={testDataRefs}
                                            onChange={e => setTestDataRefs(e.target.value)}
                                            placeholder="Refs appear here after adding"
                                            autoComplete="off"
                                            style={{ height: '36px', minHeight: '36px', borderRadius: '8px', fontSize: '0.8rem' }}
                                        />
                                    </div>
                                    <TestDataPicker
                                        projectId={currentProject?.id}
                                        mode="ref"
                                        variant="sidebar"
                                        compact
                                        insertLabel="Add"
                                        editLabel="Edit"
                                        onInsert={(value: string) => setTestDataRefs(prev => prev ? `${prev}, ${value}` : value)}
                                    />
                                </div>
                            )}
                        </div>

                        {runFormError && (
                            <Alert variant="destructive" style={{ marginBottom: '0.85rem' }}>
                                <AlertTriangle size={16} />
                                <AlertDescription>{runFormError}</AlertDescription>
                            </Alert>
                        )}

                        <div className="agents-run-summary" aria-label="Run plan preview">
                            {runPlanRows.slice(0, 5).map(([label, value]) => (
                                <span key={label} className="agents-run-chip" title={`${label}: ${value || '-'}`}>
                                    {label}: {value || '-'}
                                </span>
                            ))}
                            {queueWarnings.degraded && <span className="agents-run-chip" style={{ color: 'var(--warning)' }}>Queue needs attention</span>}
                        </div>

                        <div className="agents-disclosure">
                            <button
                                type="button"
                                className="agents-disclosure-trigger"
                                aria-expanded={runPlanDetailsOpen}
                                aria-controls="agents-run-plan-details"
                                onClick={() => setRunPlanDetailsOpen(open => !open)}
                            >
                                <span>Run Plan Details</span>
                                <ChevronDown size={15} aria-hidden="true" />
                            </button>
                            {runPlanDetailsOpen && (
                                <div id="agents-run-plan-details" className="agents-disclosure-body">
                                    <div className="agents-run-plan">
                                        {runPlanRows.map(([label, value]) => (
                                            <div key={label} className="agents-run-plan-row">
                                                <strong>{label}</strong>
                                                <span>{value || '-'}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                            </div>

                        <div className="agents-run-footer">
                        <button
                            className="agents-start-button"
                            onClick={handleRun}
                            disabled={isStarting}
                        >
                            {isStarting ? <><Loader2 className="spin" size={16} /> Starting...</> : <><Play size={16} /> Start Agent</>}
                        </button>
                        </div>
                        </div>
                        </CollapsibleContent>
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
                                {isAgentRunTerminal(activeRun.status) && activeRun.status !== 'completed' && (
                                    <button
                                        onClick={retryAgentRun}
                                        disabled={runControlPending !== null}
                                        title="Retry agent run"
                                        aria-label="Retry agent run"
                                        data-testid="agents-retry-run"
                                        style={{ border: '1px solid var(--primary)', background: 'var(--primary)', color: 'white', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'retry' ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />} Retry
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
                                    <p style={{ margin: '0.45rem auto 0', maxWidth: 460, lineHeight: 1.5 }}>Choose a saved custom agent to start a run, or open history to inspect previous results.</p>
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem', justifyContent: 'center' }}>
                                    <Button type="button" variant="outline" onClick={() => selectWorkspaceView('history')}>
                                        <RotateCcw size={14} /> Open History
                                    </Button>
                                    <Button type="button" variant="outline" onClick={() => { selectWorkspaceView('library'); openCreateAgentBuilder(); }}>
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
                                const toolCalls = Number(progress.tool_calls ?? 0);
                                const browserActions = Number(progress.browser_tool_calls ?? progress.interactions ?? 0);
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
	                                                <div style={{ fontWeight: 700 }}>{Number.isFinite(toolCalls) ? toolCalls : 0}</div>
	                                            </div>
	                                            <div>
	                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Browser Actions</div>
	                                                <div style={{ fontWeight: 700 }}>{Number.isFinite(browserActions) ? browserActions : 0}</div>
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
                                {activeRun.agent_type === 'exploratory' && activeRun.result && (
                                    <div data-testid="explorer-failed-recovery" style={{ display: 'grid', gap: '1rem' }}>
                                        <div
                                            data-testid="explorer-contract-warnings"
                                            style={{ padding: '1rem', background: explorerEvidenceEventCount > 0 ? 'var(--warning-muted)' : 'var(--danger-muted)', borderRadius: '10px', border: `1px solid ${explorerEvidenceEventCount > 0 ? 'rgba(251, 191, 36, 0.28)' : 'rgba(248, 113, 113, 0.22)'}`, display: 'grid', gap: '0.45rem' }}
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 750, color: explorerEvidenceEventCount > 0 ? 'var(--warning)' : 'var(--danger)' }}>
                                                <AlertTriangle size={16} /> {explorerEvidenceEventCount > 0 ? 'Explorer recovered partial evidence' : 'Explorer recovered no structured evidence'}
                                            </div>
                                            {[activeRun.result.summary, activeRun.result.failure_reason, ...explorerContractWarnings].filter(Boolean).map((warning: any, index: number) => (
                                                <div key={`${warning}-${index}`} data-testid="explorer-contract-warning" style={{ color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                                                    {String(warning)}
                                                </div>
                                            ))}
                                        </div>

                                        <div data-testid="explorer-quality-metrics" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.75rem' }}>
                                            {[
                                                ['Evidence Events', explorerEvidenceEventCount, 'explorer-metric-evidence-events'],
                                                ['Screenshots', explorerScreenshotCount, 'explorer-metric-screenshots'],
                                                ['Artifacts', explorerArtifactCount, 'explorer-metric-artifacts'],
                                                ['Successful Browser Actions', explorerDiagnostics.successful_browser_tool_calls ?? 0, 'explorer-metric-successful-browser-actions'],
                                                ['Deduped Flows', explorerStructuredFlowCount, 'explorer-metric-deduped-flows'],
                                                ['Duplicate Flows Removed', explorerDiagnostics.dedupe_stats?.duplicate_flows_removed ?? 0, 'explorer-metric-duplicates-removed'],
                                            ].map(([label, value, testId]) => (
                                                <div key={String(testId)} data-testid={String(testId)} style={{ padding: '0.85rem', background: 'var(--background)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                                    <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text)' }}>{String(value)}</div>
                                                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>{String(label)}</div>
                                                </div>
                                            ))}
                                        </div>

                                        {renderExplorerCapturedEvidence()}
                                        {renderExplorerUnsupportedFlowCandidates()}

                                        {explorerFlowSummaries.length > 0 ? (
                                            <div style={{ display: 'grid', gap: '0.75rem' }}>
                                                {explorerFlowSummaries.map((flow: any, i: number) => (
                                                    <div key={flow.id || i} data-testid="explorer-flow-card" style={{ padding: '1rem', background: 'var(--surface)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                                        <h5 style={{ margin: '0 0 0.45rem', fontWeight: 650 }}>{flow.title || `Recovered flow ${i + 1}`}</h5>
                                                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', overflowWrap: 'anywhere' }}>
                                                            {(flow.steps_count || 0)} steps{flow.entry_point ? ` · Starts: ${flow.entry_point}` : ''}{flow.exit_point ? ` · Ends: ${flow.exit_point}` : ''}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        ) : (
                                            <div data-testid="explorer-no-structured-flows" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                                                No evidence-backed flow summaries were recovered, so test spec generation is disabled for this run.
                                            </div>
                                        )}
                                    </div>
                                )}
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
                                        onEditOverview={openReportOverviewEdit}
                                        onEditReportItem={openReportItemEdit}
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

                                                {activeRun.status === 'completed_partial' && (
                                                    <div
                                                        data-testid="explorer-partial-warning"
                                                        style={{ padding: '1rem', background: 'var(--warning-muted)', borderRadius: '10px', border: '1px solid rgba(251, 191, 36, 0.28)', color: 'var(--text-secondary)', display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}
                                                    >
                                                        <AlertTriangle size={16} style={{ color: 'var(--warning)', marginTop: '0.1rem' }} />
                                                        <div>
                                                            <strong style={{ color: 'var(--warning)' }}>Partial Explorer result</strong>
                                                            <div style={{ fontSize: '0.86rem', lineHeight: 1.45, marginTop: '0.25rem' }}>
                                                                The run explored the app, but no completed evidence-backed flows were recovered. Review captured evidence and unsupported candidates before retrying or generating specs.
                                                            </div>
                                                        </div>
                                                    </div>
                                                )}

                                                {explorerContractWarnings.length > 0 && (
                                                    <div
                                                        data-testid="explorer-contract-warnings"
                                                        style={{ padding: '1rem', background: 'var(--warning-muted)', borderRadius: '10px', border: '1px solid rgba(251, 191, 36, 0.28)', display: 'grid', gap: '0.45rem' }}
                                                    >
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 750, color: 'var(--warning)' }}>
                                                            <AlertTriangle size={16} /> Explorer evidence warning
                                                        </div>
                                                        {explorerContractWarnings.map((warning: string, index: number) => (
                                                            <div key={`${warning}-${index}`} data-testid="explorer-contract-warning" style={{ color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                                                                {warning}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Key Metrics */}
                                                {activeRun.result.coverage && (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            📊 What Was Explored
                                                        </h4>
                                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                                                            <div data-testid="explorer-metric-pages" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--primary)' }}>
                                                                    {activeRun.result.coverage.pages_visited || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Pages Visited
                                                                </div>
                                                            </div>
                                                            <div data-testid="explorer-metric-flows" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--success)' }}>
                                                                    {activeRun.result.coverage.flows_discovered || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    User Flows Found
                                                                </div>
                                                            </div>
                                                            <div data-testid="explorer-metric-forms" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--warning)' }}>
                                                                    {activeRun.result.coverage.forms_interacted || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Forms Tested
                                                                </div>
                                                            </div>
                                                            {activeRun.result.coverage.errors_found !== undefined && (
                                                                <div data-testid="explorer-metric-issues" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                    <div style={{ fontSize: '2rem', fontWeight: 700, color: activeRun.result.coverage.errors_found > 0 ? 'var(--danger)' : 'var(--success)' }}>
                                                                        {activeRun.result.coverage.errors_found || 0}
                                                                    </div>
                                                                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                        Issues Found
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                        <div data-testid="explorer-quality-metrics" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.75rem', marginTop: '0.85rem' }}>
                                                            {[
                                                                ['Evidence Events', explorerEvidenceEventCount, 'explorer-metric-evidence-events'],
                                                                ['Screenshots', explorerScreenshotCount, 'explorer-metric-screenshots'],
                                                                ['Artifacts', explorerArtifactCount, 'explorer-metric-artifacts'],
                                                                ['Unsupported Candidates', explorerUnsupportedFlowCandidates.length, 'explorer-metric-unsupported-candidates'],
                                                                ['Successful Browser Actions', explorerDiagnostics.successful_browser_tool_calls ?? 0, 'explorer-metric-successful-browser-actions'],
                                                                ['Deduped Flows', explorerStructuredFlowCount, 'explorer-metric-deduped-flows'],
                                                                ['Duplicate Flows Removed', explorerDiagnostics.dedupe_stats?.duplicate_flows_removed ?? 0, 'explorer-metric-duplicates-removed'],
                                                            ].map(([label, value, testId]) => (
                                                                <div key={String(testId)} data-testid={String(testId)} style={{ padding: '0.85rem', background: 'var(--background)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                                                    <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text)' }}>{String(value)}</div>
                                                                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>{String(label)}</div>
                                                                </div>
                                                            ))}
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

                                                {renderExplorerCapturedEvidence()}

                                                {/* Discovered Flows - Clear Display */}
                                                {explorerFlowSummaries.length > 0 ? (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            🔍 Discovered User Flows ({activeRun.result.total_flows_discovered || explorerFlowSummaries.length})
                                                        </h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                                            These are the complete user journeys the agent found. Each one can be turned into a test.
                                                        </p>
                                                        <div style={{ display: 'grid', gap: '1rem' }}>
                                                            {explorerFlowSummaries.map((flow: any, i: number) => (
                                                                <div key={flow.id || i} data-testid="explorer-flow-card" style={{
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
                                                            The agent did not recover any complete evidence-backed flows. Try increasing the time limit or exploring a different area.
                                                        </p>
                                                    </div>
                                                )}

                                                {renderExplorerUnsupportedFlowCandidates()}

                                            {/* Next Steps */}
                                            {explorerCanGenerateSpecs && (
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
                                            )}

                                            {/* Spec Synthesis Button */}
                                            {activeRun.agent_type === 'exploratory' && explorerCanGenerateSpecs && (
                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                <button
                                                    onClick={handleSynthesize}
                                                    disabled={isSynthesizing || !explorerCanGenerateSpecs}
                                                    data-testid="explorer-generate-test-specs"
                                                    style={{
                                                        flex: 1, padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                                        background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none',
                                                        cursor: isSynthesizing || !explorerCanGenerateSpecs ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                                        opacity: isSynthesizing || !explorerCanGenerateSpecs ? 0.7 : 1
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

            {workspaceView === 'history' && renderHistoryWorkspace()}

                <Dialog open={builderOpen} onOpenChange={(open) => { if (open) setBuilderOpen(true); else closeCustomAgentBuilder(); }}>
                    <DialogContent className="agents-builder-dialog max-w-[960px]" style={{ width: 'min(960px, calc(100vw - 2rem))', maxHeight: '86vh', overflowY: 'auto' }}>
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
                            <div className="agents-builder-form">
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-name">Name</Label>
                                    <Input id="definition-name" name="definitionName" value={definitionForm.name} onChange={e => setDefinitionForm({ ...definitionForm, name: e.target.value })} placeholder="API explorer" autoComplete="off" />
                                </div>
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-description">Description</Label>
                                    <Input id="definition-description" name="definitionDescription" value={definitionForm.description} onChange={e => setDefinitionForm({ ...definitionForm, description: e.target.value })} placeholder="Explores pages and reports API calls" autoComplete="off" />
                                </div>
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-system-prompt">System Prompt</Label>
                                    <textarea
                                        id="definition-system-prompt"
                                        name="definitionSystemPrompt"
                                        value={definitionForm.system_prompt}
                                        onChange={e => setDefinitionForm({ ...definitionForm, system_prompt: e.target.value })}
                                        rows={7}
                                        className="agents-builder-textarea"
                                    />
                                </div>
                                <div className="agents-builder-split">
                                    <div className="agents-builder-field">
                                        <Label htmlFor="definition-runtime">Runtime</Label>
                                        <Select value={definitionForm.runtime} onValueChange={value => setDefinitionForm({ ...definitionForm, runtime: value })}>
                                            <SelectTrigger id="definition-runtime" aria-label="Runtime">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent className="agents-runtime-select-content" sideOffset={8}>
                                                <SelectItem value="claude_sdk">Claude SDK</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="agents-builder-field">
                                        <Label htmlFor="definition-timeout">Timeout seconds</Label>
                                        <Input id="definition-timeout" name="definitionTimeoutSeconds" type="number" min={60} max={7200} value={definitionForm.timeout_seconds} onChange={e => setDefinitionForm({ ...definitionForm, timeout_seconds: parseInt(e.target.value) || 1800 })} />
                                    </div>
                                </div>
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-test-data-refs">Default Test Data Refs</Label>
                                    <Input id="definition-test-data-refs" name="definitionTestDataRefs" value={definitionForm.test_data_refs} onChange={e => setDefinitionForm({ ...definitionForm, test_data_refs: e.target.value })} placeholder="login-users.valid-admin" autoComplete="off" />
                                    <TestDataPicker
                                        projectId={currentProject?.id}
                                        mode="ref"
                                        compact
                                        onInsert={(value: string) => setDefinitionForm(prev => ({
                                            ...prev,
                                            test_data_refs: prev.test_data_refs ? `${prev.test_data_refs}, ${value}` : value,
                                        }))}
                                    />
                                </div>
                            </div>

                            <div className="agents-builder-tools">
                                <div className="agents-builder-tools-header">
                                    <Label>Tools</Label>
                                    <span className="agents-builder-selected-count">{definitionForm.tool_ids.length} of {toolCatalog.length} selected</span>
                                </div>
                                <div className="agents-builder-tools-list">
                                    {Object.entries(toolsByCategory).map(([category, tools]) => (
                                        <fieldset key={category} style={{ border: 0, margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}>
                                            <div className="agents-tool-category-header">
                                                <legend className="agents-tool-category-title">
                                                    {category} ({tools.length})
                                                </legend>
                                                <Button type="button" variant="ghost" size="sm" onClick={() => toggleCategoryTools(tools)}>
                                                    {tools.every(tool => definitionForm.tool_ids.includes(tool.id)) ? 'Clear' : 'Select all'}
                                                </Button>
                                            </div>
                                            {tools.map(tool => (
                                                <label key={tool.id} className="agents-tool-row">
                                                    <input
                                                        type="checkbox"
                                                        checked={definitionForm.tool_ids.includes(tool.id)}
                                                        onChange={() => toggleDefinitionTool(tool.id)}
                                                    />
                                                    <span style={{ minWidth: 0 }}>
                                                        <span className="agents-tool-title-line">
                                                            <span className="agents-tool-label">{tool.label}</span>
                                                            <span className="agents-tool-risk-pill" style={TOOL_RISK_PILL_STYLES[tool.risk]}>{tool.risk}</span>
                                                        </span>
                                                        <span className="agents-tool-description">{tool.description}</span>
                                                    </span>
                                                </label>
                                            ))}
                                        </fieldset>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <DialogFooter className="agents-builder-footer">
                            <Button type="button" variant="outline" onClick={closeCustomAgentBuilder}>Cancel</Button>
                            <Button type="button" onClick={saveDefinition} disabled={savingDefinition}>
                                {savingDefinition ? <Loader2 className="spin" size={14} /> : <Save size={14} />} Save Agent
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                <Dialog open={Boolean(reportEditTarget)} onOpenChange={(open) => { if (!open) closeReportEditDialog(); }}>
                    <DialogContent
                        className="agents-report-edit-dialog"
                        style={{
                            width: 'min(760px, calc(100vw - 2rem))',
                            maxWidth: '760px',
                            maxHeight: '88vh',
                            overflow: 'hidden',
                            display: 'flex',
                            flexDirection: 'column',
                            padding: 0,
                            gap: 0,
                        }}
                    >
                        <DialogHeader className="agents-report-edit-header">
                            <span className="agents-report-edit-kicker">{reportEditKicker()}</span>
                            <DialogTitle className="agents-report-edit-title">{reportEditDialogTitle(reportEditTarget)}</DialogTitle>
                            <DialogDescription className="agents-report-edit-description">
                                Update the stored report content for this custom agent run.
                            </DialogDescription>
                        </DialogHeader>

                        <div className="agents-report-edit-body">
                            {reportEditError && (
                                <Alert variant="destructive">
                                    <AlertDescription>{reportEditError}</AlertDescription>
                                </Alert>
                            )}

                            <div className="agents-report-edit-form">
                                {reportEditTarget?.type === 'overview' && (
                                    <>
                                        {renderReportTextareaField('Summary', 'summary', 4, 'lg')}
                                        {renderReportTextareaField('Scope', 'scope', 3)}
                                    </>
                                )}

                                {reportEditTarget?.type !== 'overview' && (
                                    <>
                                        <div className="agents-report-edit-grid agents-report-edit-grid--title">
                                            {renderReportTextField('Title', 'title')}
                                            {reportEditTarget?.type === 'finding'
                                                ? renderReportSelectField('Severity', 'severity', REPORT_SEVERITY_OPTIONS)
                                                : renderReportSelectField('Priority', 'priority', REPORT_PRIORITY_OPTIONS)}
                                        </div>
                                        {renderReportTextField('Page', 'page')}
                                    </>
                                )}

                                {reportEditTarget?.type === 'finding' && (
                                    <>
                                        {renderReportTextareaField('Description', 'description', 4, 'lg')}
                                        {renderReportTextareaField('Evidence', 'evidence', 3)}
                                        {renderReportTextField('Suggested Action', 'suggested_action')}
                                    </>
                                )}

                                {reportEditTarget?.type === 'test_idea' && (
                                    <>
                                        {renderReportTextareaField('Steps', 'steps', 5, 'lg')}
                                        {renderReportTextareaField('Expected', 'expected', 3)}
                                        {renderReportTextField('Source Finding ID', 'source_finding_id')}
                                    </>
                                )}

                                {reportEditTarget?.type === 'requirement' && (
                                    <>
                                        <div className="agents-report-edit-grid">
                                            {renderReportTextField('Category', 'category')}
                                            {renderReportTextField('Confidence', 'confidence')}
                                        </div>
                                        {renderReportTextareaField('Description', 'description', 4, 'lg')}
                                        {renderReportTextareaField('Acceptance Criteria', 'acceptance_criteria', 4, 'lg')}
                                        {renderReportTextareaField('Evidence', 'evidence', 3)}
                                    </>
                                )}
                            </div>
                        </div>

                        <DialogFooter className="agents-report-edit-footer">
                            <Button type="button" variant="outline" onClick={closeReportEditDialog} disabled={savingReportEdit}>Cancel</Button>
                            <Button type="button" onClick={saveReportEdit} disabled={savingReportEdit}>
                                {savingReportEdit ? <Loader2 className="spin" size={14} /> : <Save size={14} />} Save Changes
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
                <Dialog open={flowModalVisible} onOpenChange={(open) => { if (open) setFlowModalOpen(true); else closeFlowModal(); }}>
                    {activeFlow ? (
                        <DialogContent style={{ width: 'min(980px, calc(100vw - 2rem))', maxWidth: '980px', maxHeight: '84vh', overflowY: 'auto' }}>
                            <DialogHeader>
                                <DialogTitle>{activeFlow.title}</DialogTitle>
                                <DialogDescription>Review the discovered flow and generate a test spec.</DialogDescription>
                            </DialogHeader>

                            {activeFlow.pages && activeFlow.pages.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Pages</h4>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {activeFlow.pages.map((page: string, i: number) => (
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

                            {activeFlow.happy_path && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--success)' }}>Happy Path</h4>
                                    <p style={{ fontSize: '0.9rem', lineHeight: '1.5', margin: 0 }}>
                                        {activeFlow.happy_path}
                                    </p>
                                </div>
                            )}

                            {activeFlow.edge_cases && activeFlow.edge_cases.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--warning)' }}>Edge Cases</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {activeFlow.edge_cases.map((ec: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{ec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {activeFlow.test_ideas && activeFlow.test_ideas.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Test Ideas</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {activeFlow.test_ideas.map((idea: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{idea}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {activeFlow.entry_point && (
                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                    Entry: {activeFlow.entry_point}
                                    {activeFlow.exit_point && ` -> Exit: ${activeFlow.exit_point}`}
                                </div>
                            )}

                            {activeFlow.source_type === 'custom_report' && (
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
                                    type="button"
                                    onClick={() => {
                                        if (activeFlow.source_type === 'custom_report') {
                                            if (reportSpecReview && activeFlow.item_type) {
                                                createSpecFromReportItem(reportSpecReview.item, activeFlow.item_type);
                                            } else {
                                                const message = 'The selected report item is no longer available for spec generation.';
                                                setFlowSpecError(message);
                                                setWorkspaceStatus(message);
                                            }
                                        } else {
                                            generateFlowSpec(activeFlow.id);
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
                                    ) : activeFlow.generated_spec ? (
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
                                    type="button"
                                    onClick={closeFlowModal}
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
                    ) : agentActionIntent.type === 'reviewReportSpec' ? (
                        <DialogContent style={{ width: 'min(640px, calc(100vw - 2rem))', maxWidth: '640px' }}>
                            <DialogHeader>
                                <DialogTitle>Report Item Unavailable</DialogTitle>
                                <DialogDescription>
                                    {missingReportSpecItemMessage || 'Loading the selected report item for spec review.'}
                                </DialogDescription>
                            </DialogHeader>
                            <div style={{ padding: '0.9rem 1rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)', color: 'var(--text)' }}>
                                {missingReportSpecItemMessage || `Looking for ${agentActionIntent.itemType} ${agentActionIntent.itemId} in run ${agentActionIntent.runId}.`}
                            </div>
                            <DialogFooter>
                                <Button type="button" variant="outline" onClick={closeFlowModal}>Close</Button>
                            </DialogFooter>
                        </DialogContent>
                    ) : null}
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
                                                if (activeFlow) {
                                                    generateFlowSpec(activeFlow.id, true);
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
                <div className="card agents-library-panel">
                    <div className="agents-library-header">
                        <div>
                            <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Agent Library</h2>
                            <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Create, edit, archive, and choose reusable custom agents.</p>
                        </div>
                        <Button type="button" className="agents-library-create-button" onClick={openCreateAgentBuilder}>
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
                        <div className="agents-library-empty">
                            No custom agents yet.
                        </div>
                    ) : (
                        <div className="agents-library-grid">
                            {agentDefinitions.map(definition => (
                                <div
                                    key={definition.id}
                                    className="agents-library-card"
                                    data-selected={selectedDefinitionId === definition.id}
                                >
                                    <div className="agents-library-card-header">
                                        <div>
                                            <h3 className="agents-library-card-title">{definition.name}</h3>
                                            <p className="agents-library-card-description">{definition.description || 'No description provided.'}</p>
                                        </div>
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
                                                    className="agents-definition-action-trigger agents-library-menu-trigger"
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
                                    <div className="agents-library-card-meta">
                                        <Badge variant="secondary">{definition.tool_ids.length} tools</Badge>
                                        <Badge variant="secondary">Claude SDK</Badge>
                                        <Badge variant="secondary">{Math.ceil((definition.timeout_seconds || 1800) / 60)}m</Badge>
                                    </div>
                                    <div>
                                        <Button
                                            type="button"
                                            size="sm"
                                            className="agents-library-run-button"
                                            onClick={() => { selectDefinition(definition.id); selectAgentMode('custom'); selectWorkspaceView('run'); }}
                                        >
                                            <Play size={13} /> Run Agent
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
                <QueueStatusPanel
                    queue={queueStatus}
                    loading={queueLoading}
                    error={queueError}
                    onRefresh={fetchQueueStatus}
                    onCleanStaleTasks={cleanStaleQueueTasks}
                    cleaningStaleTasks={queueCleanupLoading}
                />
            )}
        </PageLayout>
    );
}
