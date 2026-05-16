'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { GitBranch, Loader2, RefreshCw, Play, ChevronDown, ChevronUp, GitPullRequest, ShieldCheck } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PipelineStatusCard } from '@/components/PipelineStatusCard';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { QualityGateCard } from './components/QualityGateCard';
import { QualityGateDetailDrawer } from './components/QualityGateDetailDrawer';
import type { GateState, QualityGate, QualityGateDefaults } from './components/types';
import { FALLBACK_QUALITY_GATE_DEFAULTS, resolveQualityGateDefaults } from './components/types';

type ProviderFilter = 'all' | 'gitlab' | 'github';

interface Pipeline {
    id: string;
    provider: 'gitlab' | 'github';
    external_pipeline_id: string;
    external_project_id?: string;
    status: string;
    ref?: string;
    external_url?: string;
    triggered_from?: string;
    name?: string;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
    total_tests?: number;
    passed_tests?: number;
    failed_tests?: number;
}

interface GhWorkflow {
    id: number;
    name: string;
    path: string;
    state: string;
}

export default function CiCdPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || (typeof window !== 'undefined' ? localStorage.getItem('selectedProjectId') : null) || 'default';
    const pid = encodeURIComponent(projectId);

    const [pipelines, setPipelines] = useState<Pipeline[]>([]);
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [filter, setFilter] = useState<ProviderFilter>('all');
    const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);
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

    // GitHub config state
    const [ghConfigured, setGhConfigured] = useState(false);
    const [ghWorkflows, setGhWorkflows] = useState<GhWorkflow[]>([]);
    const [ghDefaultWorkflow, setGhDefaultWorkflow] = useState<string | null>(null);
    const [ghDefaultRef, setGhDefaultRef] = useState('main');

    // Trigger panel state
    const [showTrigger, setShowTrigger] = useState(false);
    const [triggerWorkflow, setTriggerWorkflow] = useState('');
    const [triggerRef, setTriggerRef] = useState('');
    const [triggering, setTriggering] = useState(false);
    const [triggerError, setTriggerError] = useState('');

    // Check GitHub config on mount
    useEffect(() => {
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/github/${pid}/config`);
                if (res.ok) {
                    const data = await res.json();
                    setGhConfigured(!!data.configured);
                    if (data.default_workflow) setGhDefaultWorkflow(data.default_workflow);
                    if (data.default_ref) setGhDefaultRef(data.default_ref);
                    setQualityGateDefaults(resolveQualityGateDefaults(data));

                    if (data.configured) {
                        const wfRes = await fetch(`${API_BASE}/github/${pid}/remote-workflows`);
                        if (wfRes.ok) {
                            const wfs = await wfRes.json();
                            setGhWorkflows(wfs || []);
                        }
                    }
                }
            } catch { /* ignore */ }
        })();
    }, [pid]);

    const syncGithubRuns = useCallback(async () => {
        try {
            await fetch(`${API_BASE}/github/${pid}/sync-runs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ per_page: 20 }),
            });
        } catch { /* ignore sync errors */ }
    }, [pid]);

    const fetchQualityGates = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/github/${pid}/quality-gates/pr?limit=20`);
            if (res.ok) {
                const gates = await res.json();
                setQualityGates(gates);
                setSelectedGate(prev => prev ? (gates.find((gate: QualityGate) => gate.id === prev.id) || prev) : prev);
            }
        } catch { /* ignore */ }
    }, [pid]);

    const loadQualityGateDetail = useCallback(async (analysisId: string, refreshFeedback = false) => {
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
    }, [pid]);

    const selectQualityGate = useCallback((gate: QualityGate) => {
        setSelectedGate(gate);
        loadQualityGateDetail(gate.id);
        if (typeof window !== 'undefined') {
            const params = new URLSearchParams(window.location.search);
            params.set('gate', gate.id);
            window.history.replaceState(null, '', `/ci-cd?${params.toString()}`);
        }
    }, [loadQualityGateDetail]);

    const fetchPipelines = useCallback(async (doSync = false) => {
        if (doSync) {
            setSyncing(true);
            await syncGithubRuns();
            setSyncing(false);
        }

        try {
            const results: Pipeline[] = [];

            // Fetch GitLab pipelines
            const glRes = await fetch(`${API_BASE}/gitlab/${pid}/pipelines`).catch(() => null);
            if (glRes?.ok) {
                const glData = await glRes.json();
                results.push(...(glData || []).map((p: any) => ({ ...p, provider: 'gitlab' as const })));
            }

            // Fetch GitHub pipelines
            const ghRes = await fetch(`${API_BASE}/github/${pid}/pipelines`).catch(() => null);
            if (ghRes?.ok) {
                const ghData = await ghRes.json();
                results.push(...(ghData || []).map((p: any) => ({ ...p, provider: 'github' as const })));
            }

            // Sort by created_at desc
            results.sort((a, b) => {
                const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
                const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
                return tb - ta;
            });

            setPipelines(results);
        } catch { /* ignore */ }
        await fetchQualityGates();
        setLoading(false);
    }, [pid, syncGithubRuns, fetchQualityGates]);

    // Initial load with sync
    useEffect(() => {
        setLoading(true);
        fetchPipelines(true);
    }, [fetchPipelines]);

    useEffect(() => {
        if (typeof window === 'undefined' || selectedGate || qualityGates.length === 0) return;
        const gateId = new URLSearchParams(window.location.search).get('gate');
        if (!gateId) return;
        const gate = qualityGates.find(item => item.id === gateId);
        if (gate) {
            setSelectedGate(gate);
            loadQualityGateDetail(gate.id);
        }
    }, [qualityGates, selectedGate, loadQualityGateDetail]);

    // Auto-refresh every 15 seconds if any pipeline is active
    useEffect(() => {
        const hasActive = pipelines.some(p =>
            ['pending', 'running', 'queued', 'waiting', 'in_progress'].includes(p.status)
        );
        const hasActiveGate = qualityGates.some(g => ['running', 'analyzed'].includes(g.quality_gate?.state));

        if (hasActive || hasActiveGate) {
            refreshTimer.current = setInterval(() => fetchPipelines(true), 15000);
        } else if (refreshTimer.current) {
            clearInterval(refreshTimer.current);
            refreshTimer.current = null;
        }

        return () => {
            if (refreshTimer.current) clearInterval(refreshTimer.current);
        };
    }, [pipelines, qualityGates, fetchPipelines]);

    const handleTrigger = async () => {
        setTriggering(true);
        setTriggerError('');
        try {
            const res = await fetch(`${API_BASE}/github/${pid}/trigger-workflow`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflow_id: triggerWorkflow || ghDefaultWorkflow || undefined,
                    ref: triggerRef || ghDefaultRef || 'main',
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                setTriggerError(err.detail || `Failed (${res.status})`);
            } else {
                setShowTrigger(false);
                // Wait for GitHub to create the run, then sync
                setTimeout(() => fetchPipelines(true), 2000);
            }
        } catch (e: any) {
            setTriggerError(e.message || 'Failed to trigger');
        }
        setTriggering(false);
    };

    const startQualityGate = async () => {
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
                body: JSON.stringify({
                    pr_number: pr,
                    ...qualityGateDefaults,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setGateError(data.detail || `Failed (${res.status})`);
                return;
            }
            setGatePrNumber('');
            await fetchQualityGates();
            setTimeout(() => fetchQualityGates(), 3000);
        } catch (e: any) {
            setGateError(e.message || 'Failed to start quality gate');
        } finally {
            setStartingGate(false);
        }
    };

    const rerunQualityGate = async () => {
        if (!selectedGate) return;
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
            const updated = await loadQualityGateDetail(selectedGate.id);
            if (!updated && data.batch_id) {
                setSelectedGate(prev => prev ? { ...prev, batch_id: data.batch_id } : prev);
            }
            await fetchQualityGates();
            setTimeout(() => fetchQualityGates(), 3000);
        } catch (e: any) {
            setGateDetailError(e.message || 'Rerun failed');
        } finally {
            setGateActionLoading('');
        }
    };

    const publishQualityGateFeedback = async () => {
        if (!selectedGate) return;
        setGateActionLoading('feedback');
        await loadQualityGateDetail(selectedGate.id, true);
        setGateActionLoading('');
    };

    const filteredPipelines = filter === 'all'
        ? pipelines
        : pipelines.filter(p => p.provider === filter);

    const activeGate = qualityGates.some(g => ['running', 'analyzed'].includes(g.quality_gate?.state));

    const gateCounts = useMemo(() => {
        const counts: Record<GateState, number> = {
            all: qualityGates.length,
            running: 0,
            failed: 0,
            passed: 0,
            'needs-full-suite': 0,
        };
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

    const tabStyle = (tab: ProviderFilter): React.CSSProperties => ({
        padding: '0.6rem 1.25rem',
        cursor: 'pointer',
        border: 'none',
        borderBottom: filter === tab ? '2px solid var(--primary)' : '2px solid transparent',
        color: filter === tab ? 'var(--primary)' : 'var(--text-secondary)',
        fontWeight: filter === tab ? 600 : 400,
        background: 'transparent',
        fontSize: '0.9rem',
        transition: 'all 0.2s var(--ease-smooth)',
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
                subtitle="Track pipeline executions across providers"
                icon={<GitBranch size={20} />}
                actions={
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        {ghConfigured && (
                            <button
                                onClick={() => setShowTrigger(!showTrigger)}
                                style={{
                                    padding: '0.5rem 0.75rem',
                                    background: 'var(--primary)',
                                    border: 'none',
                                    borderRadius: 'var(--radius)',
                                    cursor: 'pointer',
                                    color: '#fff',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    fontSize: '0.85rem',
                                    fontWeight: 600,
                                }}
                            >
                                <Play size={14} />
                                Trigger
                                {showTrigger ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                        )}
                        <button
                            onClick={() => { setSyncing(true); fetchPipelines(true); }}
                            disabled={syncing}
                            style={{
                                padding: '0.5rem 0.75rem',
                                background: 'transparent',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                cursor: syncing ? 'default' : 'pointer',
                                color: 'var(--text-secondary)',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                fontSize: '0.85rem',
                                opacity: syncing ? 0.6 : 1,
                            }}
                        >
                            <RefreshCw size={14} style={syncing ? { animation: 'spin 1s linear infinite' } : undefined} />
                            {syncing ? 'Syncing...' : 'Refresh'}
                        </button>
                    </div>
                }
            />

            {/* Trigger panel */}
            {showTrigger && ghConfigured && (
                <div style={{
                    padding: '1rem 1.25rem',
                    marginBottom: '1rem',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                }}>
                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                        <div style={{ flex: 1, minWidth: '200px' }}>
                            <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                                Workflow
                            </label>
                            <select
                                value={triggerWorkflow}
                                onChange={e => setTriggerWorkflow(e.target.value)}
                                style={{
                                    width: '100%',
                                    padding: '0.45rem 0.5rem',
                                    background: 'var(--background)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    color: 'var(--text)',
                                    fontSize: '0.85rem',
                                }}
                            >
                                <option value="">{ghDefaultWorkflow ? `Default (${ghDefaultWorkflow})` : 'Select workflow...'}</option>
                                {ghWorkflows.map(w => (
                                    <option key={w.id} value={String(w.id)}>{w.name}</option>
                                ))}
                            </select>
                        </div>
                        <div style={{ minWidth: '140px' }}>
                            <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                                Branch
                            </label>
                            <input
                                type="text"
                                placeholder={ghDefaultRef || 'main'}
                                value={triggerRef}
                                onChange={e => setTriggerRef(e.target.value)}
                                style={{
                                    width: '100%',
                                    padding: '0.45rem 0.5rem',
                                    background: 'var(--background)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    color: 'var(--text)',
                                    fontSize: '0.85rem',
                                }}
                            />
                        </div>
                        <button
                            onClick={handleTrigger}
                            disabled={triggering}
                            style={{
                                padding: '0.45rem 1rem',
                                background: 'var(--primary)',
                                border: 'none',
                                borderRadius: 'var(--radius)',
                                cursor: triggering ? 'default' : 'pointer',
                                color: '#fff',
                                fontSize: '0.85rem',
                                fontWeight: 600,
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                opacity: triggering ? 0.7 : 1,
                            }}
                        >
                            {triggering ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
                            {triggering ? 'Running...' : 'Run'}
                        </button>
                    </div>
                    {triggerError && (
                        <div style={{ marginTop: '0.5rem', color: 'var(--danger)', fontSize: '0.8rem' }}>
                            {triggerError}
                        </div>
                    )}
                </div>
            )}

            {/* PR quality gates */}
            <section className="animate-in stagger-1" style={{
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                background: 'var(--surface)',
                marginBottom: '1.5rem',
                overflow: 'hidden',
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '1rem',
                    padding: '1rem 1.25rem',
                    borderBottom: '1px solid var(--border)',
                    flexWrap: 'wrap',
                }}>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700 }}>
                            <GitPullRequest size={17} />
                            PR Quality Gates
                        </div>
                        <div style={{ marginTop: '0.2rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                            Changed-file-aware Quorvex test selection and merge confidence.
                        </div>
                    </div>
                    {ghConfigured && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                            <input
                                value={gatePrNumber}
                                onChange={e => setGatePrNumber(e.target.value)}
                                placeholder="PR #"
                                inputMode="numeric"
                                style={{
                                    width: '100px',
                                    padding: '0.48rem 0.55rem',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    background: 'var(--background)',
                                    color: 'var(--text)',
                                    fontSize: '0.85rem',
                                }}
                            />
                            <button
                                onClick={startQualityGate}
                                disabled={startingGate}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    padding: '0.5rem 0.75rem',
                                    border: 'none',
                                    borderRadius: 'var(--radius)',
                                    color: '#fff',
                                    background: 'var(--primary)',
                                    cursor: startingGate ? 'default' : 'pointer',
                                    fontWeight: 700,
                                    fontSize: '0.85rem',
                                    opacity: startingGate ? 0.7 : 1,
                                }}
                            >
                                {startingGate ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <ShieldCheck size={14} />}
                                {startingGate ? 'Starting...' : 'Start Gate'}
                            </button>
                        </div>
                    )}
                </div>
                {gateError && (
                    <div style={{ padding: '0.65rem 1.25rem', color: 'var(--danger)', fontSize: '0.82rem', borderBottom: '1px solid var(--border)' }}>
                        {gateError}
                    </div>
                )}
                {!ghConfigured ? (
                    <div style={{ padding: '1rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                        Configure GitHub in Settings to start PR quality gates.
                    </div>
                ) : qualityGates.length === 0 ? (
                    <div style={{ padding: '1rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                        No PR quality gates yet.
                    </div>
                ) : (
                    <>
                        <div style={{
                            display: 'flex',
                            gap: '0.45rem',
                            flexWrap: 'wrap',
                            padding: '0.8rem 1rem 0',
                        }}>
                            {[
                                ['all', 'All'],
                                ['running', 'Running'],
                                ['failed', 'Failed'],
                                ['passed', 'Passed'],
                                ['needs-full-suite', 'Needs full suite'],
                            ].map(([value, label]) => (
                                <button
                                    key={value}
                                    type="button"
                                    onClick={() => setGateFilter(value as GateState)}
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '0.35rem',
                                        padding: '0.4rem 0.65rem',
                                        border: gateFilter === value ? '1px solid var(--primary)' : '1px solid var(--border)',
                                        borderRadius: '999px',
                                        background: gateFilter === value ? 'rgba(59, 130, 246, 0.08)' : 'var(--background)',
                                        color: gateFilter === value ? 'var(--primary)' : 'var(--text-secondary)',
                                        cursor: 'pointer',
                                        fontSize: '0.78rem',
                                        fontWeight: 750,
                                    }}
                                >
                                    {label}
                                    <span style={{ color: 'inherit', opacity: 0.8 }}>{gateCounts[value as GateState]}</span>
                                </button>
                            ))}
                        </div>
                        {filteredQualityGates.length === 0 ? (
                            <div style={{ padding: '1rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                No gates match this filter.
                            </div>
                        ) : (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem', padding: '1rem' }}>
                                {filteredQualityGates.map(gate => (
                                    <QualityGateCard
                                        key={gate.id}
                                        gate={gate}
                                        selected={selectedGate?.id === gate.id}
                                        onSelect={selectQualityGate}
                                    />
                                ))}
                            </div>
                        )}
                    </>
                )}
            </section>

            <QualityGateDetailDrawer
                gate={selectedGate}
                loading={gateDetailLoading}
                actionLoading={gateActionLoading}
                error={gateDetailError}
                onClose={() => {
                    setSelectedGate(null);
                    if (typeof window !== 'undefined') {
                        window.history.replaceState(null, '', '/ci-cd');
                    }
                }}
                onRefresh={() => selectedGate && loadQualityGateDetail(selectedGate.id)}
                onRerun={rerunQualityGate}
                onPublishFeedback={publishQualityGateFeedback}
            />

            {/* Provider filter tabs */}
            <div className="animate-in stagger-2" style={{
                display: 'flex',
                borderBottom: '1px solid var(--border)',
                marginBottom: '1.5rem',
            }}>
                <button style={tabStyle('all')} onClick={() => setFilter('all')}>
                    All ({pipelines.length})
                </button>
                <button style={tabStyle('gitlab')} onClick={() => setFilter('gitlab')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '18px',
                            height: '18px',
                            borderRadius: '50%',
                            background: 'rgba(252, 109, 38, 0.15)',
                            color: '#fc6d26',
                            fontSize: '0.6rem',
                            fontWeight: 700,
                        }}>GL</span>
                        GitLab ({pipelines.filter(p => p.provider === 'gitlab').length})
                    </span>
                </button>
                <button style={tabStyle('github')} onClick={() => setFilter('github')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '18px',
                            height: '18px',
                            borderRadius: '50%',
                            background: 'rgba(255, 255, 255, 0.1)',
                            fontSize: '0.6rem',
                            fontWeight: 700,
                        }}>GH</span>
                        GitHub ({pipelines.filter(p => p.provider === 'github').length})
                    </span>
                </button>
            </div>

            {/* Pipeline list */}
            {filteredPipelines.length === 0 ? (
                <EmptyState
                    icon={<GitBranch size={32} />}
                    title={ghConfigured ? 'No workflow runs found' : 'No pipelines tracked yet'}
                    description={ghConfigured
                        ? 'Trigger a workflow above or push to your repository to create runs.'
                        : 'Configure GitLab or GitHub in Settings to get started.'}
                />
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {filteredPipelines.map(pipeline => (
                        <PipelineStatusCard key={`${pipeline.provider}-${pipeline.id || pipeline.external_pipeline_id}`} pipeline={pipeline} />
                    ))}
                </div>
            )}

            {/* Auto-refresh indicator */}
            {(pipelines.some(p => ['pending', 'running', 'queued', 'waiting', 'in_progress'].includes(p.status)) || activeGate) && (
                <div style={{
                    marginTop: '1rem',
                    padding: '0.5rem 0.75rem',
                    fontSize: '0.75rem',
                    color: 'var(--text-secondary)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                }}>
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
        </PageLayout>
    );
}
