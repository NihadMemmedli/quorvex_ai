'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyleCompact, inputStyle } from '@/lib/styles';
import { StatusBadge } from '@/components/shared';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import { Search, Filter, ChevronDown, ChevronUp, Database } from 'lucide-react';
import AssertionsList from './AssertionsList';
import type { Provider, Run, TestResult } from './types';

interface HistoryTabProps {
    projectId: string;
}

export default function HistoryTab({ projectId }: HistoryTabProps) {
    const [runs, setRuns] = useState<Run[]>([]);
    const [loading, setLoading] = useState(true);
    const [expandedRun, setExpandedRun] = useState<string | null>(null);
    const [results, setResults] = useState<TestResult[]>([]);
    const [providers, setProviders] = useState<Record<string, string>>({});

    // Filter state
    const [searchQuery, setSearchQuery] = useState('');
    const [providerFilter, setProviderFilter] = useState('');
    const [statusFilter, setStatusFilter] = useState('');
    const [sourceFilter, setSourceFilter] = useState<'' | 'dataset' | 'spec'>('');

    // Pagination
    const [displayCount, setDisplayCount] = useState(20);

    // Expandable content
    const [expandedInputs, setExpandedInputs] = useState<Set<string>>(new Set());
    const [expandedOutputs, setExpandedOutputs] = useState<Set<string>>(new Set());

    // Confirm dialog
    const [confirmDialog, setConfirmDialog] = useState<{ open: boolean; runId: string }>({ open: false, runId: '' });

    useEffect(() => {
        setLoading(true);
        Promise.all([
            fetch(`${API_BASE}/llm-testing/runs?project_id=${projectId}`)
                .then(r => r.json())
                .then(setRuns)
                .catch(() => { toast.error('Failed to load run history'); }),
            fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`)
                .then(r => r.json())
                .then((ps: Provider[]) => {
                    const map: Record<string, string> = {};
                    ps.forEach(p => { map[p.id] = `${p.name} (${p.model_id})`; });
                    setProviders(map);
                })
                .catch(() => { toast.error('Failed to load providers'); }),
        ]).finally(() => setLoading(false));
    }, [projectId]);

    const toggleExpand = useCallback(async (runId: string) => {
        if (expandedRun === runId) { setExpandedRun(null); return; }
        setExpandedRun(runId);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/runs/${runId}/results`);
            if (res.ok) setResults(await res.json());
            else toast.error('Failed to load run results');
        } catch {
            toast.error('Failed to load run results');
        }
    }, [expandedRun]);

    // Unique provider IDs from runs for filter dropdown
    const uniqueProviders = useMemo(() => {
        const ids = new Set<string>();
        runs.forEach(r => { if (r.provider_id) ids.add(r.provider_id); });
        return Array.from(ids);
    }, [runs]);

    // Filtered runs
    const filteredRuns = useMemo(() => {
        return runs.filter(r => {
            if (searchQuery && !r.spec_name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
            if (providerFilter && r.provider_id !== providerFilter) return false;
            if (statusFilter && r.status !== statusFilter) return false;
            if (sourceFilter === 'dataset' && !r.dataset_id) return false;
            if (sourceFilter === 'spec' && r.dataset_id) return false;
            return true;
        });
    }, [runs, searchQuery, providerFilter, statusFilter, sourceFilter]);

    // Paginated runs
    const displayedRuns = useMemo(() => filteredRuns.slice(0, displayCount), [filteredRuns, displayCount]);

    const toggleInput = (id: string) => {
        setExpandedInputs(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const toggleOutput = (id: string) => {
        setExpandedOutputs(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    return (
        <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>Run History</h2>

            {/* Filter Bar */}
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <div style={{ position: 'relative', flex: '1 1 200px', maxWidth: 300 }}>
                    <Search size={14} style={{ position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                    <input
                        type="text"
                        placeholder="Search by spec name..."
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        style={{ ...inputStyle, paddingLeft: '2rem' }}
                    />
                </div>
                <select
                    value={providerFilter}
                    onChange={e => setProviderFilter(e.target.value)}
                    style={{
                        padding: '0.5rem 0.75rem',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        background: 'var(--background-raised)',
                        color: 'var(--text)',
                        fontSize: '0.9rem',
                    }}
                >
                    <option value="">All Providers</option>
                    {uniqueProviders.map(pid => (
                        <option key={pid} value={pid}>{providers[pid] || pid}</option>
                    ))}
                </select>
                <select
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value)}
                    style={{
                        padding: '0.5rem 0.75rem',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        background: 'var(--background-raised)',
                        color: 'var(--text)',
                        fontSize: '0.9rem',
                    }}
                >
                    <option value="">All Statuses</option>
                    <option value="completed">Completed</option>
                    <option value="failed">Failed</option>
                </select>
                <select
                    value={sourceFilter}
                    onChange={e => setSourceFilter(e.target.value as '' | 'dataset' | 'spec')}
                    style={{
                        padding: '0.5rem 0.75rem',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        background: 'var(--background-raised)',
                        color: 'var(--text)',
                        fontSize: '0.9rem',
                    }}
                >
                    <option value="">All Sources</option>
                    <option value="dataset">From Datasets</option>
                    <option value="spec">From Specs</option>
                </select>
            </div>

            {loading ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} style={{ height: 72, width: '100%' }} />
                    ))}
                </div>
            ) : filteredRuns.length === 0 ? (
                <div style={{ ...cardStyleCompact, textAlign: 'center', color: 'var(--text-secondary)' }}>
                    {runs.length === 0 ? 'No runs yet. Go to the Run tab to execute a test suite.' : 'No runs match the current filters.'}
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {displayedRuns.map(r => (
                        <div key={r.id}>
                            <div onClick={() => toggleExpand(r.id)} style={{ ...cardStyleCompact, cursor: 'pointer' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                        <span style={{ fontWeight: 600 }}>{r.spec_name}</span>
                                        {r.dataset_name && (
                                            <span style={{
                                                display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                                                fontSize: '0.72rem', fontWeight: 500,
                                                background: 'var(--primary-light, rgba(59,130,246,0.1))',
                                                color: 'var(--primary)',
                                                borderRadius: '4px', padding: '0.1rem 0.4rem',
                                            }}>
                                                <Database size={10} />
                                                {r.dataset_name}
                                            </span>
                                        )}
                                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{providers[r.provider_id || ''] || r.provider_id}</span>
                                    </div>
                                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', fontSize: '0.85rem' }}>
                                        <span style={{ color: r.pass_rate >= 80 ? 'var(--success)' : r.pass_rate >= 50 ? 'var(--warning)' : 'var(--danger)' }}>
                                            {r.pass_rate}% ({r.passed_cases}/{r.total_cases})
                                        </span>
                                        {r.avg_latency_ms !== null && <span style={{ color: 'var(--text-secondary)' }}>{Math.round(r.avg_latency_ms)}ms</span>}
                                        <span style={{ color: 'var(--text-secondary)' }}>${r.total_cost_usd.toFixed(4)}</span>
                                        <StatusBadge status={r.status} />
                                        {expandedRun === r.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                                    </div>
                                </div>
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                    {new Date(r.created_at).toLocaleString()}
                                    {r.duration_seconds && ` | ${r.duration_seconds}s`}
                                </div>
                            </div>
                            {expandedRun === r.id && results.length > 0 && (
                                <div style={{ marginLeft: '1rem', marginTop: '0.25rem' }}>
                                    {results.map(tr => {
                                        const inputKey = `input-${tr.id}`;
                                        const outputKey = `output-${tr.id}`;
                                        const inputExpanded = expandedInputs.has(inputKey);
                                        const outputExpanded = expandedOutputs.has(outputKey);
                                        return (
                                            <div key={tr.id} style={{ ...cardStyleCompact, padding: '0.75rem', marginBottom: '0.25rem', borderLeft: `3px solid ${tr.overall_passed ? 'var(--success)' : 'var(--danger)'}` }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                                    <strong style={{ fontSize: '0.9rem' }}>{tr.test_case_id}: {tr.test_case_name}</strong>
                                                    <span style={{ fontSize: '0.8rem', color: tr.overall_passed ? 'var(--success)' : 'var(--danger)' }}>
                                                        {tr.overall_passed ? 'PASSED' : 'FAILED'}
                                                    </span>
                                                </div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                    {tr.latency_ms}ms | {tr.tokens_in + tr.tokens_out} tokens | ${tr.estimated_cost_usd.toFixed(5)}
                                                </div>
                                                <div style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>
                                                    <div>
                                                        <strong>Input:</strong>{' '}
                                                        {tr.input_prompt.length <= 200 ? (
                                                            tr.input_prompt
                                                        ) : (
                                                            <>
                                                                {inputExpanded ? tr.input_prompt : tr.input_prompt.slice(0, 200) + '...'}
                                                                <button
                                                                    onClick={e => { e.stopPropagation(); toggleInput(inputKey); }}
                                                                    style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer', fontSize: '0.8rem', marginLeft: '0.25rem' }}
                                                                >
                                                                    {inputExpanded ? 'Show less' : 'Show more'}
                                                                </button>
                                                            </>
                                                        )}
                                                    </div>
                                                    <div style={{ marginTop: '0.25rem' }}>
                                                        <strong>Output:</strong>{' '}
                                                        {tr.actual_output.length <= 300 ? (
                                                            tr.actual_output
                                                        ) : (
                                                            <>
                                                                {outputExpanded ? tr.actual_output : tr.actual_output.slice(0, 300) + '...'}
                                                                <button
                                                                    onClick={e => { e.stopPropagation(); toggleOutput(outputKey); }}
                                                                    style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer', fontSize: '0.8rem', marginLeft: '0.25rem' }}
                                                                >
                                                                    {outputExpanded ? 'Show less' : 'Show more'}
                                                                </button>
                                                            </>
                                                        )}
                                                    </div>
                                                </div>
                                                {tr.assertions && tr.assertions.length > 0 && (
                                                    <AssertionsList assertions={tr.assertions} />
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    ))}

                    {/* Load More */}
                    {displayCount < filteredRuns.length && (
                        <button
                            onClick={() => setDisplayCount(prev => prev + 20)}
                            style={{
                                padding: '0.6rem 1.5rem',
                                background: 'var(--surface)',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                cursor: 'pointer',
                                color: 'var(--primary)',
                                fontWeight: 500,
                                fontSize: '0.85rem',
                                alignSelf: 'center',
                                transition: 'all 0.2s var(--ease-smooth)',
                            }}
                        >
                            Load More ({filteredRuns.length - displayCount} remaining)
                        </button>
                    )}
                </div>
            )}

            <ConfirmDialog
                open={confirmDialog.open}
                onOpenChange={open => setConfirmDialog(prev => ({ ...prev, open }))}
                title="Delete Run"
                description="Are you sure you want to delete this run? This action cannot be undone."
                confirmLabel="Delete"
                variant="danger"
                onConfirm={() => {
                    // placeholder for future delete action
                }}
            />
        </div>
    );
}
