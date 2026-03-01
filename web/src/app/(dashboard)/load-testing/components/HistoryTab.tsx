'use client';
import React from 'react';
import {
    Loader2, ChevronDown, ChevronRight, RefreshCw, Clock,
} from 'lucide-react';
import { timeAgo } from '@/lib/formatting';
import { getResponseTimeColor } from '@/lib/colors';
import type { LoadTestRun, ComparisonData } from './types';

interface HistoryTabProps {
    runs: LoadTestRun[];
    runsLoading: boolean;
    runsHasMore: boolean;
    runsOffset: number;
    RUNS_PAGE_SIZE: number;
    expandedRunId: string | null;
    expandedRunData: LoadTestRun | null;
    compareIds: Set<string>;
    comparisonData: ComparisonData | null;
    comparisonLoading: boolean;
    onFetchRuns: (offset: number, append?: boolean) => void;
    onSetExpandedRunId: (id: string | null) => void;
    onLoadRunDetails: (id: string) => void;
    onToggleCompareId: (id: string) => void;
    onSetCompareIds: (ids: Set<string>) => void;
    onLoadComparison: () => void;
    onSetComparisonData: (data: ComparisonData | null) => void;
    onAnalyzeRun?: (runId: string) => void;
    analyzingRunId?: string | null;
    /** Lazy-loaded ResultsView component */
    ResultsView: React.ComponentType<{ run: LoadTestRun; onAnalyze?: () => void; analyzing?: boolean }>;
    /** Lazy-loaded ComparisonView component */
    ComparisonView: React.ComponentType<{ data: ComparisonData; onBack: () => void }>;
}

