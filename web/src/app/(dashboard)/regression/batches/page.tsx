'use client';
import { useState, useEffect, useCallback } from 'react';
import { Clock, CheckCircle2, XCircle, PlayCircle, ChevronRight, Calendar, Tag, Percent, Layers, RefreshCw, AlertTriangle, Edit3, Check, X, TrendingUp } from 'lucide-react';
import Link from 'next/link';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface RegressionBatch {
    id: string;
    name: string | null;
    status: string;
    created_at: string;
    completed_at: string | null;
    browser: string;
    tags_used: string[];
    hybrid_mode: boolean;
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
}

interface PaginatedResponse {
    batches: RegressionBatch[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
}

interface TrendPoint {
    batch_id: string;
    name: string | null;
    created_at: string;
    success_rate: number;
    passed: number;
    failed: number;
    total: number;
}

interface FlakyTest {
    spec_name: string;
    pass_count: number;
    fail_count: number;
    flakiness_rate: number;
    recent_results: string[];
}

const PAGE_SIZE = 15;

export default function BatchListPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const [batches, setBatches] = useState<RegressionBatch[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [total, setTotal] = useState(0);
    const [statusFilter, setStatusFilter] = useState<string>('');

    // D3: inline rename state
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editName, setEditName] = useState('');

    // D4: trend data
    const [trendData, setTrendData] = useState<TrendPoint[]>([]);

    // D8: flaky tests
    const [flakyTests, setFlakyTests] = useState<FlakyTest[]>([]);
    const [showFlakyModal, setShowFlakyModal] = useState(false);

    const fetchBatches = useCallback((offset: number = 0, append: boolean = false) => {
        const isInitialLoad = offset === 0 && !append;
        if (isInitialLoad) {
            setLoading(true);
        } else {
            setLoadingMore(true);
        }

        let url = `${API_BASE}/regression/batches?limit=${PAGE_SIZE}&offset=${offset}`;
        if (statusFilter) {
            url += `&status=${statusFilter}`;
        }
        if (currentProject?.id) {
            url += `&project_id=${encodeURIComponent(currentProject.id)}`;
        }

        fetch(url)
            .then(res => res.json())
            .then((data: PaginatedResponse) => {
                if (append) {
                    setBatches(prev => [...prev, ...data.batches]);
                } else {
                    setBatches(data.batches);
                }
                setHasMore(data.has_more);
                setTotal(data.total);
                setLoading(false);
                setLoadingMore(false);
            })
            .catch(err => {
                console.error('Failed to fetch batches:', err);
                setLoading(false);
                setLoadingMore(false);
            });
    }, [statusFilter, currentProject?.id]);

    const loadMore = () => {
        if (!loadingMore && hasMore) {
            fetchBatches(batches.length, true);
        }
    };

    // D4: fetch trend
    const fetchTrend = useCallback(() => {
        let url = `${API_BASE}/regression/batches/trend?limit=20`;
        if (currentProject?.id) {
            url += `&project_id=${encodeURIComponent(currentProject.id)}`;
        }
        fetch(url)
            .then(res => res.json())
            .then((data: TrendPoint[]) => setTrendData(data))
            .catch(() => {});
    }, [currentProject?.id]);

    // D8: fetch flaky tests
    const fetchFlakyTests = useCallback(() => {
        let url = `${API_BASE}/regression/flaky-tests?window=10&min_batches=3`;
        if (currentProject?.id) {
            url += `&project_id=${encodeURIComponent(currentProject.id)}`;
        }
        fetch(url)
            .then(res => res.json())
            .then((data: { flaky_tests: FlakyTest[] }) => setFlakyTests(data.flaky_tests || []))
            .catch(() => {});
    }, [currentProject?.id]);

    useEffect(() => {
        if (projectLoading) return;
        fetchBatches();
        fetchTrend();
        fetchFlakyTests();

        const interval = setInterval(() => {
            const hasRunning = batches.some(b => b.status === 'running' || b.status === 'pending');
            if (hasRunning) {
                fetchBatches();
            }
        }, 5000);

        return () => clearInterval(interval);
    }, [statusFilter, currentProject?.id, projectLoading]);

