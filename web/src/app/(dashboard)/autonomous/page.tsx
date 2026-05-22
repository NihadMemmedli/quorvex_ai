'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
    AlertCircle,
    Bot,
    CalendarClock,
    ChevronDown,
    ChevronRight,
    CheckCircle,
    ClipboardCheck,
    Compass,
    DollarSign,
    FileText,
    Gauge,
    Loader2,
    Pause,
    Play,
    Plus,
    RefreshCw,
    ShieldCheck,
    Sparkles,
    Square,
    Target,
    Terminal,
    UploadCloud,
    Users,
    Workflow,
    X,
    XCircle,
} from 'lucide-react';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { LiveBrowserView } from '@/components/LiveBrowserView';

interface MissionStatusDetails {
    status?: string | null;
    state?: string | null;
    value?: string | null;
    team_summary?: unknown;
    active_work_items?: unknown;
    blocked_work_items?: unknown;
    coverage_summary?: unknown;
}

interface Mission {
    id: string;
    name: string;
    mission_type: string;
    status: string | MissionStatusDetails;
    schedule_cron?: string | null;
    target_urls?: string[];
    autonomy_level: string;
    approval_policy: string;
    latest_run_id?: string | null;
    last_run_at?: string | null;
    next_run_at?: string | null;
    last_error?: string | null;
    health_status?: string | null;
    paused_reason?: string | null;
    consecutive_failures?: number;
    last_heartbeat_at?: string | null;
    current_stage?: string | null;
    next_action?: string | null;
    total_runs: number;
    total_findings: number;
    budget_used_usd: number;
    max_iterations?: number;
    max_runtime_minutes?: number;
    max_llm_budget_usd?: number | null;
    team_summary?: unknown;
    active_work_items?: unknown;
    blocked_work_items?: unknown;
    coverage_summary?: unknown;
    created_at: string;
}

interface MissionForm {
    name: string;
    description: string;
    mission_type: string;
    target_urls: string;
    schedule_cron: string;
    timezone: string;
    max_runtime_minutes: number;
    max_iterations: number;
    max_llm_budget_usd: number;
}

interface FormErrors {
    name?: string;
    target_urls?: string;
}

interface Approval {
    id: string;
    mission_id: string;
    finding_id?: string | null;
    action_type: string;
    status: string;
    requested_payload?: Record<string, unknown>;
    requested_at: string;
}

interface TestProposal {
    id: string;
    title: string;
    target_url?: string | null;
    target_route?: string | null;
    route?: string | null;
    test_type: string;
    risk_level: string;
    rationale?: string | null;
    suggested_file_path?: string | null;
    approval_status: string;
    generated_spec_content?: string | null;
    materialized_file_path?: string | null;
    created_at?: string | null;
}

interface WorkItem {
    id: string;
    mission_id?: string | null;
    mission_name?: string | null;
    title?: string | null;
    summary?: string | null;
    status?: string | null;
    lane?: string | null;
    priority?: string | number | null;
    owner_agent?: string | null;
    blocked_reason?: string | null;
    progress?: Record<string, unknown> | null;
    artifacts?: Array<Record<string, unknown>> | null;
    result?: Record<string, unknown> | null;
    agent_task_id?: string | null;
    updated_at?: string | null;
    created_at?: string | null;
}

interface AgentEvent {
    id: string;
    mission_id: string;
    run_id?: string | null;
    work_item_id?: string | null;
    agent_task_id?: string | null;
    sequence: number;
    event_type: string;
    level: string;
    message: string;
    payload?: Record<string, unknown>;
    created_at: string;
}

type LiveTab = 'live' | 'browser' | 'events' | 'output' | 'runs';

const DEFAULT_FORM: MissionForm = {
    name: '',
    description: '',
    mission_type: 'exploration',
    target_urls: '',
    schedule_cron: '',
    timezone: 'UTC',
    max_runtime_minutes: 30,
    max_iterations: 0,
    max_llm_budget_usd: 5,
};

const PROPOSAL_FILTERS = ['pending', 'approved', 'materialized', 'rejected', 'all'] as const;
type ProposalFilter = typeof PROPOSAL_FILTERS[number];

const proposalFilterSet = new Set<string>(PROPOSAL_FILTERS);

const dateFormatter = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
});

const currencyFormatter = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
});

const QUICK_START_TEMPLATES: Array<{
    label: string;
    mission_type: string;
    description: string;
    schedule_cron: string;
    max_runtime_minutes: number;
    max_iterations: number;
    max_llm_budget_usd: number;
    capability: string;
    icon: ReactNode;
}> = [
    {
        label: 'Whole App Team',
        mission_type: 'mixed',
        description: 'Coordinate a compact team across app-wide discovery and coverage.',
        schedule_cron: '',
        max_runtime_minutes: 35,
        max_iterations: 0,
        max_llm_budget_usd: 8,
        capability: 'Starts a small autonomous team for whole-app discovery, active work lanes, blockers, and coverage follow-up.',
        icon: <Users size={16} />,
    },
    {
        label: 'Exploration',
        mission_type: 'exploration',
        description: 'Map key pages, flows, and interaction paths.',
        schedule_cron: '0 9 * * 1-5',
        max_runtime_minutes: 30,
        max_iterations: 0,
        max_llm_budget_usd: 5,
        capability: 'Maps known coverage gaps into reviewable exploration proposals.',
        icon: <Compass size={16} />,
    },
    {
        label: 'Continuous Watch',
        mission_type: 'mixed',
        description: 'Run around the clock with approval-gated findings.',
        schedule_cron: '',
        max_runtime_minutes: 45,
        max_iterations: 0,
        max_llm_budget_usd: 10,
        capability: 'Keeps recurring exploration, coverage review, regression watch, and flake triage alive until paused.',
        icon: <Workflow size={16} />,
    },
    {
        label: 'Coverage Gaps',
        mission_type: 'coverage',
        description: 'Look for untested routes and missing assertions.',
        schedule_cron: '0 10 * * 1-5',
        max_runtime_minutes: 25,
        max_iterations: 0,
        max_llm_budget_usd: 4,
        capability: 'Finds untested routes and turns gaps into approval-gated test proposals.',
        icon: <ClipboardCheck size={16} />,
    },
    {
        label: 'Regression Watch',
        mission_type: 'regression',
        description: 'Revisit important paths on a recurring cadence.',
        schedule_cron: '0 8 * * 1-5',
        max_runtime_minutes: 20,
        max_iterations: 0,
        max_llm_budget_usd: 3,
        capability: 'Captures a recurring regression intent while deeper execution hooks mature.',
        icon: <ShieldCheck size={16} />,
    },
    {
        label: 'Flake Triage',
        mission_type: 'flake_triage',
        description: 'Investigate unstable specs and timing-sensitive flows.',
        schedule_cron: '0 12 * * 1-5',
        max_runtime_minutes: 20,
        max_iterations: 0,
        max_llm_budget_usd: 3,
        capability: 'Records flake triage intent and keeps the approval flow ready for proposals.',
        icon: <Gauge size={16} />,
    },
];

const SCHEDULE_PRESETS = [
    { label: 'Continuous', cron: '' },
    { label: 'Business hours', cron: '0 9-17 * * 1-5' },
    { label: 'Daily', cron: '0 9 * * *' },
];

function getStoredProjectId() {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('selectedProjectId');
}

function getInitialProposalFilter(): ProposalFilter {
    if (typeof window === 'undefined') return 'pending';
    const requested = new URLSearchParams(window.location.search).get('proposalStatus');
    return requested && proposalFilterSet.has(requested) ? requested as ProposalFilter : 'pending';
}

function normalizeMissions(data: unknown): Mission[] {
    if (Array.isArray(data)) return data as Mission[];
    if (data && typeof data === 'object' && Array.isArray((data as { missions?: unknown }).missions)) {
        return (data as { missions: Mission[] }).missions;
    }
    return [];
}

function normalizeProposals(data: unknown): TestProposal[] {
    if (Array.isArray(data)) return data as TestProposal[];
    if (data && typeof data === 'object' && Array.isArray((data as { proposals?: unknown }).proposals)) {
        return (data as { proposals: TestProposal[] }).proposals;
    }
    return [];
}

function normalizeWorkItems(data: unknown): WorkItem[] {
    if (Array.isArray(data)) return data as WorkItem[];
    if (data && typeof data === 'object') {
        const payload = data as { work_items?: unknown; items?: unknown };
        if (Array.isArray(payload.work_items)) return payload.work_items as WorkItem[];
        if (Array.isArray(payload.items)) return payload.items as WorkItem[];
    }
    return [];
}

function splitTargetUrls(value: string): string[] {
    return value
        .split(/[\n,]/)
        .map(url => url.trim())
        .filter(Boolean);
}

function formatDate(value?: string | null) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '-' : dateFormatter.format(date);
}

function formatCurrency(value: number) {
    return currencyFormatter.format(value || 0);
}

function formatLimit(value?: number | null) {
    return value === 0 ? 'Unlimited' : String(value ?? '-');
}

function formatMissionType(value: string) {
    return value.replace(/_/g, ' ');
}

function getMissionStatusText(status: Mission['status']) {
    if (typeof status === 'string') return status;
    return status.status || status.state || status.value || 'unknown';
}

function getMissionStatusDetails(mission: Mission): MissionStatusDetails {
    return typeof mission.status === 'object' && mission.status ? mission.status : {};
}

function getMissionField(mission: Mission, field: keyof Pick<MissionStatusDetails, 'team_summary' | 'active_work_items' | 'blocked_work_items' | 'coverage_summary'>) {
    return mission[field] ?? getMissionStatusDetails(mission)[field];
}

