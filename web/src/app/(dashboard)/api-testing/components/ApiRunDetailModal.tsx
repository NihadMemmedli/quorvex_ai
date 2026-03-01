'use client';
import React, { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import {
    X, Loader2, Clock, CheckCircle, AlertCircle, ChevronDown, ChevronRight,
    RefreshCw, Heart, Code, FileText, Activity, Play,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { timeAgo } from '@/lib/formatting';
import { ApiRunDetail, TestResultDetail, TestResultsSummary, HealingAttempt } from './types';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });

interface ApiRunDetailModalProps {
    runId: string;
    onClose: () => void;
    onRetry?: (jobId: string) => void;
}

const STATUS_COLORS: Record<string, string> = {
    passed: 'var(--success)',
    failed: 'var(--danger)',
    running: 'var(--primary)',
    skipped: 'var(--text-tertiary)',
    timedOut: 'var(--warning)',
    flaky: 'var(--warning)',
};

const ERROR_CATEGORY_COLORS: Record<string, string> = {
    auth: 'var(--warning)',
    connectivity: 'var(--accent)',
    assertion: 'var(--danger)',
    timeout: 'var(--warning)',
    syntax: 'var(--danger)',
    runtime: 'var(--danger)',
    unknown: 'var(--text-tertiary)',
};

function getStatusColor(status: string): string {
    return STATUS_COLORS[status] || 'var(--text-tertiary)';
}

function getCategoryColor(category: string): string {
    return ERROR_CATEGORY_COLORS[category] || 'var(--text-tertiary)';
}

