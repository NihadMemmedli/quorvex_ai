'use client';
import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
    Clock, CheckCircle2, XCircle, PlayCircle, ChevronRight,
    Calendar, Tag, Download, RefreshCw, ArrowLeft, Chrome,
    Globe, Compass, AlertTriangle, Hourglass, StopCircle,
    Upload, ExternalLink, Loader2, Layers, RotateCcw, BarChart3,
    GitCompare, History, ChevronDown, ChevronUp
} from 'lucide-react';
import Link from 'next/link';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface BatchRun {
    id: string;
    spec_name: string;
    test_name: string | null;
    status: string;
    steps_completed: number;
    total_steps: number;
    started_at: string | null;
    completed_at: string | null;
    error_message: string | null;
    duration_seconds: number | null;
    actual_test_count: number;
}

interface BatchDetail {
    id: string;
    name: string | null;
    status: string;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    browser: string;
    tags_used: string[];
    hybrid_mode: boolean;
    triggered_by: string | null;
    total_tests: number;
    passed: number;
    failed: number;
    stopped: number;
    running: number;
    queued: number;
    success_rate: number;
    duration_seconds: number | null;
    actual_total_tests: number | null;
    actual_passed: number | null;
    actual_failed: number | null;
    project_id: string | null;
    runs: BatchRun[];
}

interface SyncPreview {
    total_runs: number;
    mapped: number;
    unmapped: number;
    already_synced: boolean;
    batch_status: string;
    previous_sync?: { testrail_run_id: number; synced_at: string | null; results_count: number; testrail_run_url: string; };
}

interface SyncResult {
    testrail_run_id: number;
    testrail_run_url: string;
    synced: number;
    skipped: number;
    failed: number;
    errors: string[];
    already_synced: boolean;
}

interface TrConfig {
    configured: boolean;
    base_url?: string;
    project_id?: number;
    suite_id?: number;
}

interface ErrorCategory {
    name: string;
    count: number;
    percentage: number;
}

interface CompareResult {
    regressions: { spec_name: string; old_status: string; new_status: string }[];
    improvements: { spec_name: string; old_status: string; new_status: string }[];
    unchanged_passing: number;
    unchanged_failing: number;
    old_batch: { id: string; name: string | null };
    new_batch: { id: string; name: string | null };
}

interface SpecHistoryEntry {
    batch_id: string;
    batch_name: string | null;
    run_id: string;
    status: string;
    created_at: string;
    error_message: string | null;
}

interface RecentBatchOption {
    id: string;
    name: string | null;
    created_at: string;
}