export default function HistoryTab({
    runs,
    runsLoading,
    runsHasMore,
    runsOffset,
    RUNS_PAGE_SIZE,
    expandedRunId,
    expandedRunData,
    compareIds,
    comparisonData,
    comparisonLoading,
    onFetchRuns,
    onSetExpandedRunId,
    onLoadRunDetails,
    onToggleCompareId,
    onSetCompareIds,
    onLoadComparison,
    onSetComparisonData,
    onAnalyzeRun,
    analyzingRunId,
    ResultsView,
    ComparisonView,
}: HistoryTabProps) {
    if (comparisonData) {
        return comparisonLoading ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                <p>Loading comparison...</p>
            </div>
        ) : (
            <ComparisonView
                data={comparisonData}
                onBack={() => { onSetComparisonData(null); onSetCompareIds(new Set()); }}
            />
        );
    }

    return (
        <div>
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', alignItems: 'center' }}>
                <button
                    onClick={() => onFetchRuns(0)}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.5rem 0.75rem', background: 'var(--surface)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.875rem',
                    }}
                >
                    <RefreshCw size={14} /> Refresh
                </button>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                    {runs.length} run{runs.length !== 1 ? 's' : ''} loaded
                </span>
            </div>

            {/* Comparison Action Bar */}
            {compareIds.size > 0 && (
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '0.75rem',
                    padding: '0.6rem 1rem', marginBottom: '0.75rem',
                    background: 'rgba(59, 130, 246, 0.05)',
                    border: '1px solid rgba(59, 130, 246, 0.2)',
                    borderRadius: 'var(--radius)',
                }}>
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)', flex: 1 }}>
                        {compareIds.size} run{compareIds.size !== 1 ? 's' : ''} selected for comparison
                    </span>
                    <button
                        onClick={() => onSetCompareIds(new Set())}
                        style={{
                            padding: '0.35rem 0.75rem', background: 'var(--surface)',
                            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                            cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.8rem',
                        }}
                    >
                        Clear
                    </button>
                    <button
                        onClick={onLoadComparison}
                        disabled={compareIds.size !== 2 || comparisonLoading}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.4rem',
                            padding: '0.35rem 0.85rem', background: compareIds.size === 2 ? 'var(--primary)' : 'var(--surface)',
                            color: compareIds.size === 2 ? 'white' : 'var(--text-secondary)',
                            border: compareIds.size === 2 ? 'none' : '1px solid var(--border)',
                            borderRadius: 'var(--radius)', cursor: compareIds.size === 2 ? 'pointer' : 'not-allowed',
                            fontSize: '0.8rem', fontWeight: 600,
                            opacity: compareIds.size !== 2 ? 0.5 : 1,
                        }}
                    >
                        {comparisonLoading && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        Compare
                    </button>
                </div>
            )}

            {runsLoading && runs.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                    <p>Loading run history...</p>
                </div>
            ) : runs.length === 0 ? (
                <div style={{
                    textAlign: 'center', padding: '3rem',
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                }}>
                    <Clock size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                    <p style={{ color: 'var(--text-secondary)' }}>No load test runs yet</p>
                </div>
            ) : (
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', overflow: 'hidden',
                }}>
                    {/* Table header */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '32px 24px 90px 1fr 100px 90px 90px 80px 90px 140px',
                        padding: '0.6rem 1rem', borderBottom: '1px solid var(--border)',
                        fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-tertiary)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>
                        <span></span>
                        <span></span>
                        <span>Status</span>
                        <span>Spec / Script</span>
                        <span style={{ textAlign: 'right' }}>Requests</span>
                        <span style={{ textAlign: 'right' }}>Avg ms</span>
                        <span style={{ textAlign: 'right' }}>P95 ms</span>
                        <span style={{ textAlign: 'right' }}>RPS</span>
                        <span style={{ textAlign: 'right' }}>Duration</span>
                        <span style={{ textAlign: 'right' }}>Date</span>
                    </div>

                    {/* Rows */}
                    {runs.map((run, i) => {
                        const isExpanded = expandedRunId === run.id;
                        const isChecked = compareIds.has(run.id);
                        const isDisabled = compareIds.size >= 2 && !isChecked;
                        const statusColorVal = run.status === 'completed' ? 'var(--success)'
                            : run.status === 'failed' ? 'var(--danger)'
                            : run.status === 'running' ? 'var(--primary)'
                            : 'var(--text-secondary)';
                        const statusBg = run.status === 'completed' ? 'rgba(34, 197, 94, 0.1)'
                            : run.status === 'failed' ? 'var(--danger-muted)'
                            : run.status === 'running' ? 'var(--primary-glow)'
                            : 'rgba(156, 163, 175, 0.1)';

                        return (
                            <React.Fragment key={run.id}>
                                <div
                                    style={{
                                        display: 'grid',
                                        gridTemplateColumns: '32px 24px 90px 1fr 100px 90px 90px 80px 90px 140px',
                                        padding: '0.6rem 1rem',
                                        borderBottom: '1px solid var(--border)',
                                        cursor: 'pointer',
                                        background: isChecked
                                            ? 'rgba(59, 130, 246, 0.05)'
                                            : i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)',
                                        fontSize: '0.8rem',
                                        alignItems: 'center',
                                    }}
                                    onClick={() => {
                                        if (isExpanded) {
                                            onSetExpandedRunId(null);
                                        } else {
                                            onSetExpandedRunId(run.id);
                                            onLoadRunDetails(run.id);
                                        }
                                    }}
                                >
                                    <span onClick={e => e.stopPropagation()}>
                                        <input
                                            type="checkbox"
                                            checked={isChecked}
                                            disabled={isDisabled}
                                            onChange={() => onToggleCompareId(run.id)}
                                            style={{
                                                cursor: isDisabled ? 'not-allowed' : 'pointer',
                                                accentColor: 'var(--primary)',
                                                width: '14px', height: '14px',
                                            }}
                                        />
                                    </span>
                                    <span>{isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                        <span style={{
                                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                                            fontWeight: 600, background: statusBg, color: statusColorVal,
                                        }}>
                                            {run.status}
                                        </span>
                                        {run.worker_count && run.worker_count > 1 && (
                                            <span style={{
                                                padding: '0.1rem 0.35rem', borderRadius: '999px', fontSize: '0.6rem',
                                                fontWeight: 600, background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)',
                                            }} title={`Distributed across ${run.worker_count} workers`}>
                                                {run.worker_count}w
                                            </span>
                                        )}
                                    </span>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {run.spec_name || run.script_path || '-'}
                                    </span>
                                    <span style={{ textAlign: 'right' }}>{run.total_requests?.toLocaleString() || '-'}</span>
                                    <span style={{ textAlign: 'right', color: getResponseTimeColor(run.avg_response_time_ms || 0) }}>
                                        {run.avg_response_time_ms ? `${run.avg_response_time_ms.toFixed(0)}` : '-'}
                                    </span>
                                    <span style={{ textAlign: 'right', color: getResponseTimeColor(run.p95_response_time_ms || 0) }}>
                                        {run.p95_response_time_ms ? `${run.p95_response_time_ms.toFixed(0)}` : '-'}
                                    </span>
                                    <span style={{ textAlign: 'right' }}>
                                        {run.peak_rps ? `${run.peak_rps.toFixed(1)}` : '-'}
                                    </span>
                                    <span style={{ textAlign: 'right' }}>
                                        {run.duration_seconds ? `${run.duration_seconds}s` : '-'}
                                    </span>
                                    <span style={{ textAlign: 'right', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                        {timeAgo(run.created_at)}
                                    </span>
                                </div>

                                {/* Expanded Results */}
                                {isExpanded && (
                                    <div style={{
                                        padding: '1rem', borderBottom: '1px solid var(--border)',
                                        background: 'rgba(0,0,0,0.02)',
                                    }}>
                                        {expandedRunData ? (
                                            <ResultsView
                                                run={expandedRunData}
                                                onAnalyze={onAnalyzeRun ? () => onAnalyzeRun(expandedRunData.id) : undefined}
                                                analyzing={analyzingRunId === expandedRunData.id}
                                            />
                                        ) : (
                                            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                                                <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                                                <p>Loading run details...</p>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </React.Fragment>
                        );
                    })}

                    {/* Load More */}
                    {runsHasMore && (
                        <div style={{ padding: '0.75rem', textAlign: 'center' }}>
                            <button
                                onClick={() => onFetchRuns(runsOffset + RUNS_PAGE_SIZE, true)}
                                disabled={runsLoading}
                                style={{
                                    padding: '0.4rem 1rem', background: 'var(--surface)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                    cursor: runsLoading ? 'wait' : 'pointer', color: 'var(--text-secondary)',
                                    fontSize: '0.8rem',
                                }}
                            >
                                {runsLoading ? 'Loading...' : 'Load More'}
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
