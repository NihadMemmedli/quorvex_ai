'use client';
import React from 'react';
import {
    Loader2, ChevronDown, ChevronRight, Clock, RefreshCw,
} from 'lucide-react';
import { timeAgo } from '@/lib/formatting';
import { ApiTestRun } from './types';

interface HistoryPanelProps {
    apiRuns: ApiTestRun[];
    runsLoading: boolean;
    runsHasMore: boolean;
    runsOffset: number;
    expandedRunId: string | null;
    setExpandedRunId: (id: string | null) => void;
    fetchApiRuns: (offset?: number, append?: boolean) => Promise<void>;
    setRunsOffset: (offset: number) => void;
    RUNS_PAGE_SIZE: number;
    runsTotal: number;
    onViewDetail?: (runId: string) => void;
    onRetry?: (runId: string) => void;
}

export default function HistoryPanel({
    apiRuns,
    runsLoading,
    runsHasMore,
    runsOffset,
    expandedRunId,
    setExpandedRunId,
    fetchApiRuns,
    setRunsOffset,
    RUNS_PAGE_SIZE,
    runsTotal,
    onViewDetail,
    onRetry,
}: HistoryPanelProps) {
    return (
        <div>
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', alignItems: 'center' }}>
                <button
                    onClick={() => { setRunsOffset(0); fetchApiRuns(0); }}
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
                    {apiRuns.length} of {runsTotal} run{runsTotal !== 1 ? 's' : ''}
                </span>
            </div>

            {runsLoading && apiRuns.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                    <p>Loading run history...</p>
                </div>
            ) : apiRuns.length === 0 ? (
                <div style={{
                    textAlign: 'center', padding: '3rem',
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                }}>
                    <Clock size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                    <p style={{ color: 'var(--text-secondary)' }}>No test runs yet</p>
                </div>
            ) : (
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', overflow: 'hidden',
                }}>
                    {/* Table header */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: '24px 120px 1fr 180px 100px 160px',
                        padding: '0.6rem 1rem', borderBottom: '1px solid var(--border)',
                        fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>
                        <span></span>
                        <span>Status</span>
                        <span>Spec Name</span>
                        <span>Run ID</span>
                        <span>Duration</span>
                        <span>Timestamp</span>
                    </div>

                    {/* Table rows */}
                    {apiRuns.map(run => {
                        const passed = run.status === 'passed';
                        const running = run.status === 'running';
                        const isExpanded = expandedRunId === run.id;
                        const duration = (() => {
                            if (run.started_at && run.completed_at) {
                                const ms = new Date(run.completed_at).getTime() - new Date(run.started_at).getTime();
                                const secs = Math.floor(ms / 1000);
                                if (secs < 60) return `${secs}s`;
                                return `${Math.floor(secs / 60)}m ${secs % 60}s`;
                            }
                            return '-';
                        })();

                        return (
                            <div key={run.id}>
                                <div
                                    style={{
                                        display: 'grid', gridTemplateColumns: '24px 120px 1fr 180px 100px 160px',
                                        padding: '0.6rem 1rem', borderBottom: isExpanded ? 'none' : '1px solid var(--border)',
                                        fontSize: '0.8rem', alignItems: 'center',
                                        cursor: 'pointer', transition: 'background 0.15s var(--ease-smooth)',
                                    }}
                                    onClick={() => setExpandedRunId(isExpanded ? null : run.id)}
                                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                                >
                                    <span style={{ color: 'var(--text-secondary)' }}>
                                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                    </span>
                                    <span>
                                        <span style={{
                                            display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                                            fontWeight: 600,
                                            background: running ? 'var(--primary-glow)' : passed ? 'var(--success-muted)' : 'var(--danger-muted)',
                                            color: running ? 'var(--primary)' : passed ? 'var(--success)' : 'var(--danger)',
                                        }}>
                                            {running && <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} />}
                                            {run.status.toUpperCase()}
                                        </span>
                                        {run.healing_attempt && run.healing_attempt > 0 && (
                                            <span style={{
                                                display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
                                                padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                                fontWeight: 600, background: 'var(--warning-muted)', color: 'var(--warning)',
                                                marginLeft: '0.25rem',
                                            }}>
                                                Healed
                                            </span>
                                        )}
                                    </span>
                                    <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {run.spec_name}
                                    </span>
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', fontFamily: 'monospace' }}>
                                        {run.id.substring(0, 16)}
                                    </span>
                                    <span style={{ color: 'var(--text-secondary)' }}>
                                        {duration}
                                    </span>
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                        {timeAgo(run.created_at)}
                                    </span>
                                </div>
                                {isExpanded && (
                                    <div style={{
                                        padding: '0.75rem 1rem 1rem',
                                        borderBottom: '1px solid var(--border)',
                                        background: 'rgba(0,0,0,0.15)',
                                    }}>
                                        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                <span style={{ fontWeight: 600 }}>Run ID:</span> {run.id}
                                            </div>
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                <span style={{ fontWeight: 600 }}>Type:</span> {run.test_type || 'api'}
                                            </div>
                                            {run.current_stage && (
                                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                    <span style={{ fontWeight: 600 }}>Stage:</span> {run.current_stage}
                                                </div>
                                            )}
                                        </div>
                                        {run.error_message && (
                                            <div style={{
                                                padding: '0.5rem 0.75rem', marginBottom: '0.75rem',
                                                background: 'var(--danger-muted)', border: '1px solid rgba(239, 68, 68, 0.2)',
                                                borderRadius: 'var(--radius)', fontSize: '0.75rem', color: 'var(--danger)',
                                            }}>
                                                {run.error_message}
                                            </div>
                                        )}
                                        {run.stage_message && (
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                                                {run.stage_message}
                                            </div>
                                        )}
                                        <button
                                            onClick={() => onViewDetail?.(run.id)}
                                            style={{
                                                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                                                padding: '0.35rem 0.75rem', fontSize: '0.75rem', fontWeight: 500,
                                                background: 'var(--primary-glow)', color: 'var(--primary)',
                                                border: '1px solid rgba(59, 130, 246, 0.2)', borderRadius: 'var(--radius)',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            View Full Details
                                        </button>
                                        {run.status === 'failed' && (
                                            <button
                                                onClick={() => onRetry?.(run.id)}
                                                style={{
                                                    display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                                                    padding: '0.35rem 0.75rem', fontSize: '0.75rem', fontWeight: 500,
                                                    background: 'var(--warning-muted)', color: 'var(--warning)',
                                                    border: '1px solid rgba(245, 158, 11, 0.2)', borderRadius: 'var(--radius)',
                                                    cursor: 'pointer', marginLeft: '0.5rem',
                                                }}
                                            >
                                                <RefreshCw size={12} /> Retry
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}

                    {/* Load More */}
                    {runsHasMore && (
                        <div style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>
                            <button
                                onClick={() => fetchApiRuns(runsOffset + RUNS_PAGE_SIZE, true)}
                                disabled={runsLoading}
                                style={{
                                    padding: '0.4rem 1rem', background: 'var(--background)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                    cursor: runsLoading ? 'wait' : 'pointer', color: 'var(--text-secondary)',
                                    fontSize: '0.8rem', opacity: runsLoading ? 0.6 : 1,
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
