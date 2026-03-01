'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/api';
import {
    cardStyleCompact, inputStyle, btnPrimary, btnSecondary, btnSmall,
    labelStyle, thStyle, tdStyle
} from '@/lib/styles';
import { toast } from 'sonner';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusBadge } from '@/components/shared';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
    Search, Check, X, Loader2,
    Trophy, Scale, ArrowLeft, Trash2,
    CheckCircle, XCircle, Crown
} from 'lucide-react';
import { usePolling } from '@/hooks/usePolling';
import type { Provider, Spec, Comparison } from './types';

interface CompareTabProps {
    projectId: string;
}

export default function CompareTab({ projectId }: CompareTabProps) {
    const [providers, setProviders] = useState<Provider[]>([]);
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [comparisons, setComparisons] = useState<Comparison[]>([]);
    const [selectedSpec, setSelectedSpec] = useState('');
    const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
    const [comparisonName, setComparisonName] = useState('');
    const [running, setRunning] = useState(false);
    const [selectedComparison, setSelectedComparison] = useState<any>(null);
    const [matrix, setMatrix] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);

    // Job polling state for comparison
    const [compareJobId, setCompareJobId] = useState<string | null>(null);
    const [compareProgress, setCompareProgress] = useState<any>(null);

    // New state for filters and confirm dialog
    const [historySearch, setHistorySearch] = useState('');
    const [historyStatusFilter, setHistoryStatusFilter] = useState('');
    const [confirmDialog, setConfirmDialog] = useState<{ open: boolean; comparisonId: string }>({ open: false, comparisonId: '' });
    const [deleteLoading, setDeleteLoading] = useState(false);

    const fetchComparisons = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/comparisons?project_id=${projectId}`);
            if (res.ok) setComparisons(await res.json());
        } catch { toast.error('Failed to load comparisons'); }
    }, [projectId]);

    useEffect(() => {
        fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`).then(r => r.json()).then(setProviders).catch(() => {});
        fetch(`${API_BASE}/llm-testing/specs?project_id=${projectId}`).then(r => r.json()).then(setSpecs).catch(() => {});
        fetchComparisons();
    }, [projectId, fetchComparisons]);

    // Poll for comparison job completion
    const comparePollFn = useCallback(async () => {
        if (!compareJobId) return;
        const jr = await fetch(`${API_BASE}/llm-testing/jobs/${compareJobId}`);
        if (jr.ok) {
            const job = await jr.json();
            setCompareProgress(job);
            if (job.status === 'completed' || job.status === 'failed') {
                setCompareJobId(null);
                setRunning(false);
                setCompareProgress(null);
                fetchComparisons();
                if (job.status === 'completed') toast.success('Comparison completed');
                if (job.status === 'failed') toast.error(job.error || 'Comparison failed');
            }
        }
    }, [compareJobId, fetchComparisons]);

    const { stop: stopComparePoll } = usePolling(comparePollFn, {
        interval: 2000,
        enabled: !!compareJobId,
    });

    // Stop polling when compareJobId is cleared
    useEffect(() => {
        if (!compareJobId) stopComparePoll();
    }, [compareJobId, stopComparePoll]);

    const toggleProvider = useCallback((id: string) => {
        setSelectedProviders(prev => prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]);
    }, []);

    const startComparison = useCallback(async () => {
        if (!selectedSpec || selectedProviders.length < 2) return;
        setRunning(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/compare`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_name: selectedSpec, provider_ids: selectedProviders,
                    name: comparisonName || undefined, project_id: projectId,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                setCompareJobId(data.job_id);
                toast.success('Comparison started');
            } else {
                toast.error('Failed to start comparison');
                setRunning(false);
            }
        } catch { toast.error('Failed to start comparison'); setRunning(false); }
    }, [selectedSpec, selectedProviders, comparisonName, projectId]);

    const viewComparison = useCallback(async (id: string) => {
        // Toggle behavior: clicking same comparison deselects it
        if (selectedComparison?.id === id) {
            setSelectedComparison(null);
            setMatrix(null);
            return;
        }
        setDetailLoading(true);
        setSelectedComparison(null);
        setMatrix(null);
        try {
            const [detailRes, matrixRes] = await Promise.all([
                fetch(`${API_BASE}/llm-testing/comparisons/${id}`),
                fetch(`${API_BASE}/llm-testing/comparisons/${id}/matrix`),
            ]);
            if (detailRes.ok) setSelectedComparison(await detailRes.json());
            if (matrixRes.ok) setMatrix(await matrixRes.json());
        } catch {
            toast.error('Failed to load comparison details');
        }
        setDetailLoading(false);
    }, [selectedComparison]);

    const deleteComparison = useCallback(async (id: string) => {
        setDeleteLoading(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/comparisons/${id}`, { method: 'DELETE' });
            if (res.ok) {
                toast.success('Comparison deleted');
                setComparisons(prev => prev.filter(c => c.id !== id));
                if (selectedComparison?.id === id) {
                    setSelectedComparison(null);
                    setMatrix(null);
                }
            } else {
                toast.error('Failed to delete comparison');
            }
        } catch {
            toast.error('Failed to delete comparison');
        }
        setDeleteLoading(false);
    }, [selectedComparison]);

    const providerName = useCallback((id: string) => providers.find(p => p.id === id)?.name || id, [providers]);

    const comparePct = compareProgress && compareProgress.progress_total > 0
        ? Math.round((compareProgress.progress_current / compareProgress.progress_total) * 100) : 0;

    // Filtered comparisons
    const filteredComparisons = useMemo(() => {
        return comparisons.filter(c => {
            if (historySearch) {
                const q = historySearch.toLowerCase();
                if (!(c.name || '').toLowerCase().includes(q) && !c.spec_name.toLowerCase().includes(q)) return false;
            }
            if (historyStatusFilter && c.status !== historyStatusFilter) return false;
            return true;
        });
    }, [comparisons, historySearch, historyStatusFilter]);

    // Relative time helper
    const relativeTime = (dateStr: string) => {
        const diff = Date.now() - new Date(dateStr).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        return `${days}d ago`;
    };

    return (
        <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>Model Comparison</h2>

            {/* Section 1: New Comparison Form */}
            <div className="card-elevated animate-in stagger-1">
                <h3 style={{ fontWeight: 600, marginBottom: '0.75rem', fontSize: '0.95rem' }}>New Comparison</h3>

                {/* Top Row: Spec + Name */}
                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div style={{ flex: '2 1 250px' }}>
                        <label htmlFor="compare-spec" style={labelStyle}>
                            Test Spec {specs.length > 0 && <span style={{ color: 'var(--text-tertiary)', fontWeight: 400 }}>({specs.length} available)</span>}
                        </label>
                        <select
                            id="compare-spec"
                            value={selectedSpec}
                            onChange={e => setSelectedSpec(e.target.value)}
                            style={{
                                ...inputStyle,
                                opacity: running ? 0.5 : 1,
                                cursor: running ? 'not-allowed' : undefined,
                            }}
                            disabled={running}
                            aria-label="Select test spec"
                        >
                            <option value="">Select a spec...</option>
                            {specs.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                        </select>
                    </div>
                    <div style={{ flex: '1 1 180px' }}>
                        <label htmlFor="compare-name" style={labelStyle}>Name (optional)</label>
                        <input
                            id="compare-name"
                            placeholder="e.g., GPT vs Claude latency test"
                            value={comparisonName}
                            onChange={e => setComparisonName(e.target.value)}
                            style={{
                                ...inputStyle,
                                opacity: running ? 0.5 : 1,
                                cursor: running ? 'not-allowed' : undefined,
                            }}
                            disabled={running}
                            aria-label="Comparison name"
                        />
                    </div>
                </div>

                {/* Provider Selection Cards */}
                <div style={{ marginTop: '1rem' }}>
                    <label style={labelStyle}>
                        Select Providers (2+ required)
                    </label>

                    {providers.length === 0 ? (
                        <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            No providers configured. Add providers in the Providers tab.
                        </div>
                    ) : (
                        <div
                            style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
                                gap: '0.5rem',
                            }}
                            role="group"
                            aria-label="Provider selection"
                        >
                            {providers.map(p => {
                                const isSelected = selectedProviders.includes(p.id);
                                return (
                                    <div
                                        key={p.id}
                                        role="checkbox"
                                        aria-checked={isSelected}
                                        tabIndex={0}
                                        onClick={() => !running && toggleProvider(p.id)}
                                        onKeyDown={e => {
                                            if ((e.key === 'Enter' || e.key === ' ') && !running) {
                                                e.preventDefault();
                                                toggleProvider(p.id);
                                            }
                                        }}
                                        style={{
                                            position: 'relative',
                                            cursor: running ? 'not-allowed' : 'pointer',
                                            padding: '0.75rem',
                                            borderRadius: 'var(--radius)',
                                            border: `1.5px solid ${isSelected ? 'var(--primary)' : 'var(--border)'}`,
                                            background: isSelected ? 'var(--primary-glow, rgba(99, 102, 241, 0.08))' : 'var(--background-raised)',
                                            boxShadow: isSelected ? 'var(--shadow-glow-sm, 0 0 12px rgba(99, 102, 241, 0.15))' : 'none',
                                            transition: 'all 0.2s var(--ease-smooth)',
                                            opacity: running ? 0.5 : 1,
                                        }}
                                    >
                                        {/* Check icon top-right */}
                                        {isSelected && (
                                            <div style={{
                                                position: 'absolute',
                                                top: '0.4rem',
                                                right: '0.4rem',
                                                width: 18,
                                                height: 18,
                                                borderRadius: '50%',
                                                background: 'var(--primary)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'transform 0.2s var(--ease-smooth)',
                                            }}>
                                                <Check size={11} color="#fff" strokeWidth={3} />
                                            </div>
                                        )}
                                        <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text)', paddingRight: '1.5rem' }}>
                                            {p.name}
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
                                            {p.model_id}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* Footer Row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.75rem' }}>
                    <div
                        style={{ fontSize: '0.8rem', color: selectedProviders.length < 2 ? 'var(--text-tertiary)' : 'var(--text-secondary)' }}
                        aria-live="polite"
                    >
                        {selectedProviders.length < 2
                            ? `Select at least 2 providers`
                            : `${selectedProviders.length} of ${providers.length} providers selected`
                        }
                    </div>
                    <button
                        onClick={startComparison}
                        disabled={running || !selectedSpec || selectedProviders.length < 2}
                        aria-busy={running}
                        aria-disabled={running || !selectedSpec || selectedProviders.length < 2}
                        style={{
                            ...btnPrimary,
                            opacity: (running || !selectedSpec || selectedProviders.length < 2) ? 0.5 : 1,
                            cursor: (running || !selectedSpec || selectedProviders.length < 2) ? 'not-allowed' : 'pointer',
                        }}
                    >
                        {running ? (
                            <>
                                <Loader2 size={14} className="animate-spin" />
                                Comparing...
                            </>
                        ) : (
                            <>
                                <Scale size={14} />
                                Start Comparison
                            </>
                        )}
                    </button>
                </div>
            </div>

            {/* Section 2: Live Comparison Progress */}
            {running && compareProgress && (
                <div
                    className="card-elevated animate-in"
                    style={{
                        marginTop: '1rem',
                        borderLeft: '3px solid var(--primary)',
                    }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Loader2 size={16} className="animate-spin" style={{ color: 'var(--primary)' }} />
                            <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                                Comparing {compareProgress.progress_total} providers...
                            </span>
                        </div>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            {compareProgress.progress_current}/{compareProgress.progress_total}
                        </span>
                    </div>
                    <Progress value={comparePct} className="h-2" aria-label="Comparison progress" />
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap' }} aria-live="polite">
                        {selectedProviders.map((pid, idx) => {
                            const isDone = idx < (compareProgress.progress_current || 0);
                            return (
                                <span
                                    key={pid}
                                    style={{
                                        padding: '0.15rem 0.5rem',
                                        borderRadius: '9999px',
                                        fontSize: '0.75rem',
                                        fontWeight: 500,
                                        background: isDone ? 'rgba(34, 197, 94, 0.12)' : 'var(--surface-hover)',
                                        color: isDone ? 'var(--success)' : 'var(--text-tertiary)',
                                        border: `1px solid ${isDone ? 'rgba(34, 197, 94, 0.3)' : 'var(--border-subtle)'}`,
                                        transition: 'all 0.3s var(--ease-smooth)',
                                    }}
                                >
                                    {isDone && <CheckCircle size={10} style={{ marginRight: 3, verticalAlign: 'middle' }} />}
                                    {providerName(pid)}
                                </span>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Section 3: Comparison History */}
            {comparisons.length > 0 ? (
                <div className="animate-in stagger-3" style={{ marginTop: '1.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                        <h3 style={{ fontWeight: 600, fontSize: '0.95rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Scale size={16} style={{ color: 'var(--text-secondary)' }} />
                            Comparison History
                        </h3>
                        <Badge variant="secondary">{comparisons.length} comparison{comparisons.length !== 1 ? 's' : ''}</Badge>
                    </div>

                    {/* Filter Bar */}
                    <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                        <div style={{ position: 'relative', flex: '1 1 200px', maxWidth: 300 }}>
                            <Search size={14} style={{ position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                            <input
                                type="text"
                                placeholder="Search comparisons..."
                                value={historySearch}
                                onChange={e => setHistorySearch(e.target.value)}
                                style={{ ...inputStyle, paddingLeft: '2rem' }}
                                aria-label="Search comparisons"
                            />
                        </div>
                        <select
                            value={historyStatusFilter}
                            onChange={e => setHistoryStatusFilter(e.target.value)}
                            style={{
                                padding: '0.5rem 0.75rem',
                                borderRadius: 'var(--radius)',
                                border: '1px solid var(--border)',
                                background: 'var(--background-raised)',
                                color: 'var(--text)',
                                fontSize: '0.9rem',
                            }}
                            aria-label="Filter by status"
                        >
                            <option value="">All Statuses</option>
                            <option value="completed">Completed</option>
                            <option value="running">Running</option>
                            <option value="failed">Failed</option>
                        </select>
                    </div>

                    {/* Timeline Entries */}
                    {filteredComparisons.length === 0 ? (
                        <div style={{
                            ...cardStyleCompact,
                            textAlign: 'center',
                            color: 'var(--text-secondary)',
                            padding: '1.5rem',
                        }}>
                            No comparisons match filters
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                            {filteredComparisons.map(c => {
                                const isActive = selectedComparison?.id === c.id;
                                return (
                                    <div
                                        key={c.id}
                                        className="card-elevated"
                                        role="button"
                                        tabIndex={0}
                                        aria-expanded={isActive}
                                        onClick={() => viewComparison(c.id)}
                                        onKeyDown={e => {
                                            if (e.key === 'Enter' || e.key === ' ') {
                                                e.preventDefault();
                                                viewComparison(c.id);
                                            }
                                        }}
                                        style={{
                                            cursor: 'pointer',
                                            borderColor: isActive ? 'var(--primary)' : undefined,
                                            boxShadow: isActive ? 'var(--shadow-glow-sm, 0 0 12px rgba(99, 102, 241, 0.15))' : undefined,
                                            transition: 'all 0.2s var(--ease-smooth)',
                                        }}
                                    >
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                                <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                                                    {c.name || c.spec_name}
                                                </span>
                                                <Badge variant="secondary" style={{ fontSize: '0.7rem' }}>
                                                    {c.provider_ids.length} provider{c.provider_ids.length !== 1 ? 's' : ''}
                                                </Badge>
                                                <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                                                    {relativeTime(c.created_at)}
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                {c.winner_provider_id && (
                                                    <span style={{
                                                        display: 'inline-flex',
                                                        alignItems: 'center',
                                                        gap: '0.25rem',
                                                        fontSize: '0.78rem',
                                                        fontWeight: 600,
                                                        color: 'var(--success)',
                                                        padding: '0.15rem 0.5rem',
                                                        borderRadius: '9999px',
                                                        background: 'rgba(34, 197, 94, 0.1)',
                                                    }}>
                                                        <Trophy size={12} />
                                                        {providerName(c.winner_provider_id)}
                                                    </span>
                                                )}
                                                <StatusBadge status={c.status} />
                                                <button
                                                    onClick={e => {
                                                        e.stopPropagation();
                                                        setConfirmDialog({ open: true, comparisonId: c.id });
                                                    }}
                                                    style={{
                                                        ...btnSmall,
                                                        color: 'var(--text-tertiary)',
                                                        padding: '0.2rem 0.35rem',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                    }}
                                                    aria-label={`Delete comparison ${c.name || c.spec_name}`}
                                                >
                                                    <Trash2 size={13} />
                                                </button>
                                            </div>
                                        </div>
                                        {/* Provider names in bottom row */}
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: '0.25rem' }}>
                                            {c.provider_ids.map(pid => providerName(pid)).join(', ')}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            ) : !running && (
                <div style={{ marginTop: '1.5rem' }}>
                    <EmptyState
                        icon={<Scale size={32} />}
                        title="No comparisons yet"
                        description="Select a spec and providers above to run your first model comparison."
                    />
                </div>
            )}

            {/* Section 4: Skeleton loading state while fetching comparison details */}
            {detailLoading && !selectedComparison && (
                <div className="animate-in stagger-4" style={{ marginTop: '1.5rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                        <Skeleton className="h-5 w-32" style={{ borderRadius: 'var(--radius)', background: 'var(--surface-hover)' }} />
                    </div>
                    <div className="stagger-1" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
                        <Skeleton className="h-28 w-full" style={{ borderRadius: 'var(--radius)', background: 'var(--surface-hover)' }} />
                        <Skeleton className="h-28 w-full" style={{ borderRadius: 'var(--radius)', background: 'var(--surface-hover)' }} />
                        <Skeleton className="h-28 w-full" style={{ borderRadius: 'var(--radius)', background: 'var(--surface-hover)' }} />
                    </div>
                    <Skeleton className="h-56 w-full stagger-2" style={{ borderRadius: 'var(--radius)', background: 'var(--surface-hover)' }} />
                </div>
            )}

            {/* Section 4: Comparison Detail View */}
            {selectedComparison && (
                <div className="animate-in stagger-4" style={{ marginTop: '1.5rem' }}>
                    {/* Header with back button */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
                        <button
                            onClick={() => { setSelectedComparison(null); setMatrix(null); }}
                            style={{
                                ...btnSmall,
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.25rem',
                            }}
                            aria-label="Close comparison detail"
                        >
                            <ArrowLeft size={14} />
                            Back
                        </button>
                        <h3 style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                            {selectedComparison.name || selectedComparison.spec_name}
                        </h3>
                    </div>

                    {/* Summary Cards */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                        gap: '0.75rem',
                        marginBottom: '1rem',
                    }}>
                        {Object.entries(selectedComparison.comparison_summary || {}).map(([pid, data]: [string, any]) => {
                            const isWinner = pid === selectedComparison.winner_provider_id;
                            return (
                                <div
                                    key={pid}
                                    className="card-elevated"
                                    style={{
                                        borderTop: isWinner ? '3px solid var(--success)' : '3px solid var(--border)',
                                        background: isWinner ? 'rgba(34, 197, 94, 0.04)' : undefined,
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                        {isWinner && <Crown size={16} style={{ color: 'var(--success)' }} />}
                                        <span style={{ fontWeight: 600, fontSize: '1rem' }}>
                                            {providerName(pid)}
                                        </span>
                                        {isWinner && (
                                            <Badge style={{
                                                background: 'rgba(34, 197, 94, 0.15)',
                                                color: 'var(--success)',
                                                fontSize: '0.7rem',
                                            }}>
                                                Winner
                                            </Badge>
                                        )}
                                    </div>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                                        <div>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Pass Rate</div>
                                            <div style={{
                                                fontWeight: 700,
                                                fontSize: '1.1rem',
                                                color: data.pass_rate >= 80 ? 'var(--success)' : data.pass_rate >= 50 ? 'var(--warning)' : 'var(--danger)',
                                            }}>
                                                {data.pass_rate}%
                                            </div>
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Avg Latency</div>
                                            <div style={{ fontWeight: 600, fontSize: '1rem' }}>
                                                {Math.round(data.avg_latency_ms || 0)}<span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>ms</span>
                                            </div>
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Cost</div>
                                            <div style={{ fontWeight: 600, fontSize: '1rem' }}>
                                                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>$</span>{(data.total_cost_usd || 0).toFixed(4)}
                                            </div>
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Wins</div>
                                            <div style={{ fontWeight: 600, fontSize: '1rem' }}>{data.wins || 0}</div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Result Matrix */}
                    {matrix && matrix.matrix && matrix.matrix.length > 0 && (
                        <div style={{
                            overflowX: 'auto',
                            borderRadius: 'var(--radius)',
                            border: '1px solid var(--border-subtle)',
                        }}>
                            <table role="table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                <thead>
                                    <tr>
                                        <th style={{
                                            ...thStyle,
                                            position: 'sticky',
                                            left: 0,
                                            zIndex: 1,
                                            minWidth: 180,
                                        }}>
                                            Test Case
                                        </th>
                                        {selectedComparison.provider_ids?.map((pid: string) => {
                                            const isWinnerCol = pid === selectedComparison.winner_provider_id;
                                            return (
                                                <th
                                                    key={pid}
                                                    style={{
                                                        ...thStyle,
                                                        background: isWinnerCol ? 'rgba(34, 197, 94, 0.06)' : thStyle.background,
                                                    }}
                                                    aria-label={isWinnerCol ? `${providerName(pid)} (Winner)` : providerName(pid)}
                                                >
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                                        {isWinnerCol && <Trophy size={12} style={{ color: 'var(--success)' }} />}
                                                        {providerName(pid)}
                                                    </div>
                                                </th>
                                            );
                                        })}
                                    </tr>
                                </thead>
                                <tbody>
                                    {matrix.matrix.map((row: any, i: number) => (
                                        <tr
                                            key={i}
                                            style={{ transition: 'background 0.15s var(--ease-smooth)' }}
                                            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--surface-hover)'; }}
                                            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                                        >
                                            <td style={{
                                                ...tdStyle,
                                                position: 'sticky',
                                                left: 0,
                                                background: 'var(--surface)',
                                                zIndex: 1,
                                                minWidth: 180,
                                            }}>
                                                <strong>{row.test_case_id}</strong>
                                                <span style={{ color: 'var(--text-secondary)', marginLeft: '0.35rem' }}>{row.test_case_name}</span>
                                            </td>
                                            {selectedComparison.provider_ids?.map((pid: string) => {
                                                const cell = row.providers?.[pid];
                                                if (!cell) return <td key={pid} style={tdStyle}>-</td>;
                                                return (
                                                    <td key={pid} style={{
                                                        ...tdStyle,
                                                        background: cell.passed ? 'rgba(34, 197, 94, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                                                    }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                                            {cell.passed ? (
                                                                <CheckCircle size={13} style={{ color: 'var(--success)', flexShrink: 0 }} />
                                                            ) : (
                                                                <XCircle size={13} style={{ color: 'var(--danger)', flexShrink: 0 }} />
                                                            )}
                                                            <span style={{
                                                                color: cell.passed ? 'var(--success)' : 'var(--danger)',
                                                                fontWeight: 600,
                                                                fontSize: '0.8rem',
                                                            }}>
                                                                {cell.passed ? 'PASS' : 'FAIL'}
                                                            </span>
                                                        </div>
                                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
                                                            {cell.latency_ms}ms | ${cell.cost_usd?.toFixed(5)}
                                                        </div>
                                                        {cell.output && (
                                                            <div style={{ fontSize: '0.72rem', marginTop: '0.15rem', maxHeight: 60, overflow: 'hidden', color: 'var(--text-secondary)' }}>
                                                                {cell.output.length > 80 ? cell.output.slice(0, 80) + '...' : cell.output}
                                                            </div>
                                                        )}
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {/* Confirm Dialog for Delete */}
            <ConfirmDialog
                open={confirmDialog.open}
                onOpenChange={open => setConfirmDialog(prev => ({ ...prev, open }))}
                title="Delete Comparison"
                description="Are you sure you want to delete this comparison? This action cannot be undone."
                confirmLabel="Delete"
                variant="danger"
                loading={deleteLoading}
                onConfirm={() => {
                    deleteComparison(confirmDialog.comparisonId);
                }}
            />
        </div>
    );
}
