'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { GitBranch, Loader2, RefreshCw, Play, ChevronDown, ChevronUp, GitPullRequest, ShieldCheck, XCircle, CheckCircle, AlertTriangle, ExternalLink } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PipelineStatusCard } from '@/components/PipelineStatusCard';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

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

interface QualityGate {
    id: string;
    pr_number: number;
    title?: string;
    owner: string;
    repo: string;
    head_ref?: string;
    base_ref?: string;
    risk_level: string;
    confidence: string;
    changed_files_count: number;
    selected_tests_count: number;
    total_candidate_tests: number;
    saved_tests_count?: number;
    fallback_reason?: string;
    batch_id?: string;
    created_at?: string;
    quality_gate: {
        state: string;
        description: string;
        batch_url?: string;
        analysis_url?: string;
        batch?: {
            id: string;
            status: string;
            total_tests: number;
            passed: number;
            failed: number;
            running: number;
            queued: number;
            success_rate: number;
        } | null;
    };
}

function getGateColor(state: string): string {
    switch (state) {
        case 'passed': return 'var(--success)';
        case 'failed':
        case 'blocked': return 'var(--danger)';
        case 'running':
        case 'analyzed': return 'var(--primary)';
        case 'needs-full-suite': return 'var(--warning)';
        default: return 'var(--text-secondary)';
    }
}

function getGateIcon(state: string) {
    switch (state) {
        case 'passed': return <CheckCircle size={15} />;
        case 'failed':
        case 'blocked': return <XCircle size={15} />;
        case 'running':
        case 'analyzed': return <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />;
        case 'needs-full-suite': return <AlertTriangle size={15} />;
        default: return <ShieldCheck size={15} />;
    }
}

function QualityGateCard({ gate }: { gate: QualityGate }) {
    const state = gate.quality_gate?.state || 'unknown';
    const color = getGateColor(state);
    const batch = gate.quality_gate?.batch;

    return (
        <div style={{
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            background: 'var(--background)',
            padding: '0.9rem',
            minWidth: 0,
        }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 750, fontSize: '0.9rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        PR #{gate.pr_number}: {gate.title || 'Untitled'}
                    </div>
                    <div style={{ marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.76rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {gate.owner}/{gate.repo} · {gate.head_ref || 'head'} → {gate.base_ref || 'base'}
                    </div>
                </div>
                <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    padding: '0.18rem 0.5rem',
                    borderRadius: '999px',
                    color,
                    background: `color-mix(in srgb, ${color} 12%, transparent)`,
                    fontSize: '0.72rem',
                    fontWeight: 750,
                    textTransform: 'capitalize',
                    flexShrink: 0,
                }}>
                    {getGateIcon(state)}
                    {state.replaceAll('-', ' ')}
                </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.45rem', marginTop: '0.85rem' }}>
                {[
                    ['Risk', gate.risk_level],
                    ['Selected', `${gate.selected_tests_count}/${gate.total_candidate_tests}`],
                    ['Skipped', String(gate.saved_tests_count ?? 0)],
                ].map(([label, value]) => (
                    <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.5rem' }}>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.68rem' }}>{label}</div>
                        <div style={{ marginTop: '0.2rem', fontWeight: 750, fontSize: '0.82rem', textTransform: label === 'Risk' ? 'capitalize' : undefined }}>{value}</div>
                    </div>
                ))}
            </div>

            {batch && (
                <div style={{ marginTop: '0.7rem', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                    Batch: {batch.passed}/{batch.total_tests} passed
                    {batch.failed > 0 ? <span style={{ color: 'var(--danger)' }}> · {batch.failed} failed</span> : null}
                    {(batch.running > 0 || batch.queued > 0) ? ` · ${batch.running + batch.queued} active` : ''}
                </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.75rem' }}>
                {gate.batch_id && (
                    <a href={`/regression/batches/${gate.batch_id}`} style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        color: 'var(--primary)',
                        textDecoration: 'none',
                        fontSize: '0.78rem',
                        fontWeight: 700,
                    }}>
                        View Batch <ExternalLink size={12} />
                    </a>
                )}
                <a href="/pr-advisor" style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    color: 'var(--text-secondary)',
                    textDecoration: 'none',
                    fontSize: '0.78rem',
                    fontWeight: 700,
                }}>
                    Open PR Advisor <ExternalLink size={12} />
                </a>
            </div>
        </div>
    );
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
    const [gatePrNumber, setGatePrNumber] = useState('');
    const [startingGate, setStartingGate] = useState(false);
    const [gateError, setGateError] = useState('');

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
            if (res.ok) setQualityGates(await res.json());
        } catch { /* ignore */ }
    }, [pid]);

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
                    run_recommended: true,
                    post_feedback: true,
                    create_commit_status: true,
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

    const filteredPipelines = filter === 'all'
        ? pipelines
        : pipelines.filter(p => p.provider === filter);

    const activeGate = qualityGates.some(g => ['running', 'analyzed'].includes(g.quality_gate?.state));

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
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem', padding: '1rem' }}>
                        {qualityGates.slice(0, 6).map(gate => (
                            <QualityGateCard key={gate.id} gate={gate} />
                        ))}
                    </div>
                )}
            </section>

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