export default function ApiRunDetailModal({ runId, onClose, onRetry }: ApiRunDetailModalProps) {
    const [data, setData] = useState<ApiRunDetail | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [retrying, setRetrying] = useState(false);

    // Collapsible section states
    const [expandedTests, setExpandedTests] = useState<Set<number>>(new Set());
    const [showCode, setShowCode] = useState(false);
    const [showLog, setShowLog] = useState(false);

    useEffect(() => {
        const fetchDetail = async () => {
            setLoading(true);
            setError(null);
            try {
                const res = await fetch(`${API_BASE}/api-testing/runs/${runId}`);
                if (res.ok) {
                    const d = await res.json();
                    setData(d);
                } else {
                    const err = await res.json().catch(() => ({ detail: 'Failed to load run details' }));
                    setError(err.detail || 'Failed to load run details');
                }
            } catch {
                setError('Network error while fetching run details');
            } finally {
                setLoading(false);
            }
        };
        fetchDetail();
    }, [runId]);

    const handleRetry = async () => {
        setRetrying(true);
        try {
            const res = await fetch(`${API_BASE}/api-testing/runs/${runId}/retry`, { method: 'POST' });
            if (res.ok) {
                const d = await res.json();
                onRetry?.(d.job_id);
            } else {
                const err = await res.json().catch(() => ({ detail: 'Failed to retry' }));
                setError(err.detail || 'Failed to retry');
            }
        } catch {
            setError('Network error while retrying');
        } finally {
            setRetrying(false);
        }
    };

    const toggleTest = (index: number) => {
        setExpandedTests(prev => {
            const next = new Set(prev);
            if (next.has(index)) next.delete(index);
            else next.add(index);
            return next;
        });
    };

    const duration = (() => {
        if (data?.started_at && data?.completed_at) {
            const ms = new Date(data.completed_at).getTime() - new Date(data.started_at).getTime();
            const secs = Math.floor(ms / 1000);
            if (secs < 60) return `${secs}s`;
            return `${Math.floor(secs / 60)}m ${secs % 60}s`;
        }
        return null;
    })();

    return (
        <div
            style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0, 0, 0, 0.6)', display: 'flex', alignItems: 'center',
                justifyContent: 'center', zIndex: 1000,
            }}
            onClick={onClose}
        >
            <div
                style={{
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)', width: '95%', maxWidth: '1000px',
                    maxHeight: '90vh', overflow: 'auto', position: 'relative',
                }}
                onClick={e => e.stopPropagation()}
            >
                {/* Loading State */}
                {loading && (
                    <div style={{ padding: '4rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                        <Loader2 size={32} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 1rem' }} />
                        <p>Loading run details...</p>
                    </div>
                )}

                {/* Error State */}
                {error && !loading && (
                    <div style={{ padding: '2rem' }}>
                        <div style={{
                            padding: '1rem', background: 'var(--danger-muted)',
                            border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: 'var(--radius)',
                            color: 'var(--danger)', fontSize: '0.875rem',
                        }}>
                            <AlertCircle size={16} style={{ display: 'inline', marginRight: '0.5rem', verticalAlign: 'text-bottom' }} />
                            {error}
                        </div>
                        <button
                            onClick={onClose}
                            style={{
                                marginTop: '1rem', padding: '0.5rem 1rem',
                                background: 'var(--background)', border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)', cursor: 'pointer',
                                color: 'var(--text-secondary)', fontSize: '0.875rem',
                            }}
                        >
                            Close
                        </button>
                    </div>
                )}

                {/* Main Content */}
                {data && !loading && (
                    <>
                        {/* Header */}
                        <div style={{
                            padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--border)',
                            display: 'flex', alignItems: 'center', gap: '1rem',
                            position: 'sticky', top: 0, background: 'var(--surface)', zIndex: 10,
                        }}>
                            <button
                                onClick={onClose}
                                style={{
                                    background: 'none', border: 'none', cursor: 'pointer',
                                    color: 'var(--text-secondary)', padding: '0.25rem',
                                    display: 'flex', alignItems: 'center',
                                }}
                            >
                                <X size={20} />
                            </button>
                            <div style={{ flex: 1 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                                    <h2 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0 }}>
                                        {data.spec_name}
                                    </h2>
                                    <span style={{
                                        display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                                        padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                                        fontWeight: 600,
                                        background: `${getStatusColor(data.status)}1a`,
                                        color: getStatusColor(data.status),
                                    }}>
                                        {data.status === 'running' && <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} />}
                                        {data.status.toUpperCase()}
                                    </span>
                                    {data.healing_attempt != null && data.healing_attempt > 0 && (
                                        <span style={{
                                            display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
                                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                                            fontWeight: 600, background: 'var(--warning-muted)', color: 'var(--warning)',
                                        }}>
                                            <Heart size={10} /> Healed ({data.healing_attempt} attempt{data.healing_attempt > 1 ? 's' : ''})
                                        </span>
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: '1rem', marginTop: '0.35rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                    {duration && (
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                            <Clock size={12} /> {duration}
                                        </span>
                                    )}
                                    {data.created_at && (
                                        <span>{timeAgo(data.created_at)}</span>
                                    )}
                                    <span style={{ fontFamily: 'monospace', fontSize: '0.7rem' }}>
                                        ID: {data.id.substring(0, 16)}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Body */}
                        <div style={{ padding: '1.5rem' }}>

                            {/* Error Message */}
                            {data.error_message && (
                                <div style={{
                                    padding: '0.75rem 1rem', marginBottom: '1.25rem',
                                    background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.2)',
                                    borderRadius: 'var(--radius)', fontSize: '0.8rem', color: 'var(--danger)',
                                }}>
                                    <AlertCircle size={14} style={{ display: 'inline', marginRight: '0.4rem', verticalAlign: 'text-bottom' }} />
                                    {data.error_message}
                                </div>
                            )}

                            {/* Test Results Summary */}
                            {data.test_results && data.test_results.summary && (
                                <div style={{
                                    marginBottom: '1.25rem', padding: '1rem',
                                    background: 'var(--background)', border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                }}>
                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <Activity size={16} /> Test Results
                                    </div>
                                    {(() => {
                                        const s = data.test_results!.summary;
                                        const total = s.total || 1;
                                        const passedPct = (s.passed / total) * 100;
                                        const failedPct = (s.failed / total) * 100;
                                        const skippedPct = (s.skipped / total) * 100;
                                        return (
                                            <>
                                                {/* Progress bar */}
                                                <div style={{
                                                    display: 'flex', height: '8px', borderRadius: '4px',
                                                    overflow: 'hidden', marginBottom: '0.5rem',
                                                    background: 'rgba(255,255,255,0.05)',
                                                }}>
                                                    {s.passed > 0 && (
                                                        <div style={{ width: `${passedPct}%`, background: 'var(--success)', transition: 'width 0.3s var(--ease-smooth)' }} />
                                                    )}
                                                    {s.failed > 0 && (
                                                        <div style={{ width: `${failedPct}%`, background: 'var(--danger)', transition: 'width 0.3s var(--ease-smooth)' }} />
                                                    )}
                                                    {s.skipped > 0 && (
                                                        <div style={{ width: `${skippedPct}%`, background: 'var(--text-tertiary)', transition: 'width 0.3s var(--ease-smooth)' }} />
                                                    )}
                                                </div>
                                                {/* Counts */}
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                                                    <span style={{ color: 'var(--success)', fontWeight: 600 }}>{s.passed} passed</span>
                                                    <span style={{ color: 'var(--danger)', fontWeight: 600 }}>{s.failed} failed</span>
                                                    <span style={{ color: 'var(--text-tertiary)', fontWeight: 600 }}>{s.skipped} skipped</span>
                                                    <span>of {s.total} total</span>
                                                </div>
                                            </>
                                        );
                                    })()}
                                </div>
                            )}

                            {/* Per-Test Breakdown */}
                            {data.test_results && data.test_results.tests && data.test_results.tests.length > 0 && (
                                <div style={{
                                    marginBottom: '1.25rem', background: 'var(--background)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                    overflow: 'hidden',
                                }}>
                                    <div style={{
                                        padding: '0.75rem 1rem', fontSize: '0.85rem', fontWeight: 600,
                                        borderBottom: '1px solid var(--border)',
                                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                                    }}>
                                        <Play size={16} /> Test Breakdown ({data.test_results.tests.length})
                                    </div>
                                    {data.test_results.tests.map((test: TestResultDetail, idx: number) => {
                                        const isExpanded = expandedTests.has(idx);
                                        const isFailed = test.status === 'failed' || test.status === 'timedOut';
                                        const testDuration = test.duration_ms >= 1000
                                            ? `${(test.duration_ms / 1000).toFixed(1)}s`
                                            : `${test.duration_ms}ms`;

                                        return (
                                            <div key={idx}>
                                                <div
                                                    style={{
                                                        display: 'flex', alignItems: 'center', gap: '0.75rem',
                                                        padding: '0.6rem 1rem',
                                                        borderBottom: '1px solid var(--border)',
                                                        cursor: isFailed ? 'pointer' : 'default',
                                                        transition: 'background 0.15s var(--ease-smooth)',
                                                    }}
                                                    onClick={() => isFailed && toggleTest(idx)}
                                                    onMouseEnter={e => isFailed && (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                                                    onMouseLeave={e => isFailed && (e.currentTarget.style.background = 'transparent')}
                                                >
                                                    {isFailed && (
                                                        <span style={{ color: 'var(--text-secondary)' }}>
                                                            {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                                        </span>
                                                    )}
                                                    {test.status === 'passed' && <CheckCircle size={14} style={{ color: 'var(--success)', flexShrink: 0 }} />}
                                                    {test.status === 'failed' && <AlertCircle size={14} style={{ color: 'var(--danger)', flexShrink: 0 }} />}
                                                    {test.status === 'skipped' && <Clock size={14} style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} />}
                                                    {test.status === 'timedOut' && <Clock size={14} style={{ color: 'var(--warning)', flexShrink: 0 }} />}
                                                    {test.status === 'flaky' && <AlertCircle size={14} style={{ color: 'var(--warning)', flexShrink: 0 }} />}
                                                    <span style={{
                                                        flex: 1, fontSize: '0.8rem', color: 'var(--text-primary)',
                                                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                    }}>
                                                        {test.title}
                                                    </span>
                                                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', flexShrink: 0 }}>
                                                        {testDuration}
                                                    </span>
                                                    {test.error?.category && (
                                                        <span style={{
                                                            padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                                            fontWeight: 600,
                                                            background: `${getCategoryColor(test.error.category)}1a`,
                                                            color: getCategoryColor(test.error.category),
                                                            flexShrink: 0,
                                                        }}>
                                                            {test.error.category}
                                                        </span>
                                                    )}
                                                </div>
                                                {/* Expanded error details */}
                                                {isExpanded && isFailed && test.error && (
                                                    <div style={{
                                                        padding: '0.75rem 1rem 0.75rem 2.5rem',
                                                        borderBottom: '1px solid var(--border)',
                                                        background: 'rgba(0,0,0,0.1)',
                                                    }}>
                                                        {/* Error message */}
                                                        <div style={{
                                                            padding: '0.5rem 0.75rem', marginBottom: '0.5rem',
                                                            background: 'rgba(239, 68, 68, 0.08)',
                                                            border: '1px solid rgba(239, 68, 68, 0.15)',
                                                            borderRadius: 'var(--radius)', fontSize: '0.75rem',
                                                            color: 'var(--danger)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                                        }}>
                                                            {test.error.message}
                                                        </div>
                                                        {/* Stack trace */}
                                                        {test.error.stack && (
                                                            <details style={{ marginTop: '0.4rem' }}>
                                                                <summary style={{
                                                                    cursor: 'pointer', fontSize: '0.7rem',
                                                                    color: 'var(--text-secondary)', userSelect: 'none',
                                                                }}>
                                                                    Stack Trace
                                                                </summary>
                                                                <pre style={{
                                                                    marginTop: '0.4rem', padding: '0.5rem 0.75rem',
                                                                    background: 'var(--background)', color: 'var(--text-secondary)',
                                                                    borderRadius: 'var(--radius)', fontSize: '0.65rem',
                                                                    fontFamily: 'monospace', overflow: 'auto',
                                                                    maxHeight: '200px', whiteSpace: 'pre-wrap',
                                                                    wordBreak: 'break-all', lineHeight: 1.4,
                                                                }}>
                                                                    {test.error.stack}
                                                                </pre>
                                                            </details>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            {/* Error Summary */}
                            {data.test_results && data.test_results.error_summary && Object.keys(data.test_results.error_summary).length > 0 && (
                                <div style={{
                                    marginBottom: '1.25rem', padding: '1rem',
                                    background: 'var(--background)', border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                }}>
                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                                        Error Categories
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {Object.entries(data.test_results.error_summary).map(([category, count]) => (
                                            <span key={category} style={{
                                                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                                                padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                                                fontWeight: 600,
                                                background: `${getCategoryColor(category)}1a`,
                                                color: getCategoryColor(category),
                                            }}>
                                                {category} ({count})
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Generated Code */}
                            {data.generated_code && (
                                <div style={{
                                    marginBottom: '1.25rem', background: 'var(--background)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                    overflow: 'hidden',
                                }}>
                                    <button
                                        onClick={() => setShowCode(!showCode)}
                                        style={{
                                            width: '100%', display: 'flex', alignItems: 'center', gap: '0.5rem',
                                            padding: '0.75rem 1rem', background: 'none', border: 'none',
                                            cursor: 'pointer', color: 'var(--text-primary)',
                                            fontSize: '0.85rem', fontWeight: 600, textAlign: 'left',
                                        }}
                                    >
                                        <Code size={16} />
                                        Generated Code
                                        {showCode ? <ChevronDown size={14} style={{ marginLeft: 'auto' }} /> : <ChevronRight size={14} style={{ marginLeft: 'auto' }} />}
                                    </button>
                                    {showCode && (
                                        <div style={{ height: '400px', borderTop: '1px solid var(--border)' }}>
                                            <CodeEditor
                                                value={data.generated_code}
                                                onChange={() => {}}
                                                language="typescript"
                                                readOnly
                                            />
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Healing Timeline */}
                            {data.healing_history && data.healing_history.length > 0 && (
                                <div style={{
                                    marginBottom: '1.25rem', padding: '1rem',
                                    background: 'var(--background)', border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                }}>
                                    <div style={{
                                        fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem',
                                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                                    }}>
                                        <Heart size={16} style={{ color: 'var(--warning)' }} /> Healing Timeline
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                        {data.healing_history.map((attempt: HealingAttempt, idx: number) => {
                                            const isSuccess = attempt.result === 'passed' || attempt.result === 'success';
                                            const borderColor = isSuccess ? 'var(--success)' : 'var(--danger)';
                                            return (
                                                <div key={idx} style={{
                                                    padding: '0.6rem 0.75rem',
                                                    background: `${borderColor}08`,
                                                    border: `1px solid ${borderColor}30`,
                                                    borderRadius: 'var(--radius)',
                                                    borderLeft: `3px solid ${borderColor}`,
                                                }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                                                        <span style={{
                                                            padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                                            fontWeight: 600, background: 'var(--primary-glow)', color: 'var(--primary)',
                                                        }}>
                                                            Attempt {attempt.attempt}
                                                        </span>
                                                        <span style={{
                                                            padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                                            fontWeight: 600,
                                                            background: isSuccess ? 'var(--success-muted)' : 'var(--danger-muted)',
                                                            color: isSuccess ? 'var(--success)' : 'var(--danger)',
                                                        }}>
                                                            {attempt.result}
                                                        </span>
                                                        {attempt.code_changed && (
                                                            <span style={{
                                                                padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                                                fontWeight: 600, background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)',
                                                            }}>
                                                                code changed
                                                            </span>
                                                        )}
                                                    </div>
                                                    {attempt.error_before && (
                                                        <div style={{
                                                            fontSize: '0.7rem', color: 'var(--text-secondary)',
                                                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                                            maxHeight: '60px', overflow: 'hidden',
                                                        }}>
                                                            {attempt.error_before}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* Execution Log */}
                            {data.execution_log && (
                                <div style={{
                                    marginBottom: '1.25rem', background: 'var(--background)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                    overflow: 'hidden',
                                }}>
                                    <button
                                        onClick={() => setShowLog(!showLog)}
                                        style={{
                                            width: '100%', display: 'flex', alignItems: 'center', gap: '0.5rem',
                                            padding: '0.75rem 1rem', background: 'none', border: 'none',
                                            cursor: 'pointer', color: 'var(--text-primary)',
                                            fontSize: '0.85rem', fontWeight: 600, textAlign: 'left',
                                        }}
                                    >
                                        <FileText size={16} />
                                        Execution Log
                                        {showLog ? <ChevronDown size={14} style={{ marginLeft: 'auto' }} /> : <ChevronRight size={14} style={{ marginLeft: 'auto' }} />}
                                    </button>
                                    {showLog && (
                                        <pre style={{
                                            margin: 0, padding: '1rem',
                                            background: 'var(--background)', color: 'var(--text-secondary)',
                                            fontSize: '0.7rem', fontFamily: 'monospace',
                                            maxHeight: '400px', overflow: 'auto',
                                            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                                            lineHeight: 1.5, borderTop: '1px solid var(--border)',
                                        }}>
                                            {data.execution_log}
                                        </pre>
                                    )}
                                </div>
                            )}

                            {/* Retry Button */}
                            {data.status === 'failed' && onRetry && (
                                <div style={{
                                    display: 'flex', justifyContent: 'center',
                                    paddingTop: '0.5rem', borderTop: '1px solid var(--border)',
                                    marginTop: '0.5rem',
                                }}>
                                    <button
                                        onClick={handleRetry}
                                        disabled={retrying}
                                        style={{
                                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                                            padding: '0.6rem 1.5rem', fontSize: '0.875rem', fontWeight: 600,
                                            background: 'var(--warning-muted)', color: 'var(--warning)',
                                            border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: 'var(--radius)',
                                            cursor: retrying ? 'wait' : 'pointer',
                                            opacity: retrying ? 0.6 : 1,
                                        }}
                                    >
                                        {retrying ? (
                                            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                                        ) : (
                                            <RefreshCw size={16} />
                                        )}
                                        {retrying ? 'Retrying...' : 'Retry This Run'}
                                    </button>
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