function getStatusStyle(status: Mission['status'] | string | null | undefined) {
    const normalized = getMissionStatusText(status || 'unknown').toLowerCase();
    if (['running', 'active'].includes(normalized)) {
        return { color: 'var(--primary)', background: 'var(--primary-glow)' };
    }
    if (['paused', 'waiting_approval'].includes(normalized)) {
        return { color: 'var(--warning)', background: 'var(--warning-muted)' };
    }
    if (['cancelled', 'failed', 'error'].includes(normalized)) {
        return { color: 'var(--danger)', background: 'var(--danger-muted)' };
    }
    if (['completed', 'success'].includes(normalized)) {
        return { color: 'var(--success)', background: 'var(--success-muted)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(128,128,128,0.12)' };
}

function getHealthStyle(status?: string | null) {
    const normalized = (status || 'healthy').toLowerCase();
    if (normalized === 'healthy') {
        return { color: 'var(--success)', background: 'var(--success-muted)' };
    }
    if (normalized === 'degraded') {
        return { color: 'var(--warning)', background: 'var(--warning-muted)' };
    }
    if (normalized === 'blocked' || normalized === 'offline') {
        return { color: 'var(--danger)', background: 'var(--danger-muted)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(128,128,128,0.12)' };
}

function formatReason(value?: string | null) {
    return value ? value.replace(/_/g, ' ') : null;
}

function getRiskStyle(risk: string) {
    const normalized = risk.toLowerCase();
    if (normalized === 'high') {
        return { color: 'var(--danger)', background: 'var(--danger-muted)' };
    }
    if (normalized === 'medium') {
        return { color: 'var(--warning)', background: 'var(--warning-muted)' };
    }
    if (normalized === 'low') {
        return { color: 'var(--success)', background: 'var(--success-muted)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(128,128,128,0.12)' };
}

function canStart(status: Mission['status']) {
    return ['draft', 'created', 'idle', 'scheduled', 'completed', 'failed', 'error', 'cancelled'].includes(getMissionStatusText(status).toLowerCase());
}

function canPause(status: Mission['status']) {
    return ['running', 'active'].includes(getMissionStatusText(status).toLowerCase());
}

function canResume(status: Mission['status']) {
    return getMissionStatusText(status).toLowerCase() === 'paused';
}

function canCancel(status: Mission['status']) {
    return !['cancelled', 'completed'].includes(getMissionStatusText(status).toLowerCase());
}

function getProposalTarget(proposal: TestProposal) {
    return proposal.target_url || proposal.target_route || proposal.route || '-';
}

function compactSpecPreview(content?: string | null) {
    if (!content) return 'No generated spec preview available.';
    const compact = content.replace(/\s+/g, ' ').trim();
    return compact.length > 260 ? `${compact.slice(0, 260)}...` : compact;
}

function asCompactText(value: unknown, fallback = '-'): string {
    if (value === null || value === undefined || value === '') return fallback;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (Array.isArray(value)) {
        if (value.length === 0) return fallback;
        return value
            .slice(0, 3)
            .map(item => asCompactText(item, ''))
            .filter(Boolean)
            .join(', ');
    }
    if (typeof value === 'object') {
        const record = value as Record<string, unknown>;
        return String(record.summary || record.label || record.title || record.description || Object.entries(record)
            .slice(0, 3)
            .map(([key, item]) => `${key}: ${asCompactText(item, '')}`)
            .join(', ') || fallback);
    }
    return fallback;
}

function clampText(value: unknown, fallback = '-', maxLength = 96) {
    const text = asCompactText(value, fallback).replace(/\s+/g, ' ').trim();
    if (!text || text === fallback) return fallback;
    return text.length > maxLength ? `${text.slice(0, maxLength - 3).trim()}...` : text;
}

function getMissionPrimaryTarget(mission: Mission) {
    const firstTarget = mission.target_urls?.[0];
    if (!firstTarget) return 'No target configured';
    const extraCount = (mission.target_urls?.length || 0) - 1;
    return extraCount > 0 ? `${firstTarget} +${extraCount}` : firstTarget;
}

function toggleSetItem(current: Set<string>, id: string) {
    const next = new Set(current);
    if (next.has(id)) {
        next.delete(id);
    } else {
        next.add(id);
    }
    return next;
}

function getWorkItemCount(value: unknown) {
    if (Array.isArray(value)) return value.length;
    if (typeof value === 'number') return value;
    if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>;
        const count = record.count ?? record.total;
        if (typeof count === 'number') return count;
        if (Array.isArray(record.items)) return record.items.length;
    }
    return 0;
}

function eventLabel(value: string) {
    return value.replace(/_/g, ' ');
}

function getEventTone(event: AgentEvent) {
    if (event.level === 'error' || event.event_type === 'error') return 'danger';
    if (event.event_type === 'browser_action') return 'primary';
    if (event.event_type === 'pause') return 'warning';
    if (event.event_type === 'resume' || event.event_type === 'complete') return 'success';
    return 'neutral';
}

function getEventStatusStyle(event: AgentEvent) {
    const tone = getEventTone(event);
    if (tone === 'danger') return getStatusStyle('failed');
    if (tone === 'warning') return getStatusStyle('paused');
    if (tone === 'success') return getStatusStyle('completed');
    if (tone === 'primary') return getStatusStyle('running');
    return getStatusStyle('unknown');
}

function buildEventOutput(events: AgentEvent[]) {
    return events
        .filter(event => event.event_type === 'assistant_output')
        .map(event => event.message)
        .join('\n\n');
}

function getFinalWorkItemOutput(item: WorkItem) {
    const resultOutput = item.result?.output;
    if (typeof resultOutput === 'string' && resultOutput.trim()) return resultOutput;
    const artifact = item.artifacts?.find(entry => typeof entry.content === 'string' && entry.content.trim());
    return typeof artifact?.content === 'string' ? artifact.content : '';
}

function parseSseMessages(buffer: string) {
    const chunks = buffer.split('\n\n');
    return {
        messages: chunks.slice(0, -1),
        remainder: chunks[chunks.length - 1] || '',
    };
}

export default function AutonomousMissionsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const projectId = currentProject?.id || getStoredProjectId() || 'default';
    const encodedProjectId = encodeURIComponent(projectId);
    const missionsUrl = `${API_BASE}/autonomous/${encodedProjectId}/missions`;
    const proposalsUrl = `${API_BASE}/autonomous/${encodedProjectId}/proposals`;
    const workItemsUrl = `${API_BASE}/autonomous/${encodedProjectId}/work-items?limit=8`;

    const [missions, setMissions] = useState<Mission[]>([]);
    const [approvals, setApprovals] = useState<Approval[]>([]);
    const [proposals, setProposals] = useState<TestProposal[]>([]);
    const [workItems, setWorkItems] = useState<WorkItem[]>([]);
    const [proposalFilter, setProposalFilter] = useState<ProposalFilter>(getInitialProposalFilter);
    const [proposalLoadError, setProposalLoadError] = useState<string | null>(null);
    const [approvalsLoadError, setApprovalsLoadError] = useState<string | null>(null);
    const [materializeProposal, setMaterializeProposal] = useState<TestProposal | null>(null);
    const [materializePath, setMaterializePath] = useState('');
    const [materializeOverwrite, setMaterializeOverwrite] = useState(false);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [createStep, setCreateStep] = useState(1);
    const [form, setForm] = useState<MissionForm>(DEFAULT_FORM);
    const [formErrors, setFormErrors] = useState<FormErrors>({});
    const [selectedTemplateLabel, setSelectedTemplateLabel] = useState(QUICK_START_TEMPLATES[0]?.label || '');
    const [expandedMissionIds, setExpandedMissionIds] = useState<Set<string>>(new Set());
    const [expandedProposalIds, setExpandedProposalIds] = useState<Set<string>>(new Set());
    const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
    const [liveTab, setLiveTab] = useState<LiveTab>('live');
    const [missionEvents, setMissionEvents] = useState<AgentEvent[]>([]);
    const [streamStatus, setStreamStatus] = useState<'idle' | 'connecting' | 'connected' | 'closed' | 'error'>('idle');
    const [streamError, setStreamError] = useState<string | null>(null);
    const [creating, setCreating] = useState(false);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const fetchMissions = useCallback(async () => {
        setError(null);
        try {
            const response = await fetchWithAuth(missionsUrl);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load missions');
            }
            const data = await response.json();
            setMissions(normalizeMissions(data));
        } catch (err) {
            console.error('Failed to load autonomous missions:', err);
            setError(err instanceof Error ? err.message : 'Failed to load missions');
        }
    }, [missionsUrl]);

    const fetchApprovals = useCallback(async () => {
        setApprovalsLoadError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/approvals?status=pending`);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load approvals');
            }
            const data = await response.json();
            setApprovals(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Failed to load autonomous approvals:', err);
            setApprovalsLoadError(err instanceof Error ? err.message : 'Failed to load approvals');
        }
    }, [encodedProjectId]);

    const fetchProposals = useCallback(async () => {
        setProposalLoadError(null);
        try {
            const url = proposalFilter === 'all' ? proposalsUrl : `${proposalsUrl}?status=${proposalFilter}`;
            const response = await fetchWithAuth(url);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load generated test proposals');
            }
            const data = await response.json();
            setProposals(normalizeProposals(data));
        } catch (err) {
            console.error('Failed to load autonomous test proposals:', err);
            setProposalLoadError(err instanceof Error ? err.message : 'Failed to load generated test proposals');
        }
    }, [proposalFilter, proposalsUrl]);

    const fetchWorkItems = useCallback(async () => {
        try {
            const response = await fetchWithAuth(workItemsUrl);
            if (response.status === 404 || response.status === 405) {
                setWorkItems([]);
                return;
            }
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load work items');
            }
            const data = await response.json();
            setWorkItems(normalizeWorkItems(data));
        } catch (err) {
            console.error('Failed to load autonomous work items:', err);
            setWorkItems([]);
        }
    }, [workItemsUrl]);

    const refreshAll = useCallback(async () => {
        await Promise.all([fetchMissions(), fetchApprovals(), fetchProposals(), fetchWorkItems()]);
    }, [fetchApprovals, fetchMissions, fetchProposals, fetchWorkItems]);

    useEffect(() => {
        setLoading(true);
        refreshAll().finally(() => setLoading(false));
    }, [refreshAll]);

    useEffect(() => {
        if (!selectedMissionId) {
            setMissionEvents([]);
            setStreamStatus('idle');
            setStreamError(null);
            return;
        }

        const controller = new AbortController();
        let cancelled = false;
        const missionId = selectedMissionId;

        async function connectEventStream() {
            setMissionEvents([]);
            setStreamStatus('connecting');
            setStreamError(null);
            try {
                const response = await fetchWithAuth(
                    `${missionsUrl}/${encodeURIComponent(missionId)}/events/stream`,
                    { signal: controller.signal }
                );
                if (!response.ok) {
                    throw new Error(await response.text() || 'Failed to connect to mission event stream');
                }
                if (!response.body) {
                    throw new Error('Mission event stream is unavailable');
                }

                setStreamStatus('connected');
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (!cancelled) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parsed = parseSseMessages(buffer);
                    buffer = parsed.remainder;
                    parsed.messages.forEach(message => {
                        const dataLine = message
                            .split('\n')
                            .find(line => line.startsWith('data:'));
                        if (!dataLine) return;
                        try {
                            const payload = JSON.parse(dataLine.slice(5).trim());
                            if (payload.status === 'connected') {
                                setStreamStatus('connected');
                            } else if (payload.status === 'complete') {
                                setStreamStatus('closed');
                            } else if (payload.status === 'error') {
                                setStreamStatus('error');
                                setStreamError(payload.message || 'Mission event stream failed');
                            } else if (payload.event) {
                                const event = payload.event as AgentEvent;
                                setMissionEvents(prev => {
                                    if (prev.some(existing => existing.id === event.id)) return prev;
                                    return [...prev, event].sort((a, b) => a.sequence - b.sequence).slice(-500);
                                });
                            }
                        } catch (err) {
                            console.error('Failed to parse autonomous event stream payload:', err);
                        }
                    });
                }
                if (!cancelled) setStreamStatus(current => current === 'connected' ? 'closed' : current);
            } catch (err) {
                if (controller.signal.aborted || cancelled) return;
                console.error('Autonomous event stream failed:', err);
                setStreamStatus('error');
                setStreamError(err instanceof Error ? err.message : 'Mission event stream failed');
            }
        }

        connectEventStream();
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [missionsUrl, selectedMissionId]);

    useEffect(() => {
        if (!showCreate && !materializeProposal) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setShowCreate(false);
                setMaterializeProposal(null);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [materializeProposal, showCreate]);

    const handleRefresh = async () => {
        setRefreshing(true);
        await refreshAll().finally(() => setRefreshing(false));
    };

    const handleProposalFilterChange = (filter: ProposalFilter) => {
        setProposalFilter(filter);
        if (typeof window === 'undefined') return;
        const params = new URLSearchParams(window.location.search);
        if (filter === 'pending') {
            params.delete('proposalStatus');
        } else {
            params.set('proposalStatus', filter);
        }
        const query = params.toString();
        window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
    };

    const applyMissionTemplate = (template: typeof QUICK_START_TEMPLATES[number]) => {
        setForm(prev => ({
            ...prev,
            name: prev.name || `${template.label} mission`,
            mission_type: template.mission_type,
            description: prev.description || template.description,
            schedule_cron: template.schedule_cron,
            timezone: 'UTC',
            max_runtime_minutes: template.max_runtime_minutes,
            max_iterations: template.max_iterations,
            max_llm_budget_usd: template.max_llm_budget_usd,
        }));
        setFormErrors({});
        setSelectedTemplateLabel(template.label);
        setCreateStep(2);
        setShowCreate(true);
    };

    const totals = useMemo(() => {
        return missions.reduce(
            (acc, mission) => {
                acc.runs += mission.total_runs || 0;
                acc.findings += mission.total_findings || 0;
                acc.budget += mission.budget_used_usd || 0;
                if (canPause(mission.status)) acc.running += 1;
                acc.activeWorkItems += getWorkItemCount(getMissionField(mission, 'active_work_items'));
                acc.blockedWorkItems += getWorkItemCount(getMissionField(mission, 'blocked_work_items'));
                return acc;
            },
            { runs: 0, findings: 0, budget: 0, running: 0, activeWorkItems: 0, blockedWorkItems: 0 }
        );
    }, [missions]);

    const hasMissions = missions.length > 0;
    const selectedMission = missions.find(mission => mission.id === selectedMissionId) || null;
    const selectedMissionWorkItems = workItems.filter(item => item.mission_id === selectedMissionId);
    const selectedMissionActiveWorkItems = selectedMissionWorkItems.filter(item => ['queued', 'running'].includes((item.status || '').toLowerCase()));
    const selectedMissionFinalOutputs = selectedMissionWorkItems
        .map(item => ({ item, output: getFinalWorkItemOutput(item) }))
        .filter(entry => entry.output.trim());
    const latestEvent = missionEvents[missionEvents.length - 1];
    const liveAgentOutput = buildEventOutput(missionEvents);
    const latestBrowserEvent = [...missionEvents].reverse().find(event => event.event_type === 'browser_action');
    const selectedTemplate = QUICK_START_TEMPLATES.find(template => template.label === selectedTemplateLabel)
        || QUICK_START_TEMPLATES.find(template => template.mission_type === form.mission_type)
        || QUICK_START_TEMPLATES[0];
    const degradedMissions = missions.filter(mission => {
        const health = (mission.health_status || 'healthy').toLowerCase();
        return health !== 'healthy' || Boolean(mission.last_error) || Boolean(mission.paused_reason);
    });
    const approvedProposals = proposals.filter(proposal => (proposal.approval_status || '').toLowerCase() === 'approved');
    const dashboardStats = [
        { label: 'Running', value: totals.running, icon: <Play size={16} /> },
        { label: 'Blocked', value: totals.blockedWorkItems, icon: <AlertCircle size={16} /> },
        { label: 'Approvals', value: approvals.length, icon: <CheckCircle size={16} /> },
        { label: 'Proposals', value: proposals.length, icon: <FileText size={16} /> },
        { label: 'Budget', value: formatCurrency(totals.budget), icon: <DollarSign size={16} /> },
    ];
    const attentionItems = [
        {
            label: 'Pending approvals',
            value: approvals.length,
            detail: approvals.length > 0 ? 'Approve or reject requested actions' : 'No approval queue',
            icon: <CheckCircle size={16} />,
            tone: approvals.length > 0 ? 'warning' : 'neutral',
        },
        {
            label: 'Blocked work',
            value: totals.blockedWorkItems,
            detail: totals.blockedWorkItems > 0 ? 'Agent lanes need review' : 'No blockers reported',
            icon: <AlertCircle size={16} />,
            tone: totals.blockedWorkItems > 0 ? 'danger' : 'neutral',
        },
        {
            label: 'Mission health',
            value: degradedMissions.length,
            detail: degradedMissions.length > 0 ? 'Missions need attention' : 'All missions healthy',
            icon: <ShieldCheck size={16} />,
            tone: degradedMissions.length > 0 ? 'warning' : 'neutral',
        },
        {
            label: 'Ready to materialize',
            value: approvedProposals.length,
            detail: approvedProposals.length > 0 ? 'Approved tests can become files' : 'Nothing ready',
            icon: <UploadCloud size={16} />,
            tone: approvedProposals.length > 0 ? 'primary' : 'neutral',
        },
    ];

    const handleCreate = async (event: FormEvent) => {
        event.preventDefault();
        const targetUrls = splitTargetUrls(form.target_urls);
        const nextFormErrors: FormErrors = {};
        if (!form.name.trim()) {
            nextFormErrors.name = 'Give this mission a short, recognizable name.';
        }
        if (targetUrls.length === 0) {
            nextFormErrors.target_urls = 'Add at least one URL the backend can reach.';
        }
        setFormErrors(nextFormErrors);
        if (Object.keys(nextFormErrors).length > 0) {
            setError(null);
            return;
        }

        setCreating(true);
        setError(null);
        try {
            const isWholeAppTeam = selectedTemplate?.label === 'Whole App Team';
            const payload = {
                name: form.name.trim(),
                description: form.description.trim() || undefined,
                mission_type: form.mission_type,
                target_urls: targetUrls,
                schedule_cron: form.schedule_cron.trim() || undefined,
                timezone: form.timezone || 'UTC',
                max_runtime_minutes: form.max_runtime_minutes,
                max_iterations: form.max_iterations,
                max_llm_budget_usd: form.max_llm_budget_usd,
                autonomy_level: 'draft_validate',
                approval_policy: 'approval_required',
                config: isWholeAppTeam ? {
                    whole_app_team: true,
                    team_mode: 'whole_app',
                    mission_template: 'whole_app_team',
                    max_parallel_agents: 2,
                    loop_delay_seconds: 300,
                    max_pending_approvals: 25,
                    roles: [
                        'surface_mapper',
                        'explorer',
                        'requirements_analyst',
                        'rtm_mapper',
                        'spec_writer',
                        'regression_scout',
                        'flake_triager',
                    ],
                    completion_target: {
                        rtm_coverage_percentage: 95,
                        critical_gaps: 0,
                    },
                } : {},
            };

            const response = await fetchWithAuth(missionsUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to create mission');
            }
            setForm(DEFAULT_FORM);
            setFormErrors({});
            setSelectedTemplateLabel(QUICK_START_TEMPLATES[0]?.label || '');
            setCreateStep(1);
            setShowCreate(false);
            await refreshAll();
        } catch (err) {
            console.error('Failed to create autonomous mission:', err);
            setError(err instanceof Error ? err.message : 'Failed to create mission');
        } finally {
            setCreating(false);
        }
    };

    const handleMissionAction = async (mission: Mission, action: 'start' | 'pause' | 'resume' | 'cancel') => {
        const label = `${mission.id}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${missionsUrl}/${encodeURIComponent(mission.id)}/${action}`, {
                method: 'POST',
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} mission`);
            }
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${action} autonomous mission:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} mission`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleApproval = async (approval: Approval, decision: 'approve' | 'reject') => {
        const label = `${approval.id}:${decision}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/approvals/${approval.id}/${decision}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ comment: `Decision from Autonomous Missions dashboard: ${decision}` }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${decision} approval`);
            }
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${decision} autonomous approval:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${decision} approval`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleProposalAction = async (proposal: TestProposal, action: 'approve' | 'reject') => {
        const label = `${proposal.id}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/${encodeURIComponent(proposal.id)}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ comment: `Decision from Autonomous Missions dashboard: ${action}` }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} proposal`);
            }
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${action} autonomous test proposal:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} proposal`);
        } finally {
            setActionLoading(null);
        }
    };

    const openMaterializeDialog = (proposal: TestProposal) => {
        setMaterializeProposal(proposal);
        setMaterializePath(proposal.suggested_file_path || '');
        setMaterializeOverwrite(false);
        setError(null);
    };

    const handleMaterializeConfirm = async (event: FormEvent) => {
        event.preventDefault();
        if (!materializeProposal) return;
        const label = `${materializeProposal.id}:materialize`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/${encodeURIComponent(materializeProposal.id)}/materialize`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_path: materializePath.trim() || undefined,
                    overwrite: materializeOverwrite,
                    comment: 'Materialized from Autonomous Missions dashboard',
                }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to materialize proposal');
            }
            setMaterializeProposal(null);
            setMaterializePath('');
            setMaterializeOverwrite(false);
            await refreshAll();
        } catch (err) {
            console.error('Failed to materialize autonomous test proposal:', err);
            const message = err instanceof Error ? err.message : 'Failed to materialize proposal';
            setError(message);
            if (message.includes('already exists')) {
                setMaterializeOverwrite(true);
            }
        } finally {
            setActionLoading(null);
        }
    };

    if (loading || projectLoading) {
        return (
            <PageLayout tier="wide">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Autonomous Missions"
                subtitle="Create and control recurring agent missions for the current project"
                icon={<Bot size={20} />}
                actions={
                    <div className="am-header-actions" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <button
                            type="button"
                            className="am-header-button"
                            onClick={handleRefresh}
                            disabled={refreshing}
                            style={{
                                padding: '0.5rem 0.75rem',
                                background: 'transparent',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                cursor: refreshing ? 'not-allowed' : 'pointer',
                                color: 'var(--text-secondary)',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                fontSize: '0.85rem',
                                opacity: refreshing ? 0.7 : 1,
                            }}
                        >
                            <RefreshCw size={14} className={refreshing ? 'am-spin' : undefined} />
                            Refresh
                        </button>
                        <button
                            type="button"
                            className="am-header-button"
                            onClick={() => {
                                setCreateStep(1);
                                setShowCreate(true);
                            }}
                            style={{
                                padding: '0.5rem 1rem',
                                background: 'var(--primary)',
                                color: 'white',
                                border: 'none',
                                borderRadius: 'var(--radius)',
                                cursor: 'pointer',
                                fontWeight: 600,
                                fontSize: '0.85rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                            }}
                        >
                            <Plus size={16} />
                            New Mission
                        </button>
                    </div>
                }
            />

            <div aria-live="polite">
                {error && (
                    <div className="am-alert am-alert-danger">
                        <AlertCircle size={16} />
                        <span>{error}</span>
                    </div>
                )}
            </div>

            {hasMissions && (
                <div className="am-stat-grid">
                    <div className="am-stat-card am-stat-card-primary">
                        <div className="am-stat-icon"><Target size={16} /></div>
                        <div>
                            <div className="am-stat-value">{missions.length}</div>
                            <div className="am-stat-label">Missions</div>
                        </div>
                    </div>
                    {dashboardStats.map(item => (
                        <div key={item.label} className="am-stat-card">
                            <div className="am-stat-icon">{item.icon}</div>
                            <div>
                                <div className="am-stat-value">{item.value}</div>
                                <div className="am-stat-label">{item.label}</div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {hasMissions && (
                <section className="am-attention-strip" aria-label="Needs attention">
                    {attentionItems.map(item => (
                        <div key={item.label} className={`am-attention-card am-attention-${item.tone}`}>
                            <div className="am-attention-icon">{item.icon}</div>
                            <div className="am-attention-copy">
                                <strong>{item.value}</strong>
                                <span>{item.label}</span>
                                <small>{item.detail}</small>
                            </div>
                        </div>
                    ))}
                </section>
            )}

            {approvalsLoadError && (
                <div className="am-alert am-alert-danger">
                    {approvalsLoadError}
                </div>
            )}

            {approvals.length > 0 && (
                <section className="am-panel am-queue-panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <CheckCircle size={17} style={{ color: 'var(--warning)' }} />
                            <div>
                                <h2>Approval Queue</h2>
                                <p>{approvals.length} pending action{approvals.length === 1 ? '' : 's'}</p>
                            </div>
                        </div>
                    </div>
                    <div className="am-inline-list">
                        {approvals.slice(0, 4).map(approval => (
                            <div key={approval.id} className="am-inline-item">
                                <div className="am-inline-copy">
                                    <strong>{approval.action_type.replace(/_/g, ' ')}</strong>
                                    <span>{clampText(approval.requested_payload?.action || approval.requested_payload?.suggested_test || approval.finding_id || approval.id, 'Approval request', 110)}</span>
                                </div>
                                <div className="am-action-group">
                                    <MissionActionButton
                                        icon={<CheckCircle size={13} />}
                                        label="Approve"
                                        color="var(--success)"
                                        loading={actionLoading === `${approval.id}:approve`}
                                        onClick={() => handleApproval(approval, 'approve')}
                                    />
                                    <MissionActionButton
                                        icon={<XCircle size={13} />}
                                        label="Reject"
                                        color="var(--danger)"
                                        loading={actionLoading === `${approval.id}:reject`}
                                        onClick={() => handleApproval(approval, 'reject')}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {!hasMissions ? (
                <section className="am-panel am-empty-state">
                    <div className="am-empty-icon"><Bot size={24} /></div>
                    <h2>No Autonomous Missions Yet</h2>
                    <p>Create a mission to start recurring exploration, coverage review, and approval-gated test proposals for this project.</p>
                    <button
                        type="button"
                        className="am-button am-button-primary"
                        onClick={() => {
                            setCreateStep(1);
                            setShowCreate(true);
                        }}
                    >
                        <Plus size={15} />
                        New Mission
                    </button>
                </section>
            ) : (
                <section className="am-panel am-mission-panel">
                    <div className="am-section-title-row">
                        <div>
                            <div className="am-kicker">Mission control</div>
                            <h2>Active Missions</h2>
                            <p>Scan health, timing, blockers, and the next action without opening every mission.</p>
                        </div>
                    </div>
                    <div className="am-mission-list">
                        {missions.map(mission => {
                            const statusStyle = getStatusStyle(mission.status);
                            const healthStyle = getHealthStyle(mission.health_status);
                            const statusText = getMissionStatusText(mission.status);
                            const teamSummary = getMissionField(mission, 'team_summary');
                            const activeWorkItems = getMissionField(mission, 'active_work_items');
                            const blockedWorkItems = getMissionField(mission, 'blocked_work_items');
                            const coverageSummary = getMissionField(mission, 'coverage_summary');
                            const hasTeamStatus = Boolean(teamSummary || activeWorkItems || blockedWorkItems || coverageSummary);
                            const expanded = expandedMissionIds.has(mission.id);
                            return (
                                <article key={mission.id} className="am-mission-row">
                                    <div className="am-mission-row-main">
                                        <div className="am-mission-identity">
                                            <button
                                                type="button"
                                                className="am-expand-button"
                                                aria-label={`${expanded ? 'Collapse' : 'Expand'} ${mission.name}`}
                                                aria-expanded={expanded}
                                                onClick={() => setExpandedMissionIds(current => toggleSetItem(current, mission.id))}
                                            >
                                                {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            </button>
                                            <div className="am-mission-title-block">
                                                <h3>{mission.name}</h3>
                                                <div className="am-row-subtitle">{formatMissionType(mission.mission_type)}</div>
                                            </div>
                                        </div>
                                        <div className="am-mission-target" title={getMissionPrimaryTarget(mission)}>
                                            {getMissionPrimaryTarget(mission)}
                                        </div>
                                        <div className="am-mission-statuses">
                                            <span className="am-pill" style={{ color: healthStyle.color, background: healthStyle.background }}>
                                                {mission.health_status || 'healthy'}
                                            </span>
                                            <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                {statusText.replace(/_/g, ' ')}
                                            </span>
                                        </div>
                                        <div className="am-row-metrics">
                                            <div>
                                                <span>Stage</span>
                                                <strong>{formatReason(mission.current_stage) || 'idle'}</strong>
                                            </div>
                                            <div>
                                                <span>Next Run</span>
                                                <strong>{formatDate(mission.next_run_at)}</strong>
                                            </div>
                                            <div>
                                                <span>Findings</span>
                                                <strong>{mission.total_findings || 0}</strong>
                                            </div>
                                        </div>
                                        <div className="am-card-actions">
                                            <MissionActionButton
                                                icon={<Terminal size={13} />}
                                                label="Live"
                                                color="var(--primary)"
                                                loading={false}
                                                onClick={() => {
                                                    setSelectedMissionId(mission.id);
                                                    setLiveTab('live');
                                                }}
                                            />
                                            {canStart(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Play size={13} />}
                                                    label="Start"
                                                    color="var(--success)"
                                                    loading={actionLoading === `${mission.id}:start`}
                                                    onClick={() => handleMissionAction(mission, 'start')}
                                                />
                                            )}
                                            {canPause(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Pause size={13} />}
                                                    label="Pause"
                                                    color="var(--warning)"
                                                    loading={actionLoading === `${mission.id}:pause`}
                                                    onClick={() => handleMissionAction(mission, 'pause')}
                                                />
                                            )}
                                            {canResume(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Play size={13} />}
                                                    label="Resume"
                                                    color="var(--success)"
                                                    loading={actionLoading === `${mission.id}:resume`}
                                                    onClick={() => handleMissionAction(mission, 'resume')}
                                                />
                                            )}
                                            {canCancel(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Square size={13} />}
                                                    label="Cancel"
                                                    color="var(--danger)"
                                                    loading={actionLoading === `${mission.id}:cancel`}
                                                    onClick={() => handleMissionAction(mission, 'cancel')}
                                                />
                                            )}
                                        </div>
                                    </div>

                                    {expanded && (
                                        <div className="am-mission-details">
                                            <div className="am-health-panel">
                                                <div>
                                                    <span>Last Run</span>
                                                    <strong>{formatDate(mission.last_run_at)}</strong>
                                                </div>
                                                <div>
                                                    <span>Heartbeat</span>
                                                    <strong>{formatDate(mission.last_heartbeat_at)}</strong>
                                                </div>
                                                <div>
                                                    <span>Budget</span>
                                                    <strong>{formatCurrency(mission.budget_used_usd || 0)}</strong>
                                                </div>
                                                <div>
                                                    <span>Runs / Limit</span>
                                                    <strong>{mission.total_runs || 0} / {formatLimit(mission.max_iterations)}</strong>
                                                </div>
                                                <div>
                                                    <span>Failures</span>
                                                    <strong>{mission.consecutive_failures || 0}</strong>
                                                </div>
                                            </div>

                                            {hasTeamStatus && (
                                                <div className="am-team-panel">
                                                    <div className="am-team-summary">
                                                        <Users size={14} />
                                                        <span>{clampText(teamSummary, 'Team status pending', 160)}</span>
                                                    </div>
                                                    <div className="am-work-lanes">
                                                        <div>
                                                            <span>Active</span>
                                                            <strong>{getWorkItemCount(activeWorkItems)}</strong>
                                                            <small>{clampText(activeWorkItems, 'No active items', 90)}</small>
                                                        </div>
                                                        <div>
                                                            <span>Blocked</span>
                                                            <strong>{getWorkItemCount(blockedWorkItems)}</strong>
                                                            <small>{clampText(blockedWorkItems, 'No blockers', 90)}</small>
                                                        </div>
                                                        <div>
                                                            <span>Coverage</span>
                                                            <strong>{clampText(coverageSummary, 'Pending', 110)}</strong>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {(mission.paused_reason || mission.next_action) && (
                                                <div className="am-mission-note">
                                                    <Workflow size={14} />
                                                    <span>
                                                        {formatReason(mission.paused_reason) || mission.next_action}
                                                        {mission.paused_reason && mission.next_action ? `: ${mission.next_action}` : ''}
                                                    </span>
                                                </div>
                                            )}

                                            {mission.last_error && (
                                                <div className="am-mission-error">
                                                    <AlertCircle size={14} />
                                                    <span>{clampText(mission.last_error, 'Mission error', 220)}</span>
                                                </div>
                                            )}

                                            <div className="am-metadata-row">
                                                <span>{mission.autonomy_level}</span>
                                                <span>{mission.approval_policy}</span>
                                                {mission.schedule_cron && <span>{mission.schedule_cron}</span>}
                                                {mission.latest_run_id && <span>Run {clampText(mission.latest_run_id, '-', 28)}</span>}
                                            </div>
                                        </div>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                </section>
            )}

            {selectedMission && (
                <section className="am-panel am-live-panel" aria-label="Live mission debug panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Terminal size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>{selectedMission.name}</h2>
                                <p>
                                    {streamStatus === 'connected' ? 'Live stream connected' : streamStatus === 'closed' ? 'Stream closed' : streamStatus}
                                    {latestEvent ? ` · ${eventLabel(latestEvent.event_type)} · ${formatDate(latestEvent.created_at)}` : ''}
                                </p>
                            </div>
                        </div>
                        <div className="am-action-group">
                            {canPause(selectedMission.status) && (
                                <MissionActionButton
                                    icon={<Pause size={13} />}
                                    label="Pause"
                                    color="var(--warning)"
                                    loading={actionLoading === `${selectedMission.id}:pause`}
                                    onClick={() => handleMissionAction(selectedMission, 'pause')}
                                />
                            )}
                            {canResume(selectedMission.status) && (
                                <MissionActionButton
                                    icon={<Play size={13} />}
                                    label="Resume"
                                    color="var(--success)"
                                    loading={actionLoading === `${selectedMission.id}:resume`}
                                    onClick={() => handleMissionAction(selectedMission, 'resume')}
                                />
                            )}
                            {canCancel(selectedMission.status) && (
                                <MissionActionButton
                                    icon={<Square size={13} />}
                                    label="Cancel"
                                    color="var(--danger)"
                                    loading={actionLoading === `${selectedMission.id}:cancel`}
                                    onClick={() => handleMissionAction(selectedMission, 'cancel')}
                                />
                            )}
                            <button
                                type="button"
                                className="am-icon-button"
                                aria-label="Close live mission panel"
                                onClick={() => setSelectedMissionId(null)}
                            >
                                <X size={16} />
                            </button>
                        </div>
                    </div>

                    <div className="am-live-tabs" role="tablist" aria-label="Live mission debug views">
                        {(['live', 'browser', 'events', 'output', 'runs'] as LiveTab[]).map(tab => (
                            <button
                                key={tab}
                                type="button"
                                role="tab"
                                aria-selected={liveTab === tab}
                                className={liveTab === tab ? 'am-live-tab is-active' : 'am-live-tab'}
                                onClick={() => setLiveTab(tab)}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>

                    {streamError && (
                        <div className="am-alert am-alert-danger">
                            <AlertCircle size={16} />
                            <span>{streamError}</span>
                        </div>
                    )}

                    {liveTab === 'live' && (
                        <div className="am-live-grid">
                            <div className="am-live-summary">
                                <div>
                                    <span>Status</span>
                                    <strong>{getMissionStatusText(selectedMission.status)}</strong>
                                </div>
                                <div>
                                    <span>Stage</span>
                                    <strong>{formatReason(selectedMission.current_stage) || 'idle'}</strong>
                                </div>
                                <div>
                                    <span>Heartbeat</span>
                                    <strong>{formatDate(selectedMission.last_heartbeat_at)}</strong>
                                </div>
                                <div>
                                    <span>Active work</span>
                                    <strong>{selectedMissionActiveWorkItems.length}</strong>
                                </div>
                                <div>
                                    <span>Last tool</span>
                                    <strong>{clampText(latestEvent?.payload?.short_name || latestEvent?.payload?.tool_name, 'None', 44)}</strong>
                                </div>
                                <div>
                                    <span>Browser</span>
                                    <strong>{latestBrowserEvent ? eventLabel(String(latestBrowserEvent.payload?.short_name || latestBrowserEvent.message)) : 'No action'}</strong>
                                </div>
                            </div>
                            <pre className="am-live-output">
                                {liveAgentOutput || latestEvent?.message || 'Waiting for live agent output...'}
                            </pre>
                        </div>
                    )}

                    {liveTab === 'browser' && (
                        <div className="am-browser-panel">
                            <LiveBrowserView
                                runId={selectedMission.latest_run_id || selectedMission.id}
                                isActive={canPause(selectedMission.status)}
                                showHeader
                            />
                        </div>
                    )}

                    {liveTab === 'events' && (
                        <div className="am-event-list">
                            {missionEvents.length === 0 ? (
                                <div className="am-empty-inline">Waiting for mission events...</div>
                            ) : missionEvents.slice(-120).map(event => {
                                const style = getEventStatusStyle(event);
                                return (
                                    <div key={event.id} className="am-event-row">
                                        <span className="am-event-sequence">#{event.sequence}</span>
                                        <span className="am-pill" style={{ color: style.color, background: style.background }}>
                                            {eventLabel(event.event_type)}
                                        </span>
                                        <div className="am-event-copy">
                                            <strong>{clampText(event.message, 'Event', 180)}</strong>
                                            <span>{formatDate(event.created_at)}{event.work_item_id ? ` · ${event.work_item_id}` : ''}</span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {liveTab === 'output' && (
                        <div className="am-output-list">
                            {selectedMissionFinalOutputs.length === 0 ? (
                                <pre className="am-live-output">{liveAgentOutput || 'Final agent output will appear after work items complete.'}</pre>
                            ) : selectedMissionFinalOutputs.map(({ item, output }) => (
                                <div key={item.id} className="am-output-card">
                                    <div className="am-output-title">{item.owner_agent || item.title || item.id}</div>
                                    <pre className="am-live-output">{output}</pre>
                                </div>
                            ))}
                        </div>
                    )}

                    {liveTab === 'runs' && (
                        <div className="am-live-summary">
                            <div>
                                <span>Latest run</span>
                                <strong>{selectedMission.latest_run_id || '-'}</strong>
                            </div>
                            <div>
                                <span>Total runs</span>
                                <strong>{selectedMission.total_runs || 0}</strong>
                            </div>
                            <div>
                                <span>Runtime limit</span>
                                <strong>{selectedMission.max_runtime_minutes || '-'} min</strong>
                            </div>
                            <div>
                                <span>Budget</span>
                                <strong>{formatCurrency(selectedMission.budget_used_usd || 0)}</strong>
                            </div>
                            <div>
                                <span>Next action</span>
                                <strong>{clampText(selectedMission.next_action, 'None', 120)}</strong>
                            </div>
                        </div>
                    )}
                </section>
            )}

            {workItems.length > 0 && (
                <section className="am-panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Workflow size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>Recent Work Items</h2>
                                <p>{workItems.length} latest team lane update{workItems.length === 1 ? '' : 's'}</p>
                            </div>
                        </div>
                    </div>
                    <div className="am-work-item-list">
                        {workItems.map((item, index) => {
                            const status = item.status || item.lane || 'open';
                            const statusStyle = getStatusStyle(status);
                            const missionName = item.mission_name || missions.find(mission => mission.id === item.mission_id)?.name;
                            return (
                                <div key={item.id || `${item.mission_id || 'work'}:${index}`} className="am-work-item">
                                    <div style={{ minWidth: 0 }}>
                                        <div className="am-work-item-title">
                                            {clampText(item.title || item.summary, 'Untitled work item', 120)}
                                        </div>
                                        <div className="am-work-item-meta">
                                            {missionName && <span>{missionName}</span>}
                                            {item.owner_agent && <span>{item.owner_agent}</span>}
                                            {item.priority && <span>{item.priority}</span>}
                                            <span>{formatDate(item.updated_at || item.created_at)}</span>
                                        </div>
                                        {item.blocked_reason && (
                                            <div className="am-work-item-blocker">
                                                {clampText(item.blocked_reason, 'Blocked', 160)}
                                            </div>
                                        )}
                                    </div>
                                    <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                        {status.replace(/_/g, ' ')}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {(hasMissions || proposals.length > 0 || proposalLoadError) && (
                <section className="am-panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <FileText size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>Generated Test Proposals</h2>
                                <p>{proposals.length} total</p>
                            </div>
                        </div>
                    </div>
                    <div className="am-filter-row" role="group" aria-label="Proposal status filter">
                        {PROPOSAL_FILTERS.map(filter => (
                            <button
                                key={filter}
                                type="button"
                                aria-pressed={proposalFilter === filter}
                                onClick={() => handleProposalFilterChange(filter)}
                                className={proposalFilter === filter ? 'am-filter is-active' : 'am-filter'}
                            >
                                {filter}
                            </button>
                        ))}
                    </div>

                    {proposalLoadError ? (
                        <div className="am-alert am-alert-danger">
                            {proposalLoadError}
                        </div>
                    ) : proposals.length === 0 ? (
                        <div className="am-empty-inline">
                            No generated test proposals for this filter.
                        </div>
                    ) : (
                        <div className="am-proposal-list">
                            {proposals.map(proposal => {
                                const approvalStatus = proposal.approval_status || 'unknown';
                                const riskLevel = proposal.risk_level || 'unknown';
                                const statusStyle = getStatusStyle(approvalStatus);
                                const riskStyle = getRiskStyle(riskLevel);
                                const status = approvalStatus.toLowerCase();
                                const canDecideProposal = status === 'pending';
                                const canMaterializeProposal = status === 'approved';
                                const expanded = expandedProposalIds.has(proposal.id);

                                return (
                                    <article key={proposal.id} className="am-proposal-card">
                                        <div className="am-proposal-main">
                                            <button
                                                type="button"
                                                className="am-expand-button"
                                                aria-label={`${expanded ? 'Collapse' : 'Expand'} ${proposal.title || 'proposal'}`}
                                                aria-expanded={expanded}
                                                onClick={() => setExpandedProposalIds(current => toggleSetItem(current, proposal.id))}
                                            >
                                                {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            </button>
                                            <div className="am-proposal-copy">
                                                <h3>{proposal.title || 'Untitled proposal'}</h3>
                                                <div className="am-truncate" title={getProposalTarget(proposal)}>
                                                    {getProposalTarget(proposal)}
                                                </div>
                                            </div>
                                            <div className="am-mission-statuses">
                                                <span className="am-pill" style={{ color: riskStyle.color, background: riskStyle.background }}>
                                                    {riskLevel}
                                                </span>
                                                <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                    {approvalStatus.replace(/_/g, ' ')}
                                                </span>
                                            </div>
                                            <div className="am-proposal-actions">
                                                {canDecideProposal && (
                                                    <>
                                                        <MissionActionButton
                                                            icon={<CheckCircle size={13} />}
                                                            label="Approve"
                                                            color="var(--success)"
                                                            loading={actionLoading === `${proposal.id}:approve`}
                                                            onClick={() => handleProposalAction(proposal, 'approve')}
                                                        />
                                                        <MissionActionButton
                                                            icon={<XCircle size={13} />}
                                                            label="Reject"
                                                            color="var(--danger)"
                                                            loading={actionLoading === `${proposal.id}:reject`}
                                                            onClick={() => handleProposalAction(proposal, 'reject')}
                                                        />
                                                    </>
                                                )}
                                                {canMaterializeProposal && (
                                                    <MissionActionButton
                                                        icon={<UploadCloud size={13} />}
                                                        label="Materialize"
                                                        color="var(--primary)"
                                                        loading={actionLoading === `${proposal.id}:materialize`}
                                                        onClick={() => openMaterializeDialog(proposal)}
                                                    />
                                                )}
                                            </div>
                                        </div>

                                        {expanded && (
                                            <div className="am-proposal-details">
                                                <div className="am-proposal-meta">
                                                    <div>
                                                        <span>Type: </span>
                                                        <strong>{proposal.test_type || '-'}</strong>
                                                    </div>
                                                    <div>
                                                        <span>File: </span>
                                                        <strong>{proposal.suggested_file_path || '-'}</strong>
                                                    </div>
                                                    {proposal.materialized_file_path && (
                                                        <div>
                                                            <span>Materialized: </span>
                                                            <strong>{proposal.materialized_file_path}</strong>
                                                        </div>
                                                    )}
                                                </div>
                                                {proposal.rationale && (
                                                    <p className="am-proposal-rationale">
                                                        {proposal.rationale}
                                                    </p>
                                                )}
                                                <pre className="am-spec-preview">
                                                    {compactSpecPreview(proposal.generated_spec_content)}
                                                </pre>
                                            </div>
                                        )}
                                    </article>
                                );
                            })}
                        </div>
                    )}
                </section>
            )}

            {showCreate && (
                <div
                    className="am-drawer-backdrop"
                    role="presentation"
                    onMouseDown={event => {
                        if (event.target === event.currentTarget) setShowCreate(false);
                    }}
                >
                    <aside
                        className="am-create-drawer"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="create-mission-title"
                    >
                        <form onSubmit={handleCreate} className="am-create-form">
                            <div className="am-drawer-header">
                                <div>
                                    <div className="am-kicker">Mission setup</div>
                                    <h2 id="create-mission-title">Create Mission</h2>
                                    <p>New missions are created with approval gates and can be started from Mission Control.</p>
                                </div>
                                <button
                                    type="button"
                                    className="am-icon-button"
                                    aria-label="Close create mission"
                                    onClick={() => setShowCreate(false)}
                                >
                                    <X size={18} />
                                </button>
                            </div>

                            <div className="am-stepper" aria-label="Create mission steps">
                                {['Template', 'Target', 'Schedule'].map((label, index) => (
                                    <button
                                        key={label}
                                        type="button"
                                        className={createStep === index + 1 ? 'am-step is-active' : 'am-step'}
                                        onClick={() => setCreateStep(index + 1)}
                                    >
                                        <span>{index + 1}</span>
                                        {label}
                                    </button>
                                ))}
                            </div>

                            {createStep === 1 && (
                                <div className="am-drawer-section">
                                    <div className="am-step-heading">
                                        <span>1</span>
                                        <div>
                                            <strong>Choose a quick start</strong>
                                            <small>Select the mission shape that best matches the work you want the agents to do.</small>
                                        </div>
                                    </div>
                                    <div className="am-template-picker" role="radiogroup" aria-label="Mission quick starts">
                                        {QUICK_START_TEMPLATES.map(template => {
                                            const isSelected = selectedTemplate?.label === template.label;
                                            return (
                                                <button
                                                    key={template.label}
                                                    type="button"
                                                    role="radio"
                                                    aria-checked={isSelected}
                                                    className={isSelected ? 'am-template-choice is-active' : 'am-template-choice'}
                                                    onClick={() => applyMissionTemplate(template)}
                                                >
                                                    <span className="am-template-icon">{template.icon}</span>
                                                    <span>
                                                        <strong>{template.label}</strong>
                                                        <small>{template.description}</small>
                                                    </span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {createStep === 2 && (
                                <div className="am-drawer-section">
                                    <div className="am-form-grid">
                                        <label className="am-field">
                                            <span>Name</span>
                                            <input
                                                name="mission-name"
                                                value={form.name}
                                                aria-invalid={Boolean(formErrors.name)}
                                                autoComplete="off"
                                                onChange={event => {
                                                    setForm(prev => ({ ...prev, name: event.target.value }));
                                                    setFormErrors(prev => ({ ...prev, name: undefined }));
                                                }}
                                                placeholder="Checkout coverage scout"
                                            />
                                            {formErrors.name && <small className="am-field-error">{formErrors.name}</small>}
                                        </label>
                                        <label className="am-field">
                                            <span>Type</span>
                                            <select
                                                name="mission-type"
                                                value={form.mission_type}
                                                onChange={event => {
                                                    const nextType = event.target.value;
                                                    setForm(prev => ({ ...prev, mission_type: nextType }));
                                                    const matchingTemplate = QUICK_START_TEMPLATES.find(template => template.mission_type === nextType);
                                                    if (matchingTemplate) setSelectedTemplateLabel(matchingTemplate.label);
                                                }}
                                            >
                                                <option value="exploration">Exploration</option>
                                                <option value="coverage">Coverage Gaps</option>
                                                <option value="regression">Regression Watch</option>
                                                <option value="flake_triage">Flake Triage</option>
                                                <option value="mixed">Mixed Mission</option>
                                            </select>
                                        </label>
                                    </div>

                                    <label className="am-field">
                                        <span>Description</span>
                                        <textarea
                                            name="mission-description"
                                            value={form.description}
                                            onChange={event => setForm(prev => ({ ...prev, description: event.target.value }))}
                                            placeholder="Focus on checkout, payment error states, and account recovery paths."
                                            rows={3}
                                        />
                                    </label>

                                    <label className="am-field">
                                        <span>Target URLs</span>
                                        <textarea
                                            name="mission-target-urls"
                                            value={form.target_urls}
                                            aria-invalid={Boolean(formErrors.target_urls)}
                                            inputMode="url"
                                            autoComplete="off"
                                            onChange={event => {
                                                setForm(prev => ({ ...prev, target_urls: event.target.value }));
                                                setFormErrors(prev => ({ ...prev, target_urls: undefined }));
                                            }}
                                            placeholder={'https://example.com\nhttps://example.com/checkout'}
                                            rows={5}
                                        />
                                        {formErrors.target_urls && <small className="am-field-error">{formErrors.target_urls}</small>}
                                    </label>
                                </div>
                            )}

                            {createStep === 3 && (
                                <div className="am-drawer-section">
                                    <div className="am-summary-card">
                                        <div className="am-summary-header">
                                            <span className="am-template-icon">{selectedTemplate?.icon}</span>
                                            <div>
                                                <div className="am-kicker">Selected quick start</div>
                                                <h3>{selectedTemplate?.label || 'Custom mission'}</h3>
                                            </div>
                                        </div>
                                        <p>{selectedTemplate?.capability || 'Runs with draft validation and approval gates.'}</p>
                                    </div>

                                    <div className="am-fieldset">
                                        <div className="am-fieldset-heading">
                                            <CalendarClock size={15} />
                                            <span>Schedule</span>
                                        </div>
                                        <div className="am-preset-row" aria-label="Schedule presets">
                                            {SCHEDULE_PRESETS.map(preset => (
                                                <button
                                                    key={preset.label}
                                                    type="button"
                                                    className={form.schedule_cron === preset.cron ? 'am-preset is-active' : 'am-preset'}
                                                    onClick={() => setForm(prev => ({ ...prev, schedule_cron: preset.cron }))}
                                                >
                                                    {preset.label}
                                                </button>
                                            ))}
                                        </div>
                                        <div className="am-form-grid am-form-grid-compact">
                                            <label className="am-field">
                                                <span>Cron</span>
                                                <input
                                                    name="mission-cron"
                                                    value={form.schedule_cron}
                                                    autoComplete="off"
                                                    onChange={event => setForm(prev => ({ ...prev, schedule_cron: event.target.value }))}
                                                    placeholder="0 9 * * 1-5"
                                                />
                                            </label>
                                            <label className="am-field">
                                                <span>Timezone</span>
                                                <input
                                                    name="mission-timezone"
                                                    value={form.timezone}
                                                    autoComplete="off"
                                                    onChange={event => setForm(prev => ({ ...prev, timezone: event.target.value || 'UTC' }))}
                                                />
                                            </label>
                                        </div>
                                    </div>

                                    <div className="am-fieldset">
                                        <div className="am-fieldset-heading">
                                            <Gauge size={15} />
                                            <span>Limits</span>
                                        </div>
                                        <div className="am-form-grid am-form-grid-compact">
                                            <label className="am-field">
                                                <span>Max Runtime <small>minutes</small></span>
                                                <input
                                                    name="mission-max-runtime"
                                                    type="number"
                                                    min={1}
                                                    value={form.max_runtime_minutes}
                                                    onChange={event => setForm(prev => ({ ...prev, max_runtime_minutes: Number(event.target.value) }))}
                                                />
                                            </label>
                                            <label className="am-field">
                                                <span>Max Iterations <small>0 = unlimited</small></span>
                                                <input
                                                    name="mission-max-iterations"
                                                    type="number"
                                                    min={0}
                                                    value={form.max_iterations}
                                                    onChange={event => setForm(prev => ({ ...prev, max_iterations: Number(event.target.value) }))}
                                                />
                                            </label>
                                            <label className="am-field">
                                                <span>LLM Budget <small>USD</small></span>
                                                <input
                                                    name="mission-budget"
                                                    type="number"
                                                    min={0}
                                                    step="0.5"
                                                    value={form.max_llm_budget_usd}
                                                    onChange={event => setForm(prev => ({ ...prev, max_llm_budget_usd: Number(event.target.value) }))}
                                                />
                                            </label>
                                        </div>
                                    </div>

                                    <div className="am-guardrail">
                                        <ShieldCheck size={16} />
                                        <span>Approval is required before proposals become repository files.</span>
                                    </div>
                                </div>
                            )}

                            <div className="am-drawer-footer">
                                <button
                                    type="button"
                                    className="am-button am-button-secondary"
                                    onClick={() => createStep === 1 ? setShowCreate(false) : setCreateStep(step => Math.max(1, step - 1))}
                                >
                                    {createStep === 1 ? 'Cancel' : 'Back'}
                                </button>
                                {createStep < 3 ? (
                                    <button
                                        type="button"
                                        className="am-button am-button-primary"
                                        onClick={() => setCreateStep(step => Math.min(3, step + 1))}
                                    >
                                        Next
                                    </button>
                                ) : (
                                    <button
                                        type="submit"
                                        disabled={creating}
                                        className="am-button am-button-primary"
                                    >
                                        {creating ? <Loader2 size={15} className="am-spin" /> : <Plus size={15} />}
                                        Create Mission
                                    </button>
                                )}
                            </div>
                        </form>
                    </aside>
                </div>
            )}

            {materializeProposal && (
                <div
                    className="am-modal-backdrop"
                    role="presentation"
                    onMouseDown={event => {
                        if (event.target === event.currentTarget) setMaterializeProposal(null);
                    }}
                >
                    <form
                        onSubmit={handleMaterializeConfirm}
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="materialize-title"
                        style={{
                            width: 'min(560px, 100%)',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            padding: '1rem',
                            boxShadow: '0 20px 60px rgba(0,0,0,0.35)',
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginBottom: '0.85rem' }}>
                            <div>
                                <h2 id="materialize-title" style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Materialize Test Proposal</h2>
                                <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                    This writes the generated spec into the repository.
                                </p>
                            </div>
                            <button
                                type="button"
                                aria-label="Close materialize dialog"
                                onClick={() => setMaterializeProposal(null)}
                                style={{
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                    height: '2rem',
                                }}
                            >
                                <X size={18} />
                            </button>
                        </div>

                        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            Target file path
                            <input
                                name="materialize-path"
                                value={materializePath}
                                onChange={event => setMaterializePath(event.target.value)}
                                style={{
                                    padding: '0.6rem 0.75rem',
                                    background: 'var(--background)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius-sm)',
                                    color: 'var(--text)',
                                    fontFamily: 'monospace',
                                    fontSize: '0.82rem',
                                }}
                            />
                        </label>

                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            marginTop: '0.85rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.82rem',
                        }}>
                            <input
                                name="materialize-overwrite"
                                type="checkbox"
                                checked={materializeOverwrite}
                                onChange={event => setMaterializeOverwrite(event.target.checked)}
                            />
                            Overwrite existing file
                        </label>

                        <pre style={{
                            margin: '0.85rem 0 0',
                            padding: '0.65rem',
                            background: 'var(--background)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--text-secondary)',
                            fontSize: '0.74rem',
                            whiteSpace: 'pre-wrap',
                            overflowWrap: 'anywhere',
                            maxHeight: '8rem',
                            overflow: 'auto',
                        }}>
                            {compactSpecPreview(materializeProposal.generated_spec_content)}
                        </pre>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
                            <button
                                type="button"
                                onClick={() => setMaterializeProposal(null)}
                                style={{
                                    padding: '0.5rem 0.75rem',
                                    background: 'transparent',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={actionLoading === `${materializeProposal.id}:materialize`}
                                style={{
                                    padding: '0.5rem 0.9rem',
                                    background: 'var(--primary)',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: 'var(--radius)',
                                    cursor: actionLoading === `${materializeProposal.id}:materialize` ? 'not-allowed' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.45rem',
                                    fontWeight: 700,
                                    opacity: actionLoading === `${materializeProposal.id}:materialize` ? 0.7 : 1,
                                }}
                            >
                                {actionLoading === `${materializeProposal.id}:materialize` ? <Loader2 size={14} className="am-spin" /> : <UploadCloud size={14} />}
                                Materialize
                            </button>
                        </div>
                    </form>
                </div>
            )}

            <style jsx>{`
                .am-alert {
                    margin-bottom: 1rem;
                    padding: 0.85rem 1rem;
                    border-radius: var(--radius);
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    font-size: 0.9rem;
                }

                .am-alert-danger {
                    background: var(--danger-muted);
                    border: 1px solid rgba(239, 68, 68, 0.25);
                    color: var(--danger);
                }

                .am-stat-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
                    gap: 0.75rem;
                    margin-bottom: 1.25rem;
                }

                .am-stat-card {
                    padding: 1rem;
                    background: var(--surface);
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-stat-card-primary {
                    border-color: rgba(59, 130, 246, 0.28);
                    background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), var(--surface));
                }

                .am-stat-icon,
                .am-template-icon {
                    width: 34px;
                    height: 34px;
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    color: var(--primary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                }

                .am-stat-value {
                    font-size: 1.1rem;
                    font-weight: 750;
                    color: var(--text);
                }

                .am-stat-label,
                .am-kicker {
                    font-size: 0.72rem;
                    color: var(--text-secondary);
                }

                .am-kicker {
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                    font-weight: 750;
                    margin-bottom: 0.35rem;
                }

                .am-panel {
                    padding: 1rem;
                    background: var(--surface);
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    margin-bottom: 1rem;
                }

                .am-create-panel {
                    background:
                        linear-gradient(135deg, rgba(59, 130, 246, 0.08), transparent 38%),
                        var(--surface);
                }

                .am-create-grid {
                    display: grid;
                    grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.75fr);
                    gap: 1.1rem;
                    align-items: start;
                }

                .am-create-main {
                    display: grid;
                    gap: 0.9rem;
                    min-width: 0;
                }

                .am-setup-flow,
                .am-setup-summary {
                    display: grid;
                    gap: 0.85rem;
                    min-width: 0;
                }

                .am-step-heading {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.6rem;
                    align-items: start;
                    color: var(--text);
                }

                .am-step-heading > span {
                    width: 1.55rem;
                    height: 1.55rem;
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    color: var(--primary);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 0.78rem;
                    font-weight: 800;
                }

                .am-step-heading strong,
                .am-step-heading small {
                    display: block;
                    min-width: 0;
                }

                .am-step-heading strong {
                    font-size: 0.9rem;
                    font-weight: 750;
                }

                .am-step-heading small {
                    margin-top: 0.18rem;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.35;
                }

                .am-section-heading,
                .am-section-title-row {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-section-heading {
                    align-items: center;
                    justify-content: flex-start;
                    margin-bottom: 0.85rem;
                }

                .am-section-title-row {
                    margin-bottom: 0.75rem;
                }

                .am-section-title-row h2,
                .am-section-heading h2 {
                    margin: 0;
                    font-size: 1rem;
                    font-weight: 750;
                    color: var(--text);
                }

                .am-section-title-row p,
                .am-section-heading p {
                    margin: 0.25rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.83rem;
                    line-height: 1.45;
                }

                .am-soft-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.35rem;
                    color: var(--primary);
                    background: var(--primary-glow);
                    border: 1px solid rgba(59, 130, 246, 0.2);
                    border-radius: var(--radius-sm);
                    padding: 0.35rem 0.55rem;
                    font-size: 0.76rem;
                    font-weight: 750;
                    white-space: nowrap;
                }

                .am-fieldset {
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    padding: 0.75rem;
                }

                .am-fieldset-heading {
                    display: flex;
                    align-items: center;
                    gap: 0.4rem;
                    color: var(--text);
                    font-size: 0.83rem;
                    font-weight: 750;
                    margin-bottom: 0.6rem;
                }

                .am-preset-row {
                    display: flex;
                    gap: 0.4rem;
                    flex-wrap: wrap;
                    margin-bottom: 0.65rem;
                }

                .am-preset {
                    padding: 0.28rem 0.55rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    font-weight: 700;
                    cursor: pointer;
                }

                .am-preset.is-active {
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-color: rgba(59, 130, 246, 0.28);
                }

                .am-form-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 0.75rem;
                }

                .am-form-grid-compact {
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                }

                .am-field {
                    display: flex;
                    flex-direction: column;
                    gap: 0.35rem;
                    font-size: 0.8rem;
                    color: var(--text-secondary);
                    min-width: 0;
                }

                .am-field > span {
                    display: inline-flex;
                    align-items: baseline;
                    gap: 0.35rem;
                    flex-wrap: wrap;
                }

                .am-field > span small {
                    color: var(--text-tertiary);
                    font-size: 0.72rem;
                    font-weight: 500;
                }

                .am-field input,
                .am-field select,
                .am-field textarea {
                    width: 100%;
                    padding: 0.55rem 0.7rem;
                    background: var(--background);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    color: var(--text);
                    font: inherit;
                    outline: none;
                    min-width: 0;
                }

                .am-field input[aria-invalid="true"],
                .am-field textarea[aria-invalid="true"] {
                    border-color: rgba(239, 68, 68, 0.55);
                    box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.12);
                }

                .am-field textarea {
                    resize: vertical;
                    line-height: 1.45;
                }

                .am-field-error {
                    color: var(--danger);
                    font-size: 0.74rem;
                    line-height: 1.35;
                }

                .am-field input:focus,
                .am-field select:focus,
                .am-field textarea:focus,
                .am-button:focus-visible,
                .am-filter:focus-visible,
                .am-preset:focus-visible,
                .am-template-button:focus-visible,
                .am-template-choice:focus-visible {
                    border-color: var(--primary);
                    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.22);
                    outline: none;
                }

                .am-template-picker {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 0.65rem;
                }

                .am-template-button,
                .am-template-choice {
                    width: 100%;
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    color: var(--text);
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.65rem;
                    text-align: left;
                    transition: border-color 0.2s, background 0.2s;
                    cursor: pointer;
                }

                .am-template-button:hover,
                .am-template-choice:hover {
                    background: rgba(255, 255, 255, 0.035);
                    border-color: var(--border-bright);
                }

                .am-template-choice.is-active {
                    background: rgba(59, 130, 246, 0.1);
                    border-color: rgba(59, 130, 246, 0.38);
                    box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.08);
                }

                .am-template-button strong,
                .am-template-button small,
                .am-template-choice strong,
                .am-template-choice small {
                    display: block;
                    min-width: 0;
                }

                .am-template-button strong,
                .am-template-choice strong {
                    font-size: 0.86rem;
                    font-weight: 750;
                }

                .am-template-button small,
                .am-template-choice small {
                    margin-top: 0.2rem;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.3;
                }

                .am-summary-card {
                    padding: 0.85rem;
                    border: 1px solid rgba(59, 130, 246, 0.24);
                    border-radius: var(--radius-sm);
                    background: rgba(59, 130, 246, 0.06);
                    min-width: 0;
                }

                .am-summary-header {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.65rem;
                    align-items: center;
                    min-width: 0;
                }

                .am-summary-header h3 {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.95rem;
                    font-weight: 750;
                }

                .am-summary-card p {
                    margin: 0.75rem 0;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    line-height: 1.45;
                }

                .am-summary-list {
                    display: grid;
                    gap: 0.5rem;
                }

                .am-summary-list div {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    padding: 0.5rem 0;
                    border-top: 1px solid rgba(255, 255, 255, 0.06);
                    min-width: 0;
                }

                .am-summary-list span {
                    color: var(--text-tertiary);
                    font-size: 0.74rem;
                }

                .am-summary-list strong {
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 700;
                    text-align: right;
                    overflow-wrap: anywhere;
                }

                .am-guardrail {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    padding: 0.65rem;
                    border-radius: var(--radius-sm);
                    background: var(--success-muted);
                    color: var(--success);
                    font-size: 0.78rem;
                    font-weight: 650;
                }

                .am-form-actions,
                .am-action-group,
                .am-card-actions,
                .am-filter-row {
                    display: flex;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                }

                .am-form-actions {
                    justify-content: space-between;
                    align-items: center;
                    margin-top: 1rem;
                    padding-top: 0.9rem;
                    border-top: 1px solid var(--border);
                }

                .am-action-group {
                    justify-content: flex-end;
                }

                .am-next-step {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.45rem;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    min-width: 0;
                }

                .am-button {
                    min-height: 2.35rem;
                    padding: 0.5rem 0.9rem;
                    border-radius: var(--radius);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.45rem;
                    border: 1px solid transparent;
                    font-weight: 700;
                    font-size: 0.85rem;
                }

                .am-button-primary {
                    background: var(--primary);
                    color: white;
                }

                .am-button-secondary {
                    background: transparent;
                    border-color: var(--border);
                    color: var(--text-secondary);
                }

                .am-button:disabled {
                    cursor: not-allowed;
                    opacity: 0.7;
                }

                .am-inline-item,
                .am-proposal-card {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.75rem;
                    align-items: center;
                    padding: 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-mission-error {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.45rem;
                    align-items: start;
                    padding: 0.6rem;
                    border: 1px solid rgba(239, 68, 68, 0.24);
                    border-radius: var(--radius-sm);
                    background: var(--danger-muted);
                    color: var(--danger);
                    font-size: 0.76rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-mission-note {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.45rem;
                    align-items: start;
                    padding: 0.6rem;
                    border: 1px solid rgba(59, 130, 246, 0.24);
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    color: var(--primary);
                    font-size: 0.76rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-work-item-list {
                    display: grid;
                    gap: 0.6rem;
                }

                .am-work-item {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-work-item-title {
                    color: var(--text);
                    font-size: 0.88rem;
                    font-weight: 750;
                    overflow-wrap: anywhere;
                }

                .am-work-item-meta {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    margin-top: 0.25rem;
                    color: var(--text-tertiary);
                    font-size: 0.74rem;
                }

                .am-work-item-blocker {
                    margin-top: 0.45rem;
                    color: var(--danger);
                    font-size: 0.76rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-mission-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
                    gap: 1rem;
                }

                .am-mission-card {
                    padding: 1.1rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    display: flex;
                    flex-direction: column;
                    gap: 0.9rem;
                    min-width: 0;
                }

                .am-card-header {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-mini-stat {
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-health-panel {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.5rem;
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-health-panel span,
                .am-health-panel strong {
                    display: block;
                    min-width: 0;
                }

                .am-health-panel span {
                    color: var(--text-tertiary);
                    font-size: 0.7rem;
                }

                .am-health-panel strong {
                    margin-top: 0.15rem;
                    color: var(--text-secondary);
                    font-size: 0.74rem;
                    font-weight: 650;
                    overflow-wrap: anywhere;
                    text-transform: capitalize;
                }

                .am-team-panel {
                    display: grid;
                    gap: 0.55rem;
                    padding: 0.7rem;
                    border: 1px solid rgba(59, 130, 246, 0.2);
                    border-radius: var(--radius-sm);
                    background: rgba(59, 130, 246, 0.055);
                }

                .am-team-summary {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.45rem;
                    align-items: start;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.4;
                    overflow-wrap: anywhere;
                }

                .am-work-lanes {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.5rem;
                }

                .am-work-lanes > div {
                    min-width: 0;
                    padding: 0.55rem;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: var(--radius-sm);
                    background: rgba(0, 0, 0, 0.08);
                }

                .am-work-lanes span,
                .am-work-lanes strong,
                .am-work-lanes small {
                    display: block;
                    min-width: 0;
                }

                .am-work-lanes span {
                    color: var(--text-tertiary);
                    font-size: 0.68rem;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.04em;
                }

                .am-work-lanes strong {
                    margin-top: 0.16rem;
                    color: var(--text);
                    font-size: 0.82rem;
                    font-weight: 750;
                    overflow-wrap: anywhere;
                }

                .am-work-lanes small {
                    margin-top: 0.16rem;
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                    line-height: 1.3;
                    overflow-wrap: anywhere;
                }

                .am-filter-row {
                    margin-bottom: 0.85rem;
                }

                .am-filter {
                    padding: 0.3rem 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    font-weight: 650;
                    text-transform: capitalize;
                }

                .am-filter.is-active {
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-color: rgba(59, 130, 246, 0.28);
                }

                .am-empty-inline {
                    padding: 0.9rem;
                    border: 1px dashed var(--border);
                    border-radius: var(--radius-sm);
                    color: var(--text-secondary);
                    font-size: 0.85rem;
                }

                .am-proposal-card {
                    align-items: start;
                    gap: 1rem;
                }

                .am-truncate {
                    margin-top: 0.25rem;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    min-width: 0;
                }

                .am-pill {
                    padding: 0.16rem 0.5rem;
                    border-radius: 999px;
                    font-size: 0.7rem;
                    font-weight: 750;
                    text-transform: capitalize;
                }

                .am-proposal-meta {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 0.55rem;
                    color: var(--text-tertiary);
                    font-size: 0.76rem;
                    margin-bottom: 0.65rem;
                }

                .am-proposal-meta strong {
                    color: var(--text-secondary);
                    font-weight: 500;
                    overflow-wrap: anywhere;
                    text-transform: capitalize;
                }

                .am-proposal-rationale {
                    margin: 0 0 0.65rem;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    line-height: 1.45;
                }

                .am-spec-preview {
                    margin: 0;
                    padding: 0.65rem;
                    background: var(--background);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    color: var(--text-secondary);
                    font-size: 0.74rem;
                    line-height: 1.45;
                    white-space: pre-wrap;
                    overflow-wrap: anywhere;
                    max-height: 5.5rem;
                    overflow: hidden;
                }

                .am-proposal-actions {
                    display: flex;
                    flex-direction: column;
                    gap: 0.4rem;
                    align-items: flex-end;
                }

                .am-attention-strip {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.75rem;
                    margin-bottom: 1rem;
                }

                .am-attention-card {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.85rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-attention-primary {
                    border-color: rgba(59, 130, 246, 0.28);
                    background: rgba(59, 130, 246, 0.08);
                }

                .am-attention-warning {
                    border-color: rgba(251, 191, 36, 0.28);
                    background: rgba(251, 191, 36, 0.08);
                }

                .am-attention-danger {
                    border-color: rgba(248, 113, 113, 0.28);
                    background: rgba(248, 113, 113, 0.08);
                }

                .am-attention-icon {
                    width: 2rem;
                    height: 2rem;
                    border-radius: var(--radius-sm);
                    color: var(--primary);
                    background: var(--primary-glow);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                .am-attention-copy {
                    min-width: 0;
                }

                .am-attention-copy strong,
                .am-attention-copy span,
                .am-attention-copy small {
                    display: block;
                    min-width: 0;
                }

                .am-attention-copy strong {
                    color: var(--text);
                    font-size: 1.05rem;
                    font-weight: 800;
                    font-variant-numeric: tabular-nums;
                }

                .am-attention-copy span {
                    margin-top: 0.1rem;
                    color: var(--text);
                    font-size: 0.8rem;
                    font-weight: 750;
                }

                .am-attention-copy small {
                    margin-top: 0.15rem;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-inline-list,
                .am-proposal-list,
                .am-mission-list {
                    display: grid;
                    gap: 0.7rem;
                }

                .am-inline-copy {
                    min-width: 0;
                }

                .am-inline-copy strong,
                .am-inline-copy span {
                    display: block;
                    min-width: 0;
                    overflow-wrap: anywhere;
                }

                .am-inline-copy strong {
                    color: var(--text);
                    font-size: 0.88rem;
                    font-weight: 750;
                    text-transform: capitalize;
                }

                .am-inline-copy span {
                    margin-top: 0.2rem;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.35;
                }

                .am-empty-state {
                    min-height: 320px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    gap: 0.75rem;
                }

                .am-empty-state h2 {
                    margin: 0;
                    color: var(--text);
                    font-size: 1.15rem;
                    font-weight: 800;
                }

                .am-empty-state p {
                    max-width: 540px;
                    margin: 0;
                    color: var(--text-secondary);
                    font-size: 0.9rem;
                    line-height: 1.55;
                }

                .am-empty-icon {
                    width: 3rem;
                    height: 3rem;
                    border-radius: var(--radius);
                    background: var(--primary-glow);
                    color: var(--primary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                .am-mission-panel {
                    padding: 0.95rem;
                }

                .am-mission-row {
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    overflow: hidden;
                }

                .am-mission-row-main {
                    display: grid;
                    grid-template-columns: minmax(220px, 1.15fr) minmax(160px, 0.8fr) minmax(130px, 0.55fr) minmax(250px, 1.05fr) minmax(82px, auto);
                    gap: 0.85rem;
                    align-items: center;
                    padding: 0.85rem;
                    min-width: 0;
                }

                .am-mission-identity,
                .am-proposal-main {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.65rem;
                    align-items: center;
                    min-width: 0;
                }

                .am-expand-button,
                .am-icon-button {
                    width: 2rem;
                    height: 2rem;
                    border-radius: var(--radius-sm);
                    border: 1px solid var(--border);
                    background: transparent;
                    color: var(--text-secondary);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                }

                .am-expand-button:hover,
                .am-icon-button:hover {
                    color: var(--text);
                    background: var(--surface-hover);
                }

                .am-action-button:hover,
                .am-button:hover,
                .am-filter:hover,
                .am-preset:hover {
                    border-color: var(--border-bright);
                    background: rgba(255, 255, 255, 0.035);
                }

                .am-button-primary:hover {
                    background: var(--primary-hover);
                }

                .am-action-button:focus-visible,
                .am-header-button:focus-visible,
                .am-button:focus-visible,
                .am-filter:focus-visible,
                .am-preset:focus-visible,
                .am-template-choice:focus-visible,
                .am-expand-button:focus-visible,
                .am-icon-button:focus-visible,
                .am-step:focus-visible {
                    outline: none;
                    border-color: var(--primary);
                    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.24);
                }

                .am-mission-title-block,
                .am-proposal-copy {
                    min-width: 0;
                }

                .am-mission-title-block h3,
                .am-proposal-copy h3 {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.92rem;
                    font-weight: 800;
                    overflow-wrap: anywhere;
                }

                .am-row-subtitle {
                    margin-top: 0.2rem;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    text-transform: capitalize;
                }

                .am-mission-target {
                    min-width: 0;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .am-mission-statuses {
                    display: flex;
                    gap: 0.4rem;
                    flex-wrap: wrap;
                    justify-content: flex-start;
                    min-width: 120px;
                }

                .am-row-metrics {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.55rem;
                    min-width: 0;
                }

                .am-row-metrics div {
                    min-width: 0;
                }

                .am-row-metrics span,
                .am-row-metrics strong {
                    display: block;
                    min-width: 0;
                }

                .am-row-metrics span {
                    color: var(--text-tertiary);
                    font-size: 0.68rem;
                    font-weight: 700;
                }

                .am-row-metrics strong {
                    margin-top: 0.12rem;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    font-weight: 700;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    text-transform: capitalize;
                }

                .am-mission-details,
                .am-proposal-details {
                    display: grid;
                    gap: 0.75rem;
                    padding: 0 0.85rem 0.85rem 3.5rem;
                    border-top: 1px solid var(--border);
                }

                .am-mission-details {
                    padding-top: 0.85rem;
                }

                .am-metadata-row {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    color: var(--text-tertiary);
                    font-size: 0.74rem;
                }

                .am-metadata-row span {
                    max-width: 220px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-proposal-card {
                    display: block;
                    padding: 0;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    overflow: hidden;
                }

                .am-proposal-main {
                    grid-template-columns: auto minmax(220px, 1fr) auto auto;
                    padding: 0.8rem;
                }

                .am-proposal-details {
                    padding-top: 0.85rem;
                }

                .am-drawer-backdrop,
                .am-modal-backdrop {
                    position: fixed;
                    inset: 0;
                    z-index: 50;
                    background: rgba(0, 0, 0, 0.58);
                    display: flex;
                    justify-content: flex-end;
                    padding: 0;
                }

                .am-modal-backdrop {
                    align-items: center;
                    justify-content: center;
                    padding: 1rem;
                }

                .am-create-drawer {
                    width: min(620px, 100%);
                    height: 100%;
                    background: var(--surface);
                    border-left: 1px solid var(--border);
                    box-shadow: -24px 0 70px rgba(0, 0, 0, 0.38);
                    overflow: hidden;
                }

                .am-create-form {
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    min-width: 0;
                }

                .am-drawer-header {
                    display: flex;
                    justify-content: space-between;
                    gap: 1rem;
                    padding: 1rem;
                    border-bottom: 1px solid var(--border);
                }

                .am-drawer-header h2 {
                    margin: 0;
                    color: var(--text);
                    font-size: 1.05rem;
                    font-weight: 800;
                }

                .am-drawer-header p {
                    margin: 0.25rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    line-height: 1.45;
                }

                .am-stepper {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.5rem;
                    padding: 0.8rem 1rem;
                    border-bottom: 1px solid var(--border);
                }

                .am-step {
                    min-width: 0;
                    padding: 0.5rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.4rem;
                    font-size: 0.78rem;
                    font-weight: 750;
                }

                .am-step span {
                    width: 1.25rem;
                    height: 1.25rem;
                    border-radius: 999px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    background: var(--surface-hover);
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                }

                .am-step.is-active {
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-color: rgba(59, 130, 246, 0.32);
                }

                .am-step.is-active span {
                    background: var(--primary);
                    color: white;
                }

                .am-drawer-section {
                    display: grid;
                    gap: 0.9rem;
                    padding: 1rem;
                    overflow: auto;
                    min-height: 0;
                }

                .am-drawer-footer {
                    margin-top: auto;
                    padding: 1rem;
                    border-top: 1px solid var(--border);
                    display: flex;
                    justify-content: space-between;
                    gap: 0.75rem;
                    background: var(--surface);
                }

                .am-live-panel {
                    gap: 0.85rem;
                }

                .am-live-tabs {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.4rem;
                    border-bottom: 1px solid var(--border);
                    padding-bottom: 0.7rem;
                }

                .am-live-tab {
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    cursor: pointer;
                    font-size: 0.78rem;
                    font-weight: 750;
                    padding: 0.4rem 0.7rem;
                    text-transform: capitalize;
                }

                .am-live-tab.is-active {
                    border-color: rgba(59, 130, 246, 0.34);
                    background: var(--primary-glow);
                    color: var(--primary);
                }

                .am-live-grid {
                    display: grid;
                    grid-template-columns: minmax(240px, 0.42fr) minmax(0, 1fr);
                    gap: 0.85rem;
                    min-width: 0;
                }

                .am-live-summary {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.65rem;
                }

                .am-live-summary > div {
                    min-width: 0;
                    padding: 0.7rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-live-summary span {
                    display: block;
                    color: var(--text-tertiary);
                    font-size: 0.68rem;
                    font-weight: 750;
                    text-transform: uppercase;
                }

                .am-live-summary strong {
                    display: block;
                    margin-top: 0.2rem;
                    color: var(--text);
                    font-size: 0.82rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-live-output {
                    min-height: 260px;
                    max-height: 520px;
                    overflow: auto;
                    margin: 0;
                    padding: 0.8rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: #070b13;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.55;
                    white-space: pre-wrap;
                    word-break: break-word;
                }

                .am-browser-panel {
                    overflow: hidden;
                    border-radius: var(--radius);
                }

                .am-event-list,
                .am-output-list {
                    display: grid;
                    gap: 0.55rem;
                    min-width: 0;
                }

                .am-event-row {
                    display: grid;
                    grid-template-columns: auto auto minmax(0, 1fr);
                    align-items: center;
                    gap: 0.6rem;
                    padding: 0.65rem 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-event-sequence {
                    color: var(--text-tertiary);
                    font-size: 0.72rem;
                    font-weight: 750;
                }

                .am-event-copy {
                    min-width: 0;
                    display: grid;
                    gap: 0.15rem;
                }

                .am-event-copy strong,
                .am-event-copy span {
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-event-copy strong {
                    color: var(--text);
                    font-size: 0.82rem;
                }

                .am-event-copy span,
                .am-empty-inline {
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                }

                .am-output-card {
                    display: grid;
                    gap: 0.5rem;
                }

                .am-output-title {
                    color: var(--text);
                    font-size: 0.84rem;
                    font-weight: 800;
                }

                .am-spin {
                    animation: spin 1s linear infinite;
                }

                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }

                @media (prefers-reduced-motion: reduce) {
                    .am-spin,
                    [style*="spin"] {
                        animation: none !important;
                    }
                }

                @media (max-width: 900px) {
                    .am-create-grid,
                    .am-work-item,
                    .am-proposal-card,
                    .am-inline-item,
                    .am-live-grid {
                        grid-template-columns: 1fr;
                    }

                    .am-attention-strip {
                        grid-template-columns: repeat(2, minmax(0, 1fr));
                    }

                    .am-mission-row-main,
                    .am-proposal-main {
                        grid-template-columns: 1fr;
                        align-items: stretch;
                    }

                    .am-mission-identity {
                        grid-template-columns: auto minmax(0, 1fr);
                    }

                    .am-proposal-main {
                        grid-template-columns: auto minmax(0, 1fr);
                    }

                    .am-proposal-main .am-mission-statuses,
                    .am-proposal-main .am-proposal-actions {
                        grid-column: 1 / -1;
                    }

                    .am-mission-statuses,
                    .am-card-actions,
                    .am-proposal-actions {
                        justify-content: flex-start;
                    }

                    .am-mission-details,
                    .am-proposal-details {
                        padding-left: 0.85rem;
                    }

                    .am-proposal-actions {
                        align-items: flex-start;
                        flex-direction: row;
                        flex-wrap: wrap;
                    }
                }

                @media (max-width: 640px) {
                    .am-stat-grid,
                    .am-mission-grid,
                    .am-attention-strip,
                    .am-health-panel,
                    .am-work-lanes,
                    .am-row-metrics,
                    .am-live-summary,
                    .am-template-picker {
                        grid-template-columns: 1fr;
                    }

                    .am-event-row {
                        grid-template-columns: 1fr;
                        align-items: start;
                    }

                    .am-section-title-row,
                    .am-card-header {
                        flex-direction: column;
                    }

                    .am-form-actions {
                        align-items: stretch;
                        flex-direction: column;
                    }

                    .am-action-group {
                        flex-direction: column;
                    }

                    .am-button {
                        width: 100%;
                    }

                    .am-header-actions {
                        width: 100%;
                    }

                    .am-header-actions > button {
                        flex: 1 1 150px;
                        justify-content: center;
                    }

                    .am-create-drawer {
                        width: 100%;
                    }

                    .am-stepper {
                        grid-template-columns: 1fr;
                    }

                    .am-drawer-footer {
                        flex-direction: column;
                    }
                }
            `}</style>
        </PageLayout>
    );
}

function MissionActionButton({
    icon,
    label,
    color,
    loading,
    onClick,
}: {
    icon: ReactNode;
    label: string;
    color: string;
    loading: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            className="am-action-button"
            onClick={onClick}
            disabled={loading}
            aria-busy={loading}
            style={{
                padding: '0.35rem 0.6rem',
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                cursor: loading ? 'not-allowed' : 'pointer',
                color,
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                opacity: loading ? 0.7 : 1,
            }}
        >
            {loading ? <Loader2 size={13} className="am-spin" /> : icon}
            {label}
        </button>
    );
}
