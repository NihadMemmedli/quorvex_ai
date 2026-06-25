'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Activity, ChevronDown, ChevronUp, CircleAlert, Code2, GitBranch, GitPullRequest, Loader2, Play, RefreshCw, Search, Settings, ShieldCheck } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { useProjectRole } from '@/hooks/useProjectRole';
import { API_BASE } from '@/lib/api';
import { PipelineStatusCard } from '@/components/PipelineStatusCard';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { QualityGateCard } from './components/QualityGateCard';
import { QualityGateDetailDrawer } from './components/QualityGateDetailDrawer';
import { RunDetailDrawer, type CiArtifact, type CiJob, type CiRun } from './components/RunDetailDrawer';
import { WorkflowGeneratorPanel } from './components/WorkflowGeneratorPanel';
import type { GateState, QualityGate, QualityGateDefaults } from './components/types';
import { FALLBACK_QUALITY_GATE_DEFAULTS, resolveQualityGateDefaults } from './components/types';

type ProviderFilter = 'all' | 'gitlab' | 'github';

interface ProviderInfo {
    provider: 'github' | 'gitlab';
    configured: boolean;
    repository?: string;
    default_ref?: string;
    base_url?: string;
    setup_status?: string;
    missing_requirements?: string[];
    recommended_next_action?: {
        label: string;
        action: 'open_settings' | 'generate_workflow' | 'open_trigger';
        href?: string;
    } | null;
    last_sync_at?: string | null;
    capabilities?: string[];
}

interface Workflow {
    id: string;
    name: string;
    path: string;
    state: string;
    provider: 'github' | 'gitlab';
}

const activeStatuses = ['pending', 'running', 'queued', 'waiting', 'in_progress'];