export default function BatchDetailPage() {
    const params = useParams();
    const router = useRouter();
    const batchId = params.id as string;
    const { currentProject } = useProject();

    const [batch, setBatch] = useState<BatchDetail | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [showFailuresOnly, setShowFailuresOnly] = useState(false);
    const [sortBy, setSortBy] = useState<'status' | 'name' | 'duration'>('status');

    // TestRail sync state
    const [trConfig, setTrConfig] = useState<TrConfig | null>(null);
    const [syncPreview, setSyncPreview] = useState<SyncPreview | null>(null);
    const [syncModalOpen, setSyncModalOpen] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
    const [syncError, setSyncError] = useState<string | null>(null);

    // D2: Re-run failed
    const [rerunning, setRerunning] = useState(false);

    // D5: Error analysis
    const [errorCategories, setErrorCategories] = useState<ErrorCategory[]>([]);
    const [totalErrors, setTotalErrors] = useState(0);

    // D6: Compare
    const [recentBatches, setRecentBatches] = useState<RecentBatchOption[]>([]);
    const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
    const [comparing, setComparing] = useState(false);

    // D7: Spec history
    const [expandedSpec, setExpandedSpec] = useState<string | null>(null);
    const [specHistory, setSpecHistory] = useState<Record<string, SpecHistoryEntry[]>>({});

    const fetchBatch = useCallback(() => {
        fetch(`${API_BASE}/regression/batches/${batchId}`)
            .then(res => {
                if (!res.ok) throw new Error('Batch not found');
                return res.json();
            })
            .then((data: BatchDetail) => {
                setBatch(data);
                setLoading(false);
            })
            .catch(err => {
                setError(err.message);
                setLoading(false);
            });
    }, [batchId]);

    useEffect(() => {
        fetchBatch();
        const interval = setInterval(() => {
            if (batch?.status === 'running' || batch?.status === 'pending') {
                fetchBatch();
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [batchId, batch?.status]);

    // Load TestRail config
    useEffect(() => {
        const pid = currentProject?.id || batch?.project_id;
        if (!pid) return;
        fetch(`${API_BASE}/testrail/${pid}/config`)
            .then(res => res.ok ? res.json() : null)
            .then(data => { if (data) setTrConfig(data); })
            .catch(() => {});
    }, [currentProject?.id, batch?.project_id]);

    // D5: Load error analysis when batch is complete and has failures
    useEffect(() => {
        if (batch?.status === 'completed' && batch.failed > 0) {
            fetch(`${API_BASE}/regression/batches/${batchId}/error-summary`)
                .then(res => res.json())
                .then(data => {
                    setErrorCategories(data.categories || []);
                    setTotalErrors(data.total_errors || 0);
                })
                .catch(() => {});
        }
    }, [batch?.status, batch?.failed, batchId]);

    // D6: Load recent batches for compare
    useEffect(() => {
        if (!batch) return;
        const pid = currentProject?.id || batch.project_id;
        let url = `${API_BASE}/regression/batches?limit=10&status=completed`;
        if (pid) url += `&project_id=${encodeURIComponent(pid)}`;
        fetch(url)
            .then(res => res.json())
            .then(data => {
                setRecentBatches(
                    (data.batches || [])
                        .filter((b: RecentBatchOption) => b.id !== batchId)
                        .map((b: RecentBatchOption) => ({ id: b.id, name: b.name, created_at: b.created_at }))
                );
            })
            .catch(() => {});
    }, [batch?.id, currentProject?.id]);

    // D2: Re-run failed handler
    const handleRerunFailed = async () => {
        setRerunning(true);
        try {
            const res = await fetch(`${API_BASE}/regression/batches/${batchId}/rerun-failed`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Failed' }));
                alert(err.detail || 'Failed to re-run');
                return;
            }
            const data = await res.json();
            if (data.batch_id) {
                router.push(`/regression/batches/${data.batch_id}`);
            }
        } catch (e: any) {
            alert(e.message || 'Failed');
        } finally {
            setRerunning(false);
        }
    };

    // D6: Compare handler
    const handleCompare = async (otherId: string) => {
        setComparing(true);
        setCompareResult(null);
        try {
            const res = await fetch(`${API_BASE}/regression/batches/compare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_ids: [otherId, batchId] }),
            });
            if (res.ok) {
                setCompareResult(await res.json());
            }
        } catch (e) {
            console.error('Compare failed:', e);
        }
        setComparing(false);
    };

    // D7: Load spec history
    const loadSpecHistory = async (specName: string) => {
        if (expandedSpec === specName) {
            setExpandedSpec(null);
            return;
        }
        setExpandedSpec(specName);
        if (specHistory[specName]) return;

        const pid = currentProject?.id || batch?.project_id;
        let url = `${API_BASE}/regression/spec-history?spec_name=${encodeURIComponent(specName)}&limit=10`;
        if (pid) url += `&project_id=${encodeURIComponent(pid)}`;
        try {
            const res = await fetch(url);
            const data = await res.json();
            setSpecHistory(prev => ({ ...prev, [specName]: data }));
        } catch (e) {
            console.error('Failed to load spec history:', e);
        }
    };

    const handleOpenSyncModal = async () => {
        const pid = currentProject?.id || batch?.project_id;
        if (!pid) return;
        setSyncResult(null);
        setSyncError(null);
        setSyncPreview(null);
        setSyncModalOpen(true);
        try {
            const res = await fetch(`${API_BASE}/testrail/${pid}/sync-preview/${batchId}`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Failed to load preview' }));
                setSyncError(err.detail || 'Failed to load preview');
                return;
            }
            setSyncPreview(await res.json());
        } catch (e: any) {
            setSyncError(e.message || 'Failed to load preview');
        }
    };

    const handleSyncToTestrail = async () => {
        const pid = currentProject?.id || batch?.project_id;
        if (!pid || !trConfig?.project_id || !trConfig?.suite_id) return;
        setSyncing(true);
        setSyncError(null);
        try {
            const res = await fetch(`${API_BASE}/testrail/${pid}/sync-results`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_id: batchId, testrail_project_id: trConfig.project_id, testrail_suite_id: trConfig.suite_id }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Sync failed' }));
                setSyncError(err.detail || 'Sync failed');
                return;
            }
            setSyncResult(await res.json());
        } catch (e: any) {
            setSyncError(e.message || 'Sync failed');
        } finally {
            setSyncing(false);
        }
    };

    const handleExport = async (format: 'json' | 'csv' | 'html') => {
        const url = `${API_BASE}/regression/batches/${batchId}/export?format=${format}`;
        if (format === 'csv' || format === 'html') {
            window.open(url, '_blank');
        } else {
            const response = await fetch(url);
            const data = await response.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const downloadUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = `batch_${batchId}.json`;
            a.click();
            URL.revokeObjectURL(downloadUrl);
        }
    };

    const getStatusConfig = (status: string) => {
        switch (status) {
            case 'completed': case 'passed':
                return { icon: <CheckCircle2 size={16} />, color: 'var(--success)', bg: 'var(--success-muted)', borderColor: 'rgba(52, 211, 153, 0.2)', label: 'Passed' };
            case 'failed':
                return { icon: <XCircle size={16} />, color: 'var(--danger)', bg: 'var(--danger-muted)', borderColor: 'rgba(248, 113, 113, 0.2)', label: 'Failed' };
            case 'stopped':
                return { icon: <StopCircle size={16} />, color: 'var(--warning)', bg: 'var(--warning-muted)', borderColor: 'rgba(251, 191, 36, 0.2)', label: 'Stopped' };
            case 'running': case 'in_progress':
                return { icon: <PlayCircle size={16} />, color: 'var(--primary)', bg: 'var(--primary-glow)', borderColor: 'rgba(59, 130, 246, 0.25)', label: 'Running' };
            case 'queued':
                return { icon: <Hourglass size={16} />, color: 'var(--warning)', bg: 'var(--warning-muted)', borderColor: 'rgba(251, 191, 36, 0.2)', label: 'Queued' };
            default:
                return { icon: <Clock size={16} />, color: 'var(--text-secondary)', bg: 'var(--surface)', borderColor: 'var(--border)', label: status };
        }
    };

    const getBrowserIcon = (browser?: string) => {
        switch (browser) {
            case 'firefox': return <Globe size={16} color="#FF7139" />;
            case 'webkit': return <Compass size={16} color="#007AFF" />;
            default: return <Chrome size={16} color="#4285F4" />;
        }
    };

    const formatDate = (dateStr: string | null) => {
        if (!dateStr) return '-';
        return new Date(dateStr).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
    };

    const formatDuration = (seconds: number | null) => {
        if (!seconds) return '-';
        if (seconds < 60) return `${seconds}s`;
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        if (mins < 60) return `${mins}m ${secs}s`;
        const hrs = Math.floor(mins / 60);
        return `${hrs}h ${mins % 60}m`;
    };

    const getSuccessRateColor = (rate: number) => {
        if (rate >= 90) return 'var(--success)';
        if (rate >= 70) return 'var(--warning)';
        return 'var(--danger)';
    };

    const trConfigured = trConfig?.configured && trConfig?.project_id && trConfig?.suite_id;
    const showSyncButton = batch?.status === 'completed' && trConfigured;

    if (loading) return <PageLayout tier="standard"><ListPageSkeleton rows={5} /></PageLayout>;

    if (error || !batch) {
        return (
            <PageLayout tier="standard">
                <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
                    <AlertTriangle size={48} color="var(--danger)" style={{ marginBottom: '1rem' }} />
                    <h2>Batch Not Found</h2>
                    <p style={{ color: 'var(--text-secondary)' }}>{error}</p>
                    <Link href="/regression/batches" className="btn btn-primary" style={{ marginTop: '1.5rem' }}>Back to Batches</Link>
                </div>
            </PageLayout>
        );
    }

    const filteredRuns = showFailuresOnly
        ? batch.runs.filter(r => r.status === 'failed' || r.status === 'stopped')
        : batch.runs;

    const sortedRuns = [...filteredRuns].sort((a, b) => {
        if (sortBy === 'status') {
            const o: Record<string, number> = { failed: 0, stopped: 1, running: 2, queued: 3, passed: 4, completed: 4 };
            return (o[a.status] ?? 5) - (o[b.status] ?? 5);
        }
        if (sortBy === 'name') return (a.test_name || a.spec_name).localeCompare(b.test_name || b.spec_name);
        if (sortBy === 'duration') return (b.duration_seconds || 0) - (a.duration_seconds || 0);
        return 0;
    });

    const errorBarData = errorCategories.map(c => ({
        name: c.name,
        count: c.count,
        fill: c.name === 'Timeout' ? '#f59e0b' : c.name === 'Selector' ? '#8b5cf6' : c.name === 'Network' ? '#3b82f6' : c.name === 'Assertion' ? '#ef4444' : '#6b7280',
    }));

    return (
        <PageLayout tier="standard">
            <PageHeader
                title={batch.name || batch.id}
                subtitle={`${formatDate(batch.created_at)} | ${batch.browser}${batch.duration_seconds ? ` | ${formatDuration(batch.duration_seconds)}` : ''}`}
                icon={<Layers size={20} />}
                breadcrumb={
                    <Link href="/regression/batches" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem', textDecoration: 'none' }}>
                        <ArrowLeft size={16} /> Back to Batches
                    </Link>
                }
                actions={
                    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                        {/* D2: Re-run Failed */}
                        {batch.status === 'completed' && batch.failed > 0 && (
                            <button
                                className="btn"
                                onClick={handleRerunFailed}
                                disabled={rerunning}
                                style={{
                                    padding: '0.5rem 1rem',
                                    background: 'var(--danger-muted)',
                                    color: 'var(--danger)',
                                    border: '1px solid rgba(248, 113, 113, 0.3)',
                                    display: 'flex', alignItems: 'center', gap: '0.4rem',
                                    opacity: rerunning ? 0.6 : 1,
                                }}
                            >
                                {rerunning ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <RotateCcw size={16} />}
                                Re-run Failed ({batch.failed})
                            </button>
                        )}
                        {showSyncButton && (
                            <button className="btn" onClick={handleOpenSyncModal} style={{ padding: '0.5rem 1rem', background: 'var(--primary-glow)', color: 'var(--primary)', border: '1px solid rgba(59, 130, 246, 0.3)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <Upload size={16} /> Sync to TestRail
                            </button>
                        )}
                        <button className="btn btn-secondary" onClick={fetchBatch} style={{ padding: '0.5rem 1rem' }}><RefreshCw size={16} /> Refresh</button>
                        <button className="btn btn-secondary" onClick={() => handleExport('html')} style={{ padding: '0.5rem 1rem' }}><Download size={16} /> HTML</button>
                        <button className="btn btn-secondary" onClick={() => handleExport('csv')} style={{ padding: '0.5rem 1rem' }}><Download size={16} /> CSV</button>
                        <button className="btn btn-secondary" onClick={() => handleExport('json')} style={{ padding: '0.5rem 1rem' }}><Download size={16} /> JSON</button>
                    </div>
                }
            />

            {/* Batch metadata */}
            <div className="animate-in stagger-1" style={{ marginBottom: '2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem', flexWrap: 'wrap' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>{getBrowserIcon(batch.browser)}<span style={{ textTransform: 'capitalize' }}>{batch.browser}</span></span>
                    {batch.hybrid_mode && <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', fontSize: '0.75rem', fontWeight: 500 }}>Extended Healing</span>}
                </div>
                {batch.tags_used.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem' }}>
                        <Tag size={14} color="var(--text-secondary)" />
                        {batch.tags_used.map(tag => <span key={tag} style={{ fontSize: '0.8rem', padding: '0.2rem 0.6rem', borderRadius: '9999px', background: 'var(--primary-glow)', color: 'var(--primary)', fontWeight: 500 }}>{tag}</span>)}
                    </div>
                )}
            </div>

            {/* Summary Cards */}
            <div className="animate-in stagger-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '2rem' }}>
                <div className="card" style={{ padding: '1.25rem', textAlign: 'center' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.25rem' }}>{batch.actual_total_tests ?? batch.total_tests}</div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Total Tests</div>
                </div>
                <div className="card" style={{ padding: '1.25rem', textAlign: 'center', borderLeft: '3px solid var(--success)' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.25rem', color: 'var(--success)' }}>{batch.actual_passed ?? batch.passed}</div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Passed</div>
                </div>
                <div className="card" style={{ padding: '1.25rem', textAlign: 'center', borderLeft: '3px solid var(--danger)' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.25rem', color: 'var(--danger)' }}>{batch.actual_failed ?? batch.failed}</div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Failed</div>
                </div>
                <div className="card" style={{ padding: '1.25rem', textAlign: 'center', borderLeft: `3px solid ${getSuccessRateColor(batch.success_rate)}` }}>
                    <div style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.25rem', color: getSuccessRateColor(batch.success_rate) }}>{batch.success_rate}%</div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Success Rate</div>
                </div>
            </div>

            {/* Progress Bar (when running) */}
            {(batch.status === 'running' || batch.status === 'pending') && (
                <div className="card" style={{ padding: '1.25rem', marginBottom: '2rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                        <span style={{ fontWeight: 600 }}>Progress</span>
                        <span style={{ color: 'var(--text-secondary)' }}>{batch.passed + batch.failed + batch.stopped} / {batch.total_tests} completed{batch.running > 0 && ` (${batch.running} running)`}</span>
                    </div>
                    <div style={{ height: '12px', background: 'var(--surface-hover)', borderRadius: '6px', display: 'flex', overflow: 'hidden' }}>
                        <div style={{ width: `${(batch.passed / batch.total_tests) * 100}%`, background: 'var(--success)', transition: 'width 0.3s' }} />
                        <div style={{ width: `${(batch.failed / batch.total_tests) * 100}%`, background: 'var(--danger)', transition: 'width 0.3s' }} />
                        <div style={{ width: `${(batch.stopped / batch.total_tests) * 100}%`, background: 'var(--warning)', transition: 'width 0.3s' }} />
                        <div style={{ width: `${(batch.running / batch.total_tests) * 100}%`, background: 'var(--primary)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                    </div>
                </div>
            )}

            {/* D5: Error Analysis + D6: Compare side-by-side */}
            {batch.status === 'completed' && (errorCategories.length > 0 || recentBatches.length > 0) && (
                <div style={{ display: 'grid', gridTemplateColumns: errorCategories.length > 0 && recentBatches.length > 0 ? '1fr 1fr' : '1fr', gap: '1rem', marginBottom: '2rem' }}>
                    {/* D5: Error Analysis */}
                    {errorCategories.length > 0 && (
                        <div className="card animate-in" style={{ padding: '1.25rem' }}>
                            <h3 style={{ fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.95rem' }}>
                                <BarChart3 size={16} /> Error Analysis ({totalErrors} errors)
                            </h3>
                            <div style={{ width: '100%', height: 180 }}>
                                <ResponsiveContainer>
                                    <BarChart data={errorBarData} layout="vertical">
                                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                        <XAxis type="number" stroke="var(--text-secondary)" fontSize={12} />
                                        <YAxis type="category" dataKey="name" stroke="var(--text-secondary)" fontSize={12} width={80} />
                                        <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text)' }} />
                                        <Bar dataKey="count" radius={[0, 4, 4, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    )}

                    {/* D6: Compare */}
                    {recentBatches.length > 0 && (
                        <div className="card animate-in" style={{ padding: '1.25rem' }}>
                            <h3 style={{ fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.95rem' }}>
                                <GitCompare size={16} /> Compare with...
                            </h3>
                            <select
                                className="input"
                                onChange={(e) => { if (e.target.value) handleCompare(e.target.value); }}
                                defaultValue=""
                                style={{ marginBottom: '1rem', width: '100%' }}
                            >
                                <option value="">Select a batch to compare</option>
                                {recentBatches.map(b => (
                                    <option key={b.id} value={b.id}>{b.name || b.id} - {new Date(b.created_at).toLocaleDateString()}</option>
                                ))}
                            </select>
                            {comparing && <div style={{ textAlign: 'center', padding: '1rem' }}><Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} /></div>}
                            {compareResult && (
                                <div style={{ fontSize: '0.9rem' }}>
                                    {compareResult.regressions.length > 0 && (
                                        <div style={{ marginBottom: '0.75rem' }}>
                                            <div style={{ fontWeight: 600, color: 'var(--danger)', marginBottom: '0.35rem' }}>Regressions ({compareResult.regressions.length})</div>
                                            {compareResult.regressions.map(r => (
                                                <div key={r.spec_name} style={{ padding: '0.35rem 0.5rem', borderRadius: '4px', background: 'rgba(239,68,68,0.08)', marginBottom: '0.25rem', fontSize: '0.85rem' }}>
                                                    {r.spec_name} <span style={{ color: 'var(--text-secondary)' }}>{r.old_status} &rarr; {r.new_status}</span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    {compareResult.improvements.length > 0 && (
                                        <div style={{ marginBottom: '0.75rem' }}>
                                            <div style={{ fontWeight: 600, color: 'var(--success)', marginBottom: '0.35rem' }}>Improvements ({compareResult.improvements.length})</div>
                                            {compareResult.improvements.map(r => (
                                                <div key={r.spec_name} style={{ padding: '0.35rem 0.5rem', borderRadius: '4px', background: 'rgba(16,185,129,0.08)', marginBottom: '0.25rem', fontSize: '0.85rem' }}>
                                                    {r.spec_name} <span style={{ color: 'var(--text-secondary)' }}>{r.old_status} &rarr; {r.new_status}</span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                        {compareResult.unchanged_passing} unchanged passing, {compareResult.unchanged_failing} unchanged failing
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Test Results Table */}
            <div className="card animate-in stagger-3" style={{ padding: 0, overflow: 'hidden', marginBottom: '2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)' }}>
                    <h3 style={{ fontWeight: 600 }}>Test Results</h3>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                            <input type="checkbox" checked={showFailuresOnly} onChange={(e) => setShowFailuresOnly(e.target.checked)} style={{ cursor: 'pointer' }} />
                            Show failures only
                        </label>
                        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="input" style={{ padding: '0.4rem 0.8rem', width: 'auto', fontSize: '0.9rem' }}>
                            <option value="status">Sort by Status</option>
                            <option value="name">Sort by Name</option>
                            <option value="duration">Sort by Duration</option>
                        </select>
                    </div>
                </div>

                {/* Column Headers */}
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 80px 100px 100px 1fr 70px', alignItems: 'center', padding: '0.75rem 1.25rem', borderBottom: '1px solid var(--border)', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    <div>Test Name</div>
                    <div style={{ textAlign: 'center' }}>Status</div>
                    <div style={{ textAlign: 'center' }}>Steps</div>
                    <div style={{ textAlign: 'center' }}>Duration</div>
                    <div>Error</div>
                    <div style={{ textAlign: 'center' }}>History</div>
                </div>

                {sortedRuns.length === 0 ? (
                    <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>No tests to display</div>
                ) : (
                    sortedRuns.map(run => {
                        const status = getStatusConfig(run.status);
                        const isExpanded = expandedSpec === run.spec_name;
                        const history = specHistory[run.spec_name];
                        return (
                            <div key={run.id}>
                                <div style={{ display: 'grid', gridTemplateColumns: '2fr 80px 100px 100px 1fr 70px', alignItems: 'center', padding: '0.875rem 1.25rem', borderBottom: '1px solid var(--border)', fontSize: '0.9rem' }}>
                                    <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <Link href={`/runs/${run.id}`} target="_blank" style={{ color: 'var(--text)', textDecoration: 'none' }}>
                                            {run.test_name || run.spec_name}
                                        </Link>
                                        {run.actual_test_count > 1 && <span style={{ fontSize: '0.75rem', padding: '0.1rem 0.4rem', borderRadius: '4px', background: 'var(--primary-glow)', color: 'var(--primary)' }}>{run.actual_test_count} tests</span>}
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'center' }}>
                                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.25rem 0.6rem', borderRadius: '9999px', fontSize: '0.8rem', fontWeight: 600, background: status.bg, color: status.color, border: `1px solid ${status.borderColor}` }}>
                                            {status.icon} {status.label}
                                        </span>
                                    </div>
                                    <div style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>{run.steps_completed}/{run.total_steps}</div>
                                    <div style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>{formatDuration(run.duration_seconds)}</div>
                                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: run.error_message ? 'var(--danger)' : 'var(--text-secondary)', fontSize: '0.85rem' }}>{run.error_message || '-'}</div>
                                    {/* D7: History toggle */}
                                    <div style={{ textAlign: 'center' }}>
                                        <button
                                            onClick={() => loadSpecHistory(run.spec_name)}
                                            style={{ background: 'none', border: '1px solid var(--border)', borderRadius: '4px', padding: '0.2rem 0.4rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.2rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}
                                        >
                                            <History size={12} />
                                            {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                        </button>
                                    </div>
                                </div>
                                {/* D7: History panel */}
                                {isExpanded && (
                                    <div style={{ padding: '0.75rem 1.25rem 0.75rem 3rem', borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
                                        {!history ? (
                                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading...</div>
                                        ) : history.length === 0 ? (
                                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No history found</div>
                                        ) : (
                                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                                {history.map((h, i) => (
                                                    <div key={i} title={`${h.batch_name || h.batch_id} - ${h.status}${h.error_message ? `: ${h.error_message}` : ''}`}>
                                                        <div style={{
                                                            width: 16, height: 16, borderRadius: '50%',
                                                            background: h.status === 'passed' || h.status === 'completed' ? 'var(--success)' : h.status === 'failed' ? 'var(--danger)' : 'var(--warning)',
                                                            border: h.run_id === run.id ? '2px solid var(--text)' : 'none',
                                                        }} />
                                                    </div>
                                                ))}
                                                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginLeft: '0.5rem' }}>
                                                    Last {history.length} runs
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })
                )}
            </div>

            {/* Failure Details */}
            {batch.failed > 0 && (
                <div className="card" style={{ padding: '1.25rem' }}>
                    <h3 style={{ fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <AlertTriangle size={18} color="var(--danger)" /> Failure Details ({batch.failed} failed)
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {batch.runs.filter(r => r.status === 'failed' && r.error_message).map(run => (
                            <div key={run.id} style={{ padding: '1rem', borderRadius: 'var(--radius)', background: 'var(--danger-muted)', border: '1px solid rgba(248, 113, 113, 0.2)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                                    <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{run.test_name || run.spec_name}</span>
                                    <Link href={`/runs/${run.id}`} target="_blank" style={{ fontSize: '0.85rem', color: 'var(--primary)', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>View Details <ChevronRight size={14} /></Link>
                                </div>
                                <pre style={{ margin: 0, padding: '0.75rem', borderRadius: '4px', background: 'rgba(0, 0, 0, 0.25)', fontSize: '0.8rem', color: 'var(--danger)', overflow: 'auto', maxHeight: '150px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{run.error_message}</pre>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* TestRail Sync Modal */}
            {syncModalOpen && (
                <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setSyncModalOpen(false)}>
                    <div className="card" style={{ width: '500px', maxWidth: '90vw', padding: '1.5rem' }} onClick={e => e.stopPropagation()}>
                        <h3 style={{ fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}><Upload size={18} /> Sync to TestRail</h3>
                        {!syncPreview && !syncResult && !syncError && <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}><Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} /></div>}
                        {syncError && <div style={{ padding: '0.75rem 1rem', borderRadius: '6px', background: 'var(--danger-muted)', border: '1px solid rgba(248, 113, 113, 0.2)', color: 'var(--danger)', fontSize: '0.9rem', marginBottom: '1rem' }}>{syncError}</div>}
                        {syncPreview && !syncResult && (
                            <div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}><span style={{ color: 'var(--text-secondary)' }}>Total completed runs</span><span style={{ fontWeight: 600 }}>{syncPreview.total_runs}</span></div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}><span style={{ color: 'var(--text-secondary)' }}>Mapped to TestRail cases</span><span style={{ fontWeight: 600, color: 'var(--success)' }}>{syncPreview.mapped}</span></div>
                                    {syncPreview.unmapped > 0 && <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}><span style={{ color: 'var(--text-secondary)' }}>No mapping (will skip)</span><span style={{ fontWeight: 600, color: 'var(--warning)' }}>{syncPreview.unmapped}</span></div>}
                                </div>
                                {syncPreview.already_synced && syncPreview.previous_sync && (
                                    <div style={{ padding: '0.75rem 1rem', borderRadius: '6px', background: 'var(--primary-glow)', border: '1px solid rgba(59, 130, 246, 0.25)', marginBottom: '1rem', fontSize: '0.9rem' }}>
                                        <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>Already synced</div>
                                        <div style={{ color: 'var(--text-secondary)' }}>{syncPreview.previous_sync.results_count} results synced on {formatDate(syncPreview.previous_sync.synced_at)}</div>
                                        <a href={syncPreview.previous_sync.testrail_run_url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', color: 'var(--primary)', fontSize: '0.85rem', marginTop: '0.5rem' }}>View in TestRail <ExternalLink size={12} /></a>
                                    </div>
                                )}
                                {syncPreview.mapped === 0 && <div style={{ padding: '0.75rem 1rem', borderRadius: '6px', background: 'var(--warning-muted)', border: '1px solid rgba(251, 191, 36, 0.2)', marginBottom: '1rem', fontSize: '0.9rem', color: 'var(--warning)' }}>No specs are mapped to TestRail cases. Push specs to TestRail first.</div>}
                                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1rem' }}>
                                    <button className="btn btn-secondary" onClick={() => setSyncModalOpen(false)} style={{ padding: '0.5rem 1rem' }}>Cancel</button>
                                    <button className="btn btn-primary" onClick={handleSyncToTestrail} disabled={syncing || syncPreview.already_synced || syncPreview.mapped === 0} style={{ padding: '0.5rem 1rem', display: 'flex', alignItems: 'center', gap: '0.4rem', opacity: (syncing || syncPreview.already_synced || syncPreview.mapped === 0) ? 0.5 : 1 }}>
                                        {syncing ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <Upload size={16} />}
                                        {syncing ? 'Syncing...' : 'Sync Results'}
                                    </button>
                                </div>
                            </div>
                        )}
                        {syncResult && (
                            <div>
                                {syncResult.already_synced ? (
                                    <div style={{ padding: '0.75rem 1rem', borderRadius: '6px', background: 'var(--primary-glow)', border: '1px solid rgba(59, 130, 246, 0.25)', marginBottom: '1rem', fontSize: '0.9rem' }}>This batch was already synced to TestRail.</div>
                                ) : (
                                    <div style={{ padding: '0.75rem 1rem', borderRadius: '6px', background: 'var(--success-muted)', border: '1px solid rgba(52, 211, 153, 0.2)', marginBottom: '1rem' }}>
                                        <div style={{ fontWeight: 600, marginBottom: '0.5rem', color: 'var(--success)' }}>Sync complete</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.9rem' }}>
                                            <span>{syncResult.synced} results synced</span>
                                            {syncResult.skipped > 0 && <span style={{ color: 'var(--warning)' }}>{syncResult.skipped} skipped</span>}
                                            {syncResult.failed > 0 && <span style={{ color: 'var(--danger)' }}>{syncResult.failed} failed</span>}
                                        </div>
                                    </div>
                                )}
                                {syncResult.testrail_run_url && <a href={syncResult.testrail_run_url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', color: 'var(--primary)', fontSize: '0.9rem', marginBottom: '1rem' }}>View in TestRail <ExternalLink size={14} /></a>}
                                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
                                    <button className="btn btn-secondary" onClick={() => setSyncModalOpen(false)} style={{ padding: '0.5rem 1rem' }}>Close</button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </PageLayout>
    );
}
