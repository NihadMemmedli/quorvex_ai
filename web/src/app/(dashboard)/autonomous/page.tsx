'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
    AlertCircle,
    Bot,
    CalendarClock,
    CheckCircle,
    ClipboardCheck,
    Compass,
    DollarSign,
    FileText,
    Gauge,
    Globe2,
    Loader2,
    Pause,
    Play,
    Plus,
    RefreshCw,
    RotateCcw,
    ShieldCheck,
    Sparkles,
    Square,
    Target,
    UploadCloud,
    Workflow,
    XCircle,
} from 'lucide-react';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface Mission {
    id: string;
    name: string;
    mission_type: string;
    status: string;
    schedule_cron?: string | null;
    target_urls?: string[];
    autonomy_level: string;
    approval_policy: string;
    latest_run_id?: string | null;
    last_run_at?: string | null;
    next_run_at?: string | null;
    last_error?: string | null;
    total_runs: number;
    total_findings: number;
    budget_used_usd: number;
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

const DEFAULT_FORM: MissionForm = {
    name: '',
    description: '',
    mission_type: 'exploration',
    target_urls: '',
    schedule_cron: '',
    timezone: 'UTC',
    max_runtime_minutes: 30,
    max_iterations: 10,
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
        label: 'Exploration',
        mission_type: 'exploration',
        description: 'Map key pages, flows, and interaction paths.',
        schedule_cron: '0 9 * * 1-5',
        max_runtime_minutes: 30,
        max_iterations: 10,
        max_llm_budget_usd: 5,
        capability: 'Maps known coverage gaps into reviewable exploration proposals.',
        icon: <Compass size={16} />,
    },
    {
        label: 'Coverage Gaps',
        mission_type: 'coverage',
        description: 'Look for untested routes and missing assertions.',
        schedule_cron: '0 10 * * 1-5',
        max_runtime_minutes: 25,
        max_iterations: 8,
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
        max_iterations: 6,
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
        max_iterations: 6,
        max_llm_budget_usd: 3,
        capability: 'Records flake triage intent and keeps the approval flow ready for proposals.',
        icon: <Gauge size={16} />,
    },
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

function formatMissionType(value: string) {
    return value.replace(/_/g, ' ');
}

function getStatusStyle(status: string) {
    const normalized = status.toLowerCase();
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

function canStart(status: string) {
    return ['draft', 'created', 'idle', 'scheduled', 'completed', 'failed', 'error', 'cancelled'].includes(status.toLowerCase());
}

function canPause(status: string) {
    return ['running', 'active'].includes(status.toLowerCase());
}

function canResume(status: string) {
    return status.toLowerCase() === 'paused';
}

function canCancel(status: string) {
    return !['cancelled', 'completed'].includes(status.toLowerCase());
}

function getProposalTarget(proposal: TestProposal) {
    return proposal.target_url || proposal.target_route || proposal.route || '-';
}

function compactSpecPreview(content?: string | null) {
    if (!content) return 'No generated spec preview available.';
    const compact = content.replace(/\s+/g, ' ').trim();
    return compact.length > 260 ? `${compact.slice(0, 260)}...` : compact;
}

export default function AutonomousMissionsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const projectId = currentProject?.id || getStoredProjectId() || 'default';
    const encodedProjectId = encodeURIComponent(projectId);
    const missionsUrl = `${API_BASE}/autonomous/${encodedProjectId}/missions`;
    const proposalsUrl = `${API_BASE}/autonomous/${encodedProjectId}/proposals`;

    const [missions, setMissions] = useState<Mission[]>([]);
    const [approvals, setApprovals] = useState<Approval[]>([]);
    const [proposals, setProposals] = useState<TestProposal[]>([]);
    const [proposalFilter, setProposalFilter] = useState<ProposalFilter>(getInitialProposalFilter);
    const [proposalLoadError, setProposalLoadError] = useState<string | null>(null);
    const [approvalsLoadError, setApprovalsLoadError] = useState<string | null>(null);
    const [materializeProposal, setMaterializeProposal] = useState<TestProposal | null>(null);
    const [materializePath, setMaterializePath] = useState('');
    const [materializeOverwrite, setMaterializeOverwrite] = useState(false);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [form, setForm] = useState<MissionForm>(DEFAULT_FORM);
    const [formErrors, setFormErrors] = useState<FormErrors>({});
    const [selectedTemplateLabel, setSelectedTemplateLabel] = useState(QUICK_START_TEMPLATES[0]?.label || '');
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

    const refreshAll = useCallback(async () => {
        await Promise.all([fetchMissions(), fetchApprovals(), fetchProposals()]);
    }, [fetchApprovals, fetchMissions, fetchProposals]);

    useEffect(() => {
        setLoading(true);
        refreshAll().finally(() => setLoading(false));
    }, [refreshAll]);

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
        setShowCreate(true);
    };

    const totals = useMemo(() => {
        return missions.reduce(
            (acc, mission) => {
                acc.runs += mission.total_runs || 0;
                acc.findings += mission.total_findings || 0;
                acc.budget += mission.budget_used_usd || 0;
                if (canPause(mission.status)) acc.running += 1;
                return acc;
            },
            { runs: 0, findings: 0, budget: 0, running: 0 }
        );
    }, [missions]);

    const hasMissions = missions.length > 0;
    const showCreatePanel = !hasMissions || showCreate;
    const selectedTemplate = QUICK_START_TEMPLATES.find(template => template.label === selectedTemplateLabel)
        || QUICK_START_TEMPLATES.find(template => template.mission_type === form.mission_type)
        || QUICK_START_TEMPLATES[0];
    const dashboardStats = [
        { label: 'Running', value: totals.running, icon: <Play size={16} /> },
        { label: 'Runs', value: totals.runs, icon: <RotateCcw size={16} /> },
        { label: 'Findings', value: totals.findings, icon: <AlertCircle size={16} /> },
        { label: 'Approvals', value: approvals.length, icon: <CheckCircle size={16} /> },
        { label: 'Proposals', value: proposals.length, icon: <FileText size={16} /> },
        { label: 'Budget', value: formatCurrency(totals.budget), icon: <DollarSign size={16} /> },
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
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                            type="button"
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
                            <RefreshCw size={14} style={refreshing ? { animation: 'spin 1s linear infinite' } : undefined} />
                            Refresh
                        </button>
                        <button
                            type="button"
                            onClick={() => setShowCreate(value => !value)}
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

            {approvals.length > 0 && (
                <section className="am-panel">
                    <div className="am-section-heading">
                        <CheckCircle size={17} style={{ color: 'var(--warning)' }} />
                        <h2>Pending Approvals</h2>
                    </div>
                    <div style={{ display: 'grid', gap: '0.65rem' }}>
                        {approvals.slice(0, 5).map(approval => (
                            <div key={approval.id} className="am-inline-item">
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontWeight: 700, fontSize: '0.88rem', textTransform: 'capitalize' }}>
                                        {approval.action_type.replace(/_/g, ' ')}
                                    </div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.2rem', overflowWrap: 'anywhere' }}>
                                        {String(approval.requested_payload?.action || approval.requested_payload?.suggested_test || approval.finding_id || approval.id)}
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: '0.4rem' }}>
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

            {approvalsLoadError && (
                <div className="am-alert am-alert-danger">
                    {approvalsLoadError}
                </div>
            )}

            {showCreatePanel && (
                <form
                    onSubmit={handleCreate}
                    className="am-panel am-create-panel"
                >
                    <div className="am-create-grid">
                        <div className="am-create-main">
                            <div className="am-section-title-row">
                                <div>
                                    <div className="am-kicker">Mission setup</div>
                                    <h2>Create Mission</h2>
                                    <p>Define the objective and target surface first. New missions are created paused, then started when you are ready.</p>
                                </div>
                                {!hasMissions && (
                                    <div className="am-soft-badge">
                                        <Sparkles size={14} /> First mission
                                    </div>
                                )}
                            </div>

                            <div className="am-setup-flow">
                                <div className="am-step-heading">
                                    <span>1</span>
                                    <div>
                                        <strong>Objective</strong>
                                        <small>Pick the mission shape and name it for the flow or risk area it owns.</small>
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
                                        rows={2}
                                    />
                                </label>

                                <div className="am-step-heading">
                                    <span>2</span>
                                    <div>
                                        <strong>Targets</strong>
                                        <small>Use app URLs reachable by the Quorvex backend or worker environment.</small>
                                    </div>
                                </div>
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
                                        rows={4}
                                    />
                                    {formErrors.target_urls && <small className="am-field-error">{formErrors.target_urls}</small>}
                                </label>
                            </div>
                        </div>

                        <aside className="am-setup-summary">
                            <div className="am-summary-card">
                                <div className="am-summary-header">
                                    <span className="am-template-icon">{selectedTemplate?.icon}</span>
                                    <div>
                                        <div className="am-kicker">Selected quick start</div>
                                        <h3>{selectedTemplate?.label || 'Custom mission'}</h3>
                                    </div>
                                </div>
                                <p>{selectedTemplate?.capability || 'Runs with draft validation and approval gates.'}</p>
                                <div className="am-summary-list">
                                    <div>
                                        <span>Lifecycle</span>
                                        <strong>Created paused</strong>
                                    </div>
                                    <div>
                                        <span>Autonomy</span>
                                        <strong>Draft validate</strong>
                                    </div>
                                    <div>
                                        <span>Approval</span>
                                        <strong>Required</strong>
                                    </div>
                                </div>
                            </div>

                            <div className="am-fieldset">
                                <div className="am-fieldset-heading">
                                    <CalendarClock size={15} />
                                    <span>Schedule</span>
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
                                        <span>Max Iterations <small>runs</small></span>
                                        <input
                                            name="mission-max-iterations"
                                            type="number"
                                            min={1}
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
                        </aside>
                    </div>

                    <div className="am-form-actions">
                        <div className="am-next-step">
                            <Play size={14} />
                            <span>After creation, start the paused mission from Mission Control.</span>
                        </div>
                        <div className="am-action-group">
                            {hasMissions && (
                                <button
                                    type="button"
                                    className="am-button am-button-secondary"
                                    onClick={() => setShowCreate(false)}
                                >
                                    Cancel
                                </button>
                            )}
                            <button
                                type="submit"
                                disabled={creating}
                                className="am-button am-button-primary"
                            >
                                {creating ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> : <Plus size={15} />}
                                Create Mission
                            </button>
                        </div>
                    </div>
                </form>
            )}

            {hasMissions && (
                <section className="am-panel">
                    <div className="am-section-title-row">
                        <div>
                            <div className="am-kicker">Mission control</div>
                            <h2>Active Missions</h2>
                            <p>Track schedules, latest activity, and pending actions for this project.</p>
                        </div>
                    </div>
                    <div className="am-mission-grid">
                    {missions.map(mission => {
                        const statusStyle = getStatusStyle(mission.status);
                        return (
                            <div key={mission.id} className="am-mission-card">
                                <div className="am-card-header">
                                    <div style={{ minWidth: 0 }}>
                                        <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, overflowWrap: 'anywhere' }}>
                                            {mission.name}
                                        </h3>
                                        <div style={{ marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'capitalize' }}>
                                            {formatMissionType(mission.mission_type)}
                                        </div>
                                    </div>
                                    <span style={{
                                        padding: '0.18rem 0.55rem',
                                        borderRadius: '999px',
                                        color: statusStyle.color,
                                        background: statusStyle.background,
                                        fontSize: '0.72rem',
                                        fontWeight: 700,
                                        textTransform: 'capitalize',
                                        flexShrink: 0,
                                    }}>
                                        {mission.status.replace(/_/g, ' ')}
                                    </span>
                                </div>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                                    {(mission.target_urls || []).slice(0, 3).map(url => (
                                        <div key={url} style={{
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.8rem',
                                            whiteSpace: 'nowrap',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                        }}>
                                            {url}
                                        </div>
                                    ))}
                                    {(mission.target_urls?.length || 0) > 3 && (
                                        <div style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>
                                            +{(mission.target_urls?.length || 0) - 3} more targets
                                        </div>
                                    )}
                                </div>

                                <div style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'repeat(3, 1fr)',
                                    gap: '0.6rem',
                                }}>
                                    {[
                                        { label: 'Runs', value: mission.total_runs || 0 },
                                        { label: 'Findings', value: mission.total_findings || 0 },
                                        { label: 'Budget', value: formatCurrency(mission.budget_used_usd || 0) },
                                    ].map(item => (
                                        <div key={item.label} className="am-mini-stat">
                                            <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{item.value}</div>
                                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{item.label}</div>
                                        </div>
                                    ))}
                                </div>

                                <div style={{
                                    display: 'grid',
                                    gridTemplateColumns: '1fr 1fr',
                                    gap: '0.75rem',
                                    color: 'var(--text-secondary)',
                                    fontSize: '0.78rem',
                                }}>
                                    <div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', marginBottom: '0.15rem', color: 'var(--text-tertiary)' }}>
                                            <CalendarClock size={13} /> Last Run
                                        </div>
                                        <div>{formatDate(mission.last_run_at)}</div>
                                    </div>
                                    <div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', marginBottom: '0.15rem', color: 'var(--text-tertiary)' }}>
                                            <CalendarClock size={13} /> Next Run
                                        </div>
                                        <div>{formatDate(mission.next_run_at)}</div>
                                    </div>
                                </div>

                                <div style={{
                                    color: 'var(--text-tertiary)',
                                    fontSize: '0.75rem',
                                    display: 'flex',
                                    flexWrap: 'wrap',
                                    gap: '0.5rem',
                                }}>
                                    <span>{mission.autonomy_level}</span>
                                    <span>{mission.approval_policy}</span>
                                    {mission.schedule_cron && <span>{mission.schedule_cron}</span>}
                                    {mission.latest_run_id && <span>Run {mission.latest_run_id}</span>}
                                </div>

                                {mission.last_error && (
                                    <div className="am-mission-error">
                                        <AlertCircle size={14} />
                                        <span>{mission.last_error}</span>
                                    </div>
                                )}

                                <div className="am-card-actions">
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
                    <div className="am-filter-row" role="tablist" aria-label="Proposal status">
                        {PROPOSAL_FILTERS.map(filter => (
                            <button
                                key={filter}
                                type="button"
                                role="tab"
                                aria-selected={proposalFilter === filter}
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
                        <div style={{ display: 'grid', gap: '0.75rem' }}>
                            {proposals.map(proposal => {
                                const approvalStatus = proposal.approval_status || 'unknown';
                                const riskLevel = proposal.risk_level || 'unknown';
                                const statusStyle = getStatusStyle(approvalStatus);
                                const riskStyle = getRiskStyle(riskLevel);
                                const status = approvalStatus.toLowerCase();
                                const canDecideProposal = status === 'pending';
                                const canMaterializeProposal = status === 'approved';

                                return (
                                    <div key={proposal.id} className="am-proposal-card">
                                        <div style={{ minWidth: 0 }}>
                                            <div className="am-card-header" style={{ marginBottom: '0.55rem' }}>
                                                <div style={{ minWidth: 0 }}>
                                                    <h3 style={{ margin: 0, fontSize: '0.92rem', fontWeight: 700, overflowWrap: 'anywhere' }}>
                                                        {proposal.title || 'Untitled proposal'}
                                                    </h3>
                                                    <div className="am-truncate">
                                                        {getProposalTarget(proposal)}
                                                    </div>
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', justifyContent: 'flex-end', flexShrink: 0 }}>
                                                    <span className="am-pill" style={{ color: riskStyle.color, background: riskStyle.background }}>
                                                        {riskLevel}
                                                    </span>
                                                    <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                        {approvalStatus.replace(/_/g, ' ')}
                                                    </span>
                                                </div>
                                            </div>

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
                                );
                            })}
                        </div>
                    )}
                </section>
            )}

            {materializeProposal && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0,0,0,0.55)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '1rem',
                    zIndex: 50,
                }}>
                    <form
                        onSubmit={handleMaterializeConfirm}
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
                                <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Materialize Test Proposal</h2>
                                <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                    This writes the generated spec into the repository.
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => setMaterializeProposal(null)}
                                style={{
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                    height: '2rem',
                                }}
                            >
                                <XCircle size={18} />
                            </button>
                        </div>

                        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            Target file path
                            <input
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
                                {actionLoading === `${materializeProposal.id}:materialize` ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <UploadCloud size={14} />}
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

                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }

                @media (max-width: 900px) {
                    .am-create-grid,
                    .am-proposal-card,
                    .am-inline-item {
                        grid-template-columns: 1fr;
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
                    .am-template-picker {
                        grid-template-columns: 1fr;
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
            onClick={onClick}
            disabled={loading}
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
            {loading ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : icon}
            {label}
        </button>
    );
}