export default function CiCdPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || (typeof window !== 'undefined' ? localStorage.getItem('selectedProjectId') : null) || 'default';
    const { canEdit } = useProjectRole(projectId);
    const pid = encodeURIComponent(projectId);

    const [providers, setProviders] = useState<ProviderInfo[]>([]);
    const [pipelines, setPipelines] = useState<CiRun[]>([]);
    const [workflows, setWorkflows] = useState<Workflow[]>([]);
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [filter, setFilter] = useState<ProviderFilter>('all');
    const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);
    const triggerPanelRef = useRef<HTMLElement | null>(null);
    const qualityGateRef = useRef<HTMLElement | null>(null);
    const workflowPanelRef = useRef<HTMLDivElement | null>(null);
    const runsRef = useRef<HTMLDivElement | null>(null);

    const [showTrigger, setShowTrigger] = useState(false);
    const [showWorkflowGenerator, setShowWorkflowGenerator] = useState(false);
    const [triggerProvider, setTriggerProvider] = useState<'github' | 'gitlab'>('github');
    const [triggerWorkflow, setTriggerWorkflow] = useState('');
    const [triggerRef, setTriggerRef] = useState('');
    const [triggerInputs, setTriggerInputs] = useState('');
    const [triggering, setTriggering] = useState(false);
    const [triggerError, setTriggerError] = useState('');

    const [selectedRun, setSelectedRun] = useState<CiRun | null>(null);
    const [runJobs, setRunJobs] = useState<CiJob[]>([]);
    const [runArtifacts, setRunArtifacts] = useState<CiArtifact[]>([]);
    const [runLoading, setRunLoading] = useState(false);
    const [runActionLoading, setRunActionLoading] = useState('');
    const [runError, setRunError] = useState('');
    const [runLogs, setRunLogs] = useState<{ type: string; url?: string; content?: string } | null>(null);

    const [qualityGates, setQualityGates] = useState<QualityGate[]>([]);
    const [selectedGate, setSelectedGate] = useState<QualityGate | null>(null);
    const [gateFilter, setGateFilter] = useState<GateState>('all');
    const [gateDetailLoading, setGateDetailLoading] = useState(false);
    const [gateActionLoading, setGateActionLoading] = useState('');
    const [gateDetailError, setGateDetailError] = useState('');
    const [gatePrNumber, setGatePrNumber] = useState('');
    const [startingGate, setStartingGate] = useState(false);
    const [gateError, setGateError] = useState('');
    const [qualityGateDefaults, setQualityGateDefaults] = useState<QualityGateDefaults>(FALLBACK_QUALITY_GATE_DEFAULTS);

    const githubProvider = providers.find(p => p.provider === 'github');
    const ghConfigured = providers.some(p => p.provider === 'github' && p.configured);
    const glConfigured = providers.some(p => p.provider === 'gitlab' && p.configured);
    const anyProviderConfigured = ghConfigured || glConfigured;
    const defaultRef = providers.find(p => p.provider === triggerProvider)?.default_ref || 'main';

    const fetchProviders = useCallback(async () => {
        const res = await fetch(`${API_BASE}/projects/${pid}/ci/providers`).catch(() => null);
        if (res?.ok) {
            const data = await res.json();
            setProviders(data || []);
            if (!data?.some((p: ProviderInfo) => p.provider === triggerProvider && p.configured)) {
                const first = data?.find((p: ProviderInfo) => p.configured);
                if (first) setTriggerProvider(first.provider);
            }
        }
    }, [pid, triggerProvider]);

    const fetchWorkflows = useCallback(async () => {
        if (!ghConfigured) {
            setWorkflows([]);
            return;
        }
        const res = await fetch(`${API_BASE}/projects/${pid}/ci/workflows?provider=github`).catch(() => null);
        if (res?.ok) setWorkflows(await res.json());
    }, [ghConfigured, pid]);

    const syncGithubRuns = useCallback(async () => {
        if (!canEdit || !anyProviderConfigured) return;
        await fetch(`${API_BASE}/projects/${pid}/ci/runs/sync`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: 'all', per_page: 20 }),
        }).catch(() => null);
    }, [anyProviderConfigured, canEdit, pid]);

    const fetchQualityGates = useCallback(async () => {
        if (!ghConfigured) {
            setQualityGates([]);
            return;
        }
        try {
            const configRes = await fetch(`${API_BASE}/github/${pid}/config`);
            if (configRes.ok) setQualityGateDefaults(resolveQualityGateDefaults(await configRes.json()));
            const res = await fetch(`${API_BASE}/github/${pid}/quality-gates/pr?limit=20`);
            if (res.ok) {
                const gates = await res.json();
                setQualityGates(gates);
                setSelectedGate(prev => prev ? (gates.find((gate: QualityGate) => gate.id === prev.id) || prev) : prev);
            }
        } catch { /* ignore */ }
    }, [ghConfigured, pid]);

    const fetchPipelines = useCallback(async (doSync = false) => {
        if (doSync) {
            setSyncing(true);
            await syncGithubRuns();
            setSyncing(false);
        }
        const res = await fetch(`${API_BASE}/projects/${pid}/ci/runs?provider=all`).catch(() => null);
        if (res?.ok) setPipelines(await res.json());
        await fetchQualityGates();
        setLoading(false);
    }, [fetchQualityGates, pid, syncGithubRuns]);

    useEffect(() => {
        setLoading(true);
        fetchProviders().finally(() => fetchPipelines(canEdit));
    }, [canEdit, fetchProviders, fetchPipelines]);

    useEffect(() => {
        fetchWorkflows();
    }, [fetchWorkflows]);

    useEffect(() => {
        if (githubProvider?.setup_status === 'needs_workflow') {
            setShowWorkflowGenerator(true);
        }
    }, [githubProvider?.setup_status]);

    useEffect(() => {
        const hasActive = pipelines.some(p => activeStatuses.includes(p.status));
        const hasActiveGate = qualityGates.some(g => ['running', 'analyzed'].includes(g.quality_gate?.state));
        if (hasActive || hasActiveGate) {
            refreshTimer.current = setInterval(() => fetchPipelines(canEdit), 15000);
        } else if (refreshTimer.current) {
            clearInterval(refreshTimer.current);
            refreshTimer.current = null;
        }
        return () => {
            if (refreshTimer.current) clearInterval(refreshTimer.current);
        };
    }, [pipelines, qualityGates, fetchPipelines, canEdit]);

    const parseInputs = () => {
        const trimmed = triggerInputs.trim();
        if (!trimmed) return undefined;
        if (trimmed.startsWith('{')) return JSON.parse(trimmed);
        return Object.fromEntries(
            trimmed
                .split('\n')
                .map(line => line.trim())
                .filter(Boolean)
                .map(line => {
                    const [key, ...rest] = line.split('=');
                    return [key.trim(), rest.join('=').trim()];
                })
                .filter(([key]) => key),
        );
    };

    const handleTrigger = async () => {
        if (!canEdit) return;
        setTriggering(true);
        setTriggerError('');
        try {
            const res = await fetch(`${API_BASE}/projects/${pid}/ci/workflows/dispatch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: triggerProvider,
                    workflow_id: triggerProvider === 'github' ? triggerWorkflow || undefined : undefined,
                    ref: triggerRef || defaultRef,
                    inputs: parseInputs(),
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setTriggerError(data.detail || `Failed (${res.status})`);
                return;
            }
            setShowTrigger(false);
            setTriggerInputs('');
            await fetchPipelines(false);
        } catch (e: any) {
            setTriggerError(e.message || 'Failed to trigger workflow');
        } finally {
            setTriggering(false);
        }
    };

    const loadRunDetail = useCallback(async (run: CiRun, refresh = true) => {
        setSelectedRun(run);
        setRunLoading(true);
        setRunError('');
        setRunLogs(null);
        try {
            const res = await fetch(`${API_BASE}/projects/${pid}/ci/runs/${run.provider}/${run.id}?refresh=${refresh ? 'true' : 'false'}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setRunError(data.detail || `Failed (${res.status})`);
                return;
            }
            setSelectedRun(data.run);
            setRunJobs(data.jobs || []);
            setRunArtifacts(data.artifacts || []);
            setPipelines(prev => prev.map(item => item.provider === data.run.provider && String(item.id) === String(data.run.id) ? data.run : item));
        } catch (e: any) {
            setRunError(e.message || 'Failed to load run details');
        } finally {
            setRunLoading(false);
        }
    }, [pid]);

    const runAction = async (action: 'cancel' | 'rerun' | 'rerun-failed') => {
        if (!canEdit || !selectedRun) return;
        setRunActionLoading(action);
        setRunError('');
        try {
            const endpoint = action === 'cancel' ? 'cancel' : 'rerun';
            const res = await fetch(`${API_BASE}/projects/${pid}/ci/runs/${selectedRun.provider}/${selectedRun.id}/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: endpoint === 'rerun' ? JSON.stringify({ failed_only: action === 'rerun-failed' }) : undefined,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setRunError(data.detail || `Action failed (${res.status})`);
                return;
            }
            await loadRunDetail(selectedRun, true);
        } catch (e: any) {
            setRunError(e.message || 'Action failed');
        } finally {
            setRunActionLoading('');
        }
    };

    const loadLogs = async (jobId?: string) => {
        if (!selectedRun) return;
        setRunActionLoading('logs');
        setRunError('');
        try {
            const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
            const res = await fetch(`${API_BASE}/projects/${pid}/ci/runs/${selectedRun.provider}/${selectedRun.id}/logs${query}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setRunError(data.detail || `Failed to load logs (${res.status})`);
                return;
            }
            setRunLogs(data);
        } catch (e: any) {
            setRunError(e.message || 'Failed to load logs');
        } finally {
            setRunActionLoading('');
        }
    };

    const generateWorkflow = async (payload: any) => {
        if (!canEdit) {
            return {
                workflow_path: 'Read-only access',
                generated_yaml: '',
                validation_errors: ['Viewers cannot generate workflow change requests.'],
                validation_warnings: [],
            };
        }
        const res = await fetch(`${API_BASE}/projects/${pid}/ci/workflow-change-requests`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) return {
            workflow_path: 'Generation failed',
            generated_yaml: '',
            validation_errors: [data.detail || `Failed (${res.status})`],
            validation_warnings: [],
        };
        return data;
    };

    const openWorkflowPr = async (changeRequestId: string) => {
        if (!canEdit) throw new Error('Viewers cannot open workflow pull requests.');
        const res = await fetch(`${API_BASE}/projects/${pid}/ci/workflow-change-requests/${encodeURIComponent(changeRequestId)}/pull-request`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ draft: true }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `Failed to open PR (${res.status})`);
        await fetchProviders();
        return data;
    };

    const openTriggerPanel = (provider?: 'github' | 'gitlab') => {
        if (!canEdit) return;
        if (provider) setTriggerProvider(provider);
        setShowTrigger(true);
        window.setTimeout(() => triggerPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
    };

    const openWorkflowGenerator = () => {
        if (!canEdit) return;
        setShowWorkflowGenerator(true);
        window.setTimeout(() => workflowPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
    };

    const applyProviderAction = (provider: ProviderInfo) => {
        const action = provider.recommended_next_action;
        if (!action) return;
        if (action.action === 'open_settings') {
            window.location.href = action.href || '/settings';
            return;
        }
        if (action.action === 'generate_workflow') {
            if (!canEdit) return;
            openWorkflowGenerator();
            return;
        }
        if (action.action === 'open_trigger') {
            if (!canEdit) return;
            openTriggerPanel(provider.provider);
        }
    };

    const focusPrGate = () => {
        qualityGateRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const focusFailures = () => {
        setFilter('all');
        window.setTimeout(() => runsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
    };

    const startQualityGate = async () => {
        if (!canEdit) return;
        const pr = Number(gatePrNumber);
        if (!Number.isInteger(pr) || pr <= 0) {
            setGateError('Enter a valid PR number');
            return;
        }
        setStartingGate(true);
        setGateError('');
        try {
            const res = await fetch(`${API_BASE}/github/${pid}/quality-gates/pr/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pr_number: pr, ...qualityGateDefaults }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setGateError(data.detail || `Failed (${res.status})`);
                return;
            }
            setGatePrNumber('');
            await fetchQualityGates();
        } catch (e: any) {
            setGateError(e.message || 'Failed to start quality gate');
        } finally {
            setStartingGate(false);
        }
    };

    const loadQualityGateDetail = useCallback(async (analysisId: string, refreshFeedback = false) => {
        if (refreshFeedback && !canEdit) return null;
        setGateDetailLoading(true);
        setGateDetailError('');
        try {
            const suffix = refreshFeedback ? '?refresh_feedback=true' : '';
            const res = await fetch(`${API_BASE}/github/${pid}/quality-gates/pr/${encodeURIComponent(analysisId)}${suffix}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setGateDetailError(data.detail || `Failed to load gate (${res.status})`);
                return null;
            }
            setSelectedGate(data);
            setQualityGates(prev => prev.map(item => item.id === data.id ? data : item));
            return data as QualityGate;
        } catch (e: any) {
            setGateDetailError(e.message || 'Failed to load gate');
            return null;
        } finally {
            setGateDetailLoading(false);
        }
    }, [canEdit, pid]);

    const selectQualityGate = useCallback((gate: QualityGate) => {
        setSelectedGate(gate);
        loadQualityGateDetail(gate.id);
    }, [loadQualityGateDetail]);

    const rerunQualityGate = async () => {
        if (!canEdit || !selectedGate) return;
        setGateActionLoading('rerun');
        setGateDetailError('');
        try {
            const res = await fetch(`${API_BASE}/github/${pid}/pr-advisor/analyses/${encodeURIComponent(selectedGate.id)}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    browser: qualityGateDefaults.browser,
                    hybrid: qualityGateDefaults.hybrid,
                    max_iterations: qualityGateDefaults.max_iterations,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setGateDetailError(data.detail || `Rerun failed (${res.status})`);
                return;
            }
            await loadQualityGateDetail(selectedGate.id);
            await fetchQualityGates();
        } catch (e: any) {
            setGateDetailError(e.message || 'Rerun failed');
        } finally {
            setGateActionLoading('');
        }
    };

    const filteredPipelines = filter === 'all' ? pipelines : pipelines.filter(p => p.provider === filter);
    const activeGate = qualityGates.some(g => ['running', 'analyzed'].includes(g.quality_gate?.state));

    const gateCounts = useMemo(() => {
        const counts: Record<GateState, number> = { all: qualityGates.length, running: 0, failed: 0, passed: 0, 'needs-full-suite': 0 };
        qualityGates.forEach(gate => {
            const state = gate.quality_gate?.state;
            if (state === 'running' || state === 'analyzed') counts.running += 1;
            if (state === 'failed' || state === 'blocked') counts.failed += 1;
            if (state === 'passed') counts.passed += 1;
            if (state === 'needs-full-suite') counts['needs-full-suite'] += 1;
        });
        return counts;
    }, [qualityGates]);

    const filteredQualityGates = useMemo(() => {
        if (gateFilter === 'all') return qualityGates;
        return qualityGates.filter(gate => {
            const state = gate.quality_gate?.state;
            if (gateFilter === 'running') return state === 'running' || state === 'analyzed';
            if (gateFilter === 'failed') return state === 'failed' || state === 'blocked';
            return state === gateFilter;
        });
    }, [qualityGates, gateFilter]);

    const providerSummary = useMemo(() => providers.map(provider => ({
        ...provider,
        label: provider.provider === 'github' ? 'GitHub Actions' : 'GitLab CI',
        statusLabel: provider.setup_status === 'ready'
            ? 'Ready'
            : provider.setup_status === 'not_configured'
                ? 'Not connected'
                : 'Needs setup',
        repositoryLabel: provider.repository || (provider.provider === 'github' ? 'No repository selected' : 'No project selected'),
    })), [providers]);

    const failedRuns = pipelines.filter(run => ['failed', 'failure'].includes(run.status));
    const readyProviders = providers.filter(provider => provider.setup_status === 'ready');
    const setupNeeds = providers.flatMap(provider => provider.missing_requirements || []);
    const emptyDescription = !anyProviderConfigured
        ? 'Connect GitHub or GitLab in Settings. After that this page can trigger runs, sync provider history, and inspect logs.'
        : setupNeeds.includes('select_or_generate_workflow')
            ? 'GitHub is connected, but no default workflow is selected. Generate a workflow draft or select an existing workflow in Settings.'
            : 'Run a pipeline from the control cards above or refresh provider history after a repository push.';

    const tabStyle = (tab: ProviderFilter): CSSProperties => ({
        padding: '0.6rem 1.25rem',
        cursor: 'pointer',
        border: 'none',
        borderBottom: filter === tab ? '2px solid var(--primary)' : '2px solid transparent',
        color: filter === tab ? 'var(--primary)' : 'var(--text-secondary)',
        fontWeight: filter === tab ? 700 : 500,
        background: 'transparent',
        fontSize: '0.9rem',
    });

    if (loading) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="CI/CD Pipelines"
                subtitle="Control provider workflows, PR gates, and release evidence"
                icon={<GitBranch size={20} />}
                actions={
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        {canEdit && anyProviderConfigured && (
                            <button type="button" onClick={() => setShowTrigger(!showTrigger)} style={primaryButtonStyle}>
                                <Play size={14} />
                                Trigger
                                {showTrigger ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={() => fetchPipelines(canEdit)}
                            disabled={syncing}
                            style={secondaryButtonStyle(syncing)}
                        >
                            <RefreshCw size={14} style={syncing ? { animation: 'spin 1s linear infinite' } : undefined} />
                            {syncing ? 'Syncing...' : 'Refresh'}
                        </button>
                    </div>
                }
            />

            <section style={{ ...panelStyle, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.85rem' }}>
                {providerSummary.map(provider => (
                    <div key={provider.provider} style={statusCardStyle(provider.setup_status === 'ready')}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'flex-start' }}>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', fontWeight: 750 }}>{provider.label}</div>
                                <div style={{ marginTop: '0.25rem', fontSize: '1rem', fontWeight: 850 }}>{provider.statusLabel}</div>
                            </div>
                            <span style={provider.setup_status === 'ready' ? readyBadgeStyle : warningBadgeStyle}>
                                {provider.setup_status === 'ready' ? 'Ready' : 'Setup'}
                            </span>
                        </div>
                        <div style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45 }}>
                            <div>{provider.repositoryLabel}</div>
                            <div>Default ref: {provider.default_ref || 'main'}</div>
                            <div>Last sync: {provider.last_sync_at ? new Date(provider.last_sync_at).toLocaleString() : 'No synced runs yet'}</div>
                        </div>
                        {(provider.missing_requirements || []).length > 0 && (
                            <div style={{ marginTop: '0.7rem', display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                                {(provider.missing_requirements || []).slice(0, 3).map(item => (
                                    <span key={item} style={smallTagStyle}>{formatRequirement(item)}</span>
                                ))}
                            </div>
                        )}
                        {provider.recommended_next_action && (canEdit || provider.recommended_next_action.action === 'open_settings') && (
                            <button type="button" onClick={() => applyProviderAction(provider)} style={{ ...secondaryButtonStyle(false), marginTop: '0.85rem', width: '100%', justifyContent: 'center' }}>
                                <Settings size={14} />
                                {provider.recommended_next_action.label}
                            </button>
                        )}
                    </div>
                ))}
            </section>

            <section style={{ marginBottom: '1rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0.75rem' }}>
                    <button type="button" onClick={() => openTriggerPanel(readyProviders[0]?.provider)} disabled={!canEdit || readyProviders.length === 0} style={taskButtonStyle(!canEdit || readyProviders.length === 0)}>
                        <Play size={18} />
                        <span style={taskTextStyle}>
                            <strong style={taskTitleStyle}>Run pipeline</strong>
                            <small style={taskDescriptionStyle}>Dispatch a GitHub workflow or GitLab pipeline.</small>
                        </span>
                    </button>
                    <button type="button" onClick={focusPrGate} disabled={!canEdit || !ghConfigured} style={taskButtonStyle(!canEdit || !ghConfigured)}>
                        <ShieldCheck size={18} />
                        <span style={taskTextStyle}>
                            <strong style={taskTitleStyle}>Start PR gate</strong>
                            <small style={taskDescriptionStyle}>Analyze a PR and run recommended tests.</small>
                        </span>
                    </button>
                    <button type="button" onClick={openWorkflowGenerator} disabled={!canEdit || !ghConfigured} style={taskButtonStyle(!canEdit || !ghConfigured)}>
                        <Code2 size={18} />
                        <span style={taskTextStyle}>
                            <strong style={taskTitleStyle}>Generate workflow</strong>
                            <small style={taskDescriptionStyle}>Create a reviewed GitHub Actions draft.</small>
                        </span>
                    </button>
                    <button type="button" onClick={focusFailures} disabled={failedRuns.length === 0} style={taskButtonStyle(failedRuns.length === 0)}>
                        <Search size={18} />
                        <span style={taskTextStyle}>
                            <strong style={taskTitleStyle}>Investigate failure</strong>
                            <small style={taskDescriptionStyle}>{failedRuns.length ? `${failedRuns.length} failed run${failedRuns.length === 1 ? '' : 's'} need review.` : 'No failed runs right now.'}</small>
                        </span>
                    </button>
                </div>
            </section>

            {canEdit && showTrigger && anyProviderConfigured && (
                <section ref={triggerPanelRef} style={panelStyle}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.85rem', fontWeight: 800 }}>
                        <Activity size={16} />
                        Run Pipeline
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem', alignItems: 'end' }}>
                        <label style={fieldStyle}>
                            Provider
                            <select value={triggerProvider} onChange={e => setTriggerProvider(e.target.value as 'github' | 'gitlab')} style={inputStyle}>
                                {ghConfigured && <option value="github">GitHub Actions</option>}
                                {glConfigured && <option value="gitlab">GitLab CI</option>}
                            </select>
                        </label>
                        {triggerProvider === 'github' && (
                            <label style={fieldStyle}>
                                Workflow
                                <select value={triggerWorkflow} onChange={e => setTriggerWorkflow(e.target.value)} style={inputStyle}>
                                    <option value="">Default workflow</option>
                                    {workflows.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
                                </select>
                            </label>
                        )}
                        <label style={fieldStyle}>
                            Ref
                            <input value={triggerRef} onChange={e => setTriggerRef(e.target.value)} placeholder={defaultRef} style={inputStyle} />
                        </label>
                        <label style={{ ...fieldStyle, gridColumn: 'span 2' }}>
                            Inputs
                            <textarea value={triggerInputs} onChange={e => setTriggerInputs(e.target.value)} rows={2} placeholder="key=value per line or JSON object" style={{ ...inputStyle, resize: 'vertical' }} />
                        </label>
                        <button type="button" onClick={handleTrigger} disabled={triggering} style={{ ...primaryButtonStyle, justifyContent: 'center', height: 39 }}>
                            {triggering ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
                            {triggering ? 'Running...' : 'Run'}
                        </button>
                    </div>
                    {triggerError && <div style={{ marginTop: '0.5rem', color: 'var(--danger)', fontSize: '0.82rem' }}>{triggerError}</div>}
                </section>
            )}

            {canEdit && showWorkflowGenerator && (
                <div ref={workflowPanelRef}>
                    <WorkflowGeneratorPanel onGenerate={generateWorkflow} onOpenPr={openWorkflowPr} onClose={() => setShowWorkflowGenerator(false)} />
                </div>
            )}

            <section ref={qualityGateRef} className="animate-in stagger-1" style={sectionStyle}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800 }}>
                            <GitPullRequest size={17} />
                            PR Quality Gates
                        </div>
                        <div style={{ marginTop: '0.2rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                            Changed-file-aware Quorvex test selection and merge confidence.
                        </div>
                    </div>
                    {canEdit && ghConfigured && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                            <input value={gatePrNumber} onChange={e => setGatePrNumber(e.target.value)} placeholder="PR #" inputMode="numeric" style={{ ...inputStyle, width: 100 }} />
                            <button type="button" onClick={startQualityGate} disabled={startingGate} style={primaryButtonStyle}>
                                {startingGate ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <ShieldCheck size={14} />}
                                {startingGate ? 'Starting...' : 'Start Gate'}
                            </button>
                        </div>
                    )}
                </div>
                {gateError && <div style={{ padding: '0.65rem 1.25rem', color: 'var(--danger)', fontSize: '0.82rem', borderBottom: '1px solid var(--border)' }}>{gateError}</div>}
                {!ghConfigured ? (
                    <div style={{ padding: '1rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                        Configure GitHub in Settings to start PR quality gates.
                    </div>
                ) : qualityGates.length === 0 ? (
                    <div style={{ padding: '1rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>No PR quality gates yet.</div>
                ) : (
                    <>
                        <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', padding: '0.8rem 1rem 0' }}>
                            {[
                                ['all', 'All'],
                                ['running', 'Running'],
                                ['failed', 'Failed'],
                                ['passed', 'Passed'],
                                ['needs-full-suite', 'Needs full suite'],
                            ].map(([value, label]) => (
                                <button key={value} type="button" onClick={() => setGateFilter(value as GateState)} style={pillStyle(gateFilter === value)}>
                                    {label} <span style={{ opacity: 0.8 }}>{gateCounts[value as GateState]}</span>
                                </button>
                            ))}
                        </div>
                        {filteredQualityGates.length === 0 ? (
                            <div style={{ padding: '1rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>No gates match this filter.</div>
                        ) : (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem', padding: '1rem' }}>
                                {filteredQualityGates.map(gate => (
                                    <QualityGateCard key={gate.id} gate={gate} selected={selectedGate?.id === gate.id} onSelect={selectQualityGate} />
                                ))}
                            </div>
                        )}
                    </>
                )}
            </section>

            <div className={!canEdit ? 'ci-cd-read-only-quality-drawer' : undefined}>
                <QualityGateDetailDrawer
                    gate={selectedGate}
                    loading={gateDetailLoading}
                    actionLoading={gateActionLoading}
                    error={gateDetailError}
                    onClose={() => setSelectedGate(null)}
                    onRefresh={() => selectedGate && loadQualityGateDetail(selectedGate.id)}
                    onRerun={canEdit ? rerunQualityGate : () => {}}
                    onPublishFeedback={canEdit ? () => selectedGate && loadQualityGateDetail(selectedGate.id, true) : () => {}}
                />
            </div>

            <RunDetailDrawer
                run={selectedRun && !canEdit ? {
                    ...selectedRun,
                    action_availability: {
                        ...selectedRun.action_availability,
                        can_cancel: false,
                        can_rerun: false,
                        can_rerun_failed: false,
                        disabled_reason: 'Read-only access',
                    },
                } : selectedRun}
                jobs={runJobs}
                artifacts={runArtifacts}
                loading={runLoading}
                actionLoading={runActionLoading}
                error={runError}
                logs={runLogs}
                onClose={() => setSelectedRun(null)}
                onRefresh={() => selectedRun && loadRunDetail(selectedRun, true)}
                onCancel={() => runAction('cancel')}
                onRerun={failedOnly => runAction(failedOnly ? 'rerun-failed' : 'rerun')}
                onLoadLogs={loadLogs}
            />

            <div ref={runsRef} className="animate-in stagger-2">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 850 }}>Pipeline Runs</h2>
                        <div style={{ marginTop: '0.2rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                            Click a run to open jobs, artifacts, logs, rerun, or cancel controls.
                        </div>
                    </div>
                    {failedRuns.length > 0 && (
                        <span style={warningBadgeStyle}>
                            <CircleAlert size={13} />
                            {failedRuns.length} failed
                        </span>
                    )}
                </div>
                <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
                    <button type="button" style={tabStyle('all')} onClick={() => setFilter('all')}>All ({pipelines.length})</button>
                    <button type="button" style={tabStyle('gitlab')} onClick={() => setFilter('gitlab')}>GitLab ({pipelines.filter(p => p.provider === 'gitlab').length})</button>
                    <button type="button" style={tabStyle('github')} onClick={() => setFilter('github')}>GitHub ({pipelines.filter(p => p.provider === 'github').length})</button>
                </div>
            </div>

            {filteredPipelines.length === 0 ? (
                <EmptyState
                    icon={<GitBranch size={32} />}
                    title={anyProviderConfigured ? 'No workflow runs found' : 'No pipelines tracked yet'}
                    description={emptyDescription}
                />
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {filteredPipelines.map(pipeline => (
                        <div key={`${pipeline.provider}-${pipeline.id || pipeline.external_pipeline_id}`} role="button" tabIndex={0} onClick={() => loadRunDetail(pipeline, true)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') loadRunDetail(pipeline, true); }} style={{ cursor: 'pointer' }}>
                            <PipelineStatusCard pipeline={pipeline} />
                        </div>
                    ))}
                </div>
            )}

            {(pipelines.some(p => activeStatuses.includes(p.status)) || activeGate) && (
                <div style={{ marginTop: '1rem', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
                    Auto-refreshing active work every 15 seconds
                </div>
            )}

            <style jsx>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
            <style jsx global>{`
                .ci-cd-read-only-quality-drawer aside > div:nth-child(2) button:nth-of-type(2),
                .ci-cd-read-only-quality-drawer aside > div:nth-child(2) button:nth-of-type(3) {
                    display: none !important;
                }
            `}</style>
        </PageLayout>
    );
}

const inputStyle: CSSProperties = {
    width: '100%',
    padding: '0.48rem 0.55rem',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--background)',
    color: 'var(--text)',
    fontSize: '0.85rem',
};

const fieldStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.35rem',
    fontSize: '0.78rem',
    color: 'var(--text-secondary)',
};

const primaryButtonStyle: CSSProperties = {
    padding: '0.5rem 0.75rem',
    background: 'var(--primary)',
    border: 'none',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    color: '#fff',
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    fontSize: '0.85rem',
    fontWeight: 750,
};

const secondaryButtonStyle = (disabled?: boolean): CSSProperties => ({
    padding: '0.5rem 0.75rem',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    cursor: disabled ? 'default' : 'pointer',
    color: 'var(--text-secondary)',
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    fontSize: '0.85rem',
    opacity: disabled ? 0.6 : 1,
});

const panelStyle: CSSProperties = {
    padding: '1rem 1.25rem',
    marginBottom: '1rem',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
};

const sectionStyle: CSSProperties = {
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--surface)',
    marginBottom: '1.5rem',
    overflow: 'hidden',
};

function pillStyle(active: boolean): CSSProperties {
    return {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.35rem',
        padding: '0.4rem 0.65rem',
        border: active ? '1px solid var(--primary)' : '1px solid var(--border)',
        borderRadius: '999px',
        background: active ? 'rgba(59, 130, 246, 0.08)' : 'var(--background)',
        color: active ? 'var(--primary)' : 'var(--text-secondary)',
        cursor: 'pointer',
        fontSize: '0.78rem',
        fontWeight: 750,
    };
}

function formatRequirement(value: string): string {
    return value
        .split('_')
        .map(part => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

function statusCardStyle(ready: boolean): CSSProperties {
    return {
        border: ready ? '1px solid rgba(34, 197, 94, 0.32)' : '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        background: 'var(--background)',
        padding: '0.95rem',
        minWidth: 0,
    };
}

function taskButtonStyle(disabled: boolean): CSSProperties {
    return {
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        background: 'var(--surface)',
        color: 'var(--text)',
        padding: '0.9rem',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '0.75rem',
        textAlign: 'left',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.58 : 1,
        minHeight: 88,
    };
}

const readyBadgeStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.3rem',
    padding: '0.25rem 0.5rem',
    borderRadius: '999px',
    background: 'rgba(34, 197, 94, 0.1)',
    color: 'var(--success)',
    fontSize: '0.72rem',
    fontWeight: 800,
    flexShrink: 0,
};

const warningBadgeStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.3rem',
    padding: '0.25rem 0.5rem',
    borderRadius: '999px',
    background: 'rgba(245, 158, 11, 0.1)',
    color: 'var(--warning)',
    fontSize: '0.72rem',
    fontWeight: 800,
    flexShrink: 0,
};

const smallTagStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '0.2rem 0.45rem',
    borderRadius: '999px',
    background: 'rgba(128, 128, 128, 0.1)',
    border: '1px solid rgba(128, 128, 128, 0.15)',
    color: 'var(--text-secondary)',
    fontSize: '0.7rem',
    fontWeight: 700,
};

const taskTextStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
    minWidth: 0,
};

const taskTitleStyle: CSSProperties = {
    display: 'block',
    fontSize: '0.9rem',
    lineHeight: 1.25,
};

const taskDescriptionStyle: CSSProperties = {
    display: 'block',
    color: 'var(--text-secondary)',
    fontSize: '0.8rem',
    lineHeight: 1.35,
};
