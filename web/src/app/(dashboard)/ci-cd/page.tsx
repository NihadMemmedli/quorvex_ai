'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { GitBranch, Loader2, RefreshCw, Play, ChevronDown, ChevronUp } from 'lucide-react';
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

export default function CiCdPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || (typeof window !== 'undefined' ? localStorage.getItem('selectedProjectId') : null) || 'default';
    const pid = encodeURIComponent(projectId);

    const [pipelines, setPipelines] = useState<Pipeline[]>([]);
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [filter, setFilter] = useState<ProviderFilter>('all');
    const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);

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
        setLoading(false);
    }, [pid, syncGithubRuns]);

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

        if (hasActive) {
            refreshTimer.current = setInterval(() => fetchPipelines(true), 15000);
        } else if (refreshTimer.current) {
            clearInterval(refreshTimer.current);
            refreshTimer.current = null;
        }

        return () => {
            if (refreshTimer.current) clearInterval(refreshTimer.current);
        };
    }, [pipelines, fetchPipelines]);

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

    const filteredPipelines = filter === 'all'
        ? pipelines
        : pipelines.filter(p => p.provider === filter);

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
            {pipelines.some(p => ['pending', 'running', 'queued', 'waiting', 'in_progress'].includes(p.status)) && (
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
                    Auto-refreshing every 15 seconds
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