    // D3: save name
    const saveName = async (batchId: string) => {
        try {
            const res = await fetch(`${API_BASE}/regression/batches/${batchId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: editName }),
            });
            if (res.ok) {
                setBatches(prev => prev.map(b => b.id === batchId ? { ...b, name: editName } : b));
            }
        } catch (e) {
            console.error('Failed to save name:', e);
        }
        setEditingId(null);
    };

    const getStatusConfig = (status: string) => {
        switch (status) {
            case 'completed':
                return { icon: <CheckCircle2 size={18} />, color: 'var(--success)', bg: 'var(--success-muted)', borderColor: 'rgba(52, 211, 153, 0.2)', label: 'Completed' };
            case 'running':
                return { icon: <PlayCircle size={18} />, color: 'var(--primary)', bg: 'var(--primary-glow)', borderColor: 'rgba(59, 130, 246, 0.25)', label: 'Running' };
            case 'pending':
            default:
                return { icon: <Clock size={18} />, color: 'var(--text-secondary)', bg: 'var(--surface)', borderColor: 'var(--border)', label: 'Pending' };
        }
    };

    const formatDate = (dateStr: string) => {
        const date = new Date(dateStr);
        return date.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
    };

    const formatShortDate = (dateStr: string) => {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
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

    if (loading || projectLoading) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="Batch Reports"
                subtitle={`${total} regression batch${total !== 1 ? 'es' : ''} recorded`}
                icon={<Layers size={20} />}
                actions={
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        {flakyTests.length > 0 && (
                            <button
                                className="btn"
                                onClick={() => setShowFlakyModal(true)}
                                style={{
                                    padding: '0.5rem 1rem',
                                    background: 'var(--warning-muted)',
                                    color: 'var(--warning)',
                                    border: '1px solid rgba(251, 191, 36, 0.3)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                }}
                            >
                                <AlertTriangle size={16} />
                                {flakyTests.length} Flaky
                            </button>
                        )}
                        <select
                            value={statusFilter}
                            onChange={(e) => setStatusFilter(e.target.value)}
                            className="input"
                            style={{ padding: '0.5rem 1rem', width: 'auto' }}
                        >
                            <option value="">All Status</option>
                            <option value="running">Running</option>
                            <option value="completed">Completed</option>
                            <option value="pending">Pending</option>
                        </select>
                        <button
                            className="btn btn-secondary"
                            onClick={() => fetchBatches()}
                            style={{ padding: '0.5rem 1rem' }}
                        >
                            <RefreshCw size={16} />
                            Refresh
                        </button>
                    </div>
                }
            />

            {/* D4: Trend Chart */}
            {trendData.length >= 2 && (
                <div className="card animate-in stagger-1" style={{ padding: '1.25rem', marginBottom: '1.5rem' }}>
                    <h3 style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <TrendingUp size={16} />
                        Success Rate Trend
                    </h3>
                    <div style={{ width: '100%', height: 200 }}>
                        <ResponsiveContainer>
                            <LineChart data={trendData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                <XAxis
                                    dataKey="created_at"
                                    tickFormatter={(v) => formatShortDate(v)}
                                    stroke="var(--text-secondary)"
                                    fontSize={12}
                                />
                                <YAxis
                                    domain={[0, 100]}
                                    stroke="var(--text-secondary)"
                                    fontSize={12}
                                    tickFormatter={(v) => `${v}%`}
                                />
                                <Tooltip
                                    contentStyle={{
                                        background: 'var(--surface)',
                                        border: '1px solid var(--border)',
                                        borderRadius: '8px',
                                        color: 'var(--text)',
                                    }}
                                    formatter={(value) => [`${value}%`, 'Success Rate']}
                                    labelFormatter={(label) => formatDate(label)}
                                />
                                <Line
                                    type="monotone"
                                    dataKey="success_rate"
                                    stroke="#10b981"
                                    strokeWidth={2}
                                    dot={{ r: 4, fill: '#10b981' }}
                                    activeDot={{ r: 6 }}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}

            {/* Batch List */}
            {batches.length === 0 ? (
                <EmptyState
                    icon={<Layers size={32} />}
                    title="No batches found"
                    description="Run regression tests to create batch reports."
                    action={
                        <Link href="/regression" className="btn btn-primary" style={{ marginTop: '1rem' }}>
                            Go to Regression Testing
                        </Link>
                    }
                />
            ) : (
                <div className="animate-in stagger-2" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {batches.map(batch => {
                        const status = getStatusConfig(batch.status);
                        const total_t = batch.total_tests || 1;
                        const passedPct = (batch.passed / total_t) * 100;
                        const failedPct = (batch.failed / total_t) * 100;
                        const stoppedPct = (batch.stopped / total_t) * 100;

                        return (
                            <div
                                key={batch.id}
                                className="list-item"
                                style={{ padding: '1.25rem', display: 'flex', alignItems: 'center' }}
                            >
                                <Link
                                    href={`/regression/batches/${batch.id}`}
                                    style={{ display: 'flex', alignItems: 'flex-start', gap: '1.25rem', flex: 1, textDecoration: 'none', color: 'inherit' }}
                                >
                                    <div className="status-icon-wrapper" style={{
                                        color: status.color,
                                        background: status.bg,
                                        border: `1px solid ${status.borderColor}`,
                                        width: 44,
                                        height: 44
                                    }}>
                                        {status.icon}
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        {/* D3: inline edit name */}
                                        {editingId === batch.id ? (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}
                                                onClick={(e) => e.preventDefault()}
                                            >
                                                <input
                                                    className="input"
                                                    value={editName}
                                                    onChange={(e) => setEditName(e.target.value)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') saveName(batch.id);
                                                        if (e.key === 'Escape') setEditingId(null);
                                                    }}
                                                    autoFocus
                                                    style={{ padding: '0.3rem 0.6rem', fontSize: '1rem', fontWeight: 600 }}
                                                    onClick={(e) => e.stopPropagation()}
                                                />
                                                <button
                                                    className="btn"
                                                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); saveName(batch.id); }}
                                                    style={{ padding: '0.3rem', background: 'var(--success)', color: 'white', border: 'none', borderRadius: '4px' }}
                                                >
                                                    <Check size={14} />
                                                </button>
                                                <button
                                                    className="btn"
                                                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); setEditingId(null); }}
                                                    style={{ padding: '0.3rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '4px' }}
                                                >
                                                    <X size={14} />
                                                </button>
                                            </div>
                                        ) : (
                                            <h3 style={{ fontWeight: 600, fontSize: '1.05rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                {batch.name || batch.id}
                                                <button
                                                    onClick={(e) => {
                                                        e.preventDefault();
                                                        e.stopPropagation();
                                                        setEditingId(batch.id);
                                                        setEditName(batch.name || batch.id);
                                                    }}
                                                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0.2rem', opacity: 0.5, display: 'flex' }}
                                                    title="Rename batch"
                                                >
                                                    <Edit3 size={14} color="var(--text-secondary)" />
                                                </button>
                                            </h3>
                                        )}
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.875rem', color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                <Calendar size={14} />
                                                {formatDate(batch.created_at)}
                                            </span>
                                            <span>|</span>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                <Clock size={14} />
                                                {formatDuration(batch.duration_seconds)}
                                            </span>
                                            {batch.tags_used.length > 0 && (
                                                <>
                                                    <span>|</span>
                                                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                        <Tag size={14} />
                                                        {batch.tags_used.slice(0, 2).join(', ')}
                                                        {batch.tags_used.length > 2 && ` +${batch.tags_used.length - 2}`}
                                                    </span>
                                                </>
                                            )}
                                        </div>

                                        {/* D9: Mini progress bar */}
                                        <div style={{
                                            marginTop: '0.75rem',
                                            height: '6px',
                                            background: 'var(--surface-hover)',
                                            borderRadius: '3px',
                                            display: 'flex',
                                            overflow: 'hidden',
                                        }}>
                                            {passedPct > 0 && (
                                                <div style={{ width: `${passedPct}%`, background: 'var(--success)', transition: 'width 0.3s' }} />
                                            )}
                                            {failedPct > 0 && (
                                                <div style={{ width: `${failedPct}%`, background: 'var(--danger)', transition: 'width 0.3s' }} />
                                            )}
                                            {stoppedPct > 0 && (
                                                <div style={{ width: `${stoppedPct}%`, background: 'var(--warning)', transition: 'width 0.3s' }} />
                                            )}
                                        </div>
                                    </div>
                                </Link>

                                <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.9rem' }}>
                                        <span style={{ color: 'var(--success)', fontWeight: 600 }}>
                                            {batch.actual_passed ?? batch.passed} passed
                                        </span>
                                        {(batch.actual_failed ?? batch.failed) > 0 && (
                                            <span style={{ color: 'var(--danger)', fontWeight: 600 }}>
                                                {batch.actual_failed ?? batch.failed} failed
                                            </span>
                                        )}
                                        {batch.running > 0 && (
                                            <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
                                                {batch.running} running
                                            </span>
                                        )}
                                        <span style={{ color: 'var(--text-secondary)' }}>
                                            / {batch.actual_total_tests ?? batch.total_tests}
                                        </span>
                                    </div>

                                    {batch.status === 'completed' && (
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem',
                                            padding: '0.35rem 0.75rem',
                                            borderRadius: '999px',
                                            background: `${getSuccessRateColor(batch.success_rate)}15`,
                                            color: getSuccessRateColor(batch.success_rate),
                                            fontWeight: 600,
                                            fontSize: '0.9rem'
                                        }}>
                                            <Percent size={14} />
                                            {batch.success_rate}%
                                        </div>
                                    )}

                                    <Link href={`/regression/batches/${batch.id}`}>
                                        <ChevronRight size={20} color="var(--text-secondary)" />
                                    </Link>
                                </div>
                            </div>
                        );
                    })}

                    {/* Load More Button */}
                    {hasMore && (
                        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '1rem' }}>
                            <button
                                onClick={loadMore}
                                disabled={loadingMore}
                                className="btn btn-secondary"
                                style={{ padding: '0.75rem 2rem', fontSize: '0.95rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                {loadingMore ? (
                                    <>
                                        <div className="loading-spinner" style={{ width: 16, height: 16 }} />
                                        Loading...
                                    </>
                                ) : (
                                    <>Load More ({total - batches.length} remaining)</>
                                )}
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* D8: Flaky Tests Modal */}
            {showFlakyModal && (
                <div
                    style={{
                        position: 'fixed', inset: 0, zIndex: 1000,
                        background: 'rgba(0,0,0,0.6)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                    onClick={() => setShowFlakyModal(false)}
                >
                    <div
                        className="card"
                        style={{ width: '600px', maxWidth: '90vw', maxHeight: '80vh', padding: '1.5rem', display: 'flex', flexDirection: 'column' }}
                        onClick={e => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h3 style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <AlertTriangle size={18} color="var(--warning)" />
                                Flaky Tests ({flakyTests.length})
                            </h3>
                            <button
                                onClick={() => setShowFlakyModal(false)}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0.25rem' }}
                            >
                                <X size={20} color="var(--text-secondary)" />
                            </button>
                        </div>
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                            Tests that alternate between pass and fail across recent batches.
                        </p>
                        <div style={{ flex: 1, overflowY: 'auto' }}>
                            {flakyTests.map(ft => (
                                <div
                                    key={ft.spec_name}
                                    style={{
                                        padding: '0.875rem',
                                        borderBottom: '1px solid var(--border)',
                                    }}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                        <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>{ft.spec_name}</span>
                                        <span style={{
                                            padding: '0.15rem 0.5rem',
                                            borderRadius: '9999px',
                                            background: 'var(--warning-muted)',
                                            color: 'var(--warning)',
                                            fontSize: '0.75rem',
                                            fontWeight: 600,
                                        }}>
                                            {ft.flakiness_rate}% flaky
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                                        {ft.recent_results.map((r, i) => (
                                            <div
                                                key={i}
                                                style={{
                                                    width: 12,
                                                    height: 12,
                                                    borderRadius: '50%',
                                                    background: r === 'pass' ? 'var(--success)' : 'var(--danger)',
                                                }}
                                                title={`${r === 'pass' ? 'Passed' : 'Failed'}`}
                                            />
                                        ))}
                                        <span style={{ marginLeft: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                            {ft.pass_count}P / {ft.fail_count}F
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </PageLayout>
    );
}
