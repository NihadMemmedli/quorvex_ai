'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyleCompact, inputStyle, btnPrimary, btnSecondary, labelStyle } from '@/lib/styles';
import { toast } from 'sonner';
import { EmptyState } from '@/components/ui/empty-state';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusBadge } from '@/components/shared';
import {
    Server, FileText, StopCircle, RotateCcw,
    History as HistoryIcon, Play, Loader2, Eye,
    FlaskConical, Clock, ChevronRight
} from 'lucide-react';
import { usePolling } from '@/hooks/usePolling';
import { timeAgo } from '@/lib/formatting';
import type { Provider, Spec, Run } from './types';

interface RunTabProps {
    projectId: string;
}

export default function RunTab({ projectId }: RunTabProps) {
    const [providers, setProviders] = useState<Provider[]>([]);
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [selectedSpec, setSelectedSpec] = useState('');
    const [selectedProvider, setSelectedProvider] = useState('');
    const [running, setRunning] = useState(false);
    const [jobId, setJobId] = useState<string | null>(null);
    const [progress, setProgress] = useState<any>(null);

    // New state
    const [recentRuns, setRecentRuns] = useState<Run[]>([]);
    const [recentLoading, setRecentLoading] = useState(true);
    const [startTime, setStartTime] = useState<number | null>(null);
    const [elapsed, setElapsed] = useState(0);
    const [highlightMissing, setHighlightMissing] = useState(false);

    const runButtonRef = useRef<HTMLButtonElement>(null);
    const statusRef = useRef<HTMLDivElement>(null);

    // Provider name lookup
    const providerMap = useCallback((id: string) => {
        const p = providers.find(pr => pr.id === id);
        return p ? p.name : id;
    }, [providers]);

    // Fetch providers + specs
    useEffect(() => {
        fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`).then(r => r.json()).then(setProviders).catch(() => {});
        fetch(`${API_BASE}/llm-testing/specs?project_id=${projectId}`).then(r => r.json()).then(setSpecs).catch(() => {});
    }, [projectId]);

    // Fetch recent runs
    const fetchRecentRuns = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/runs?project_id=${projectId}&limit=5`);
            if (res.ok) {
                const data = await res.json();
                setRecentRuns(data.slice(0, 5));
            }
        } catch { /* ignore */ }
        setRecentLoading(false);
    }, [projectId]);

    useEffect(() => {
        fetchRecentRuns();
    }, [fetchRecentRuns]);

    // Elapsed time counter
    useEffect(() => {
        if (!running || !startTime) {
            setElapsed(0);
            return;
        }
        const timer = setInterval(() => {
            setElapsed(Math.floor((Date.now() - startTime) / 1000));
        }, 1000);
        return () => clearInterval(timer);
    }, [running, startTime]);

    // Poll for run job progress
    const runPollFn = useCallback(async () => {
        if (!jobId) return;
        const jr = await fetch(`${API_BASE}/llm-testing/jobs/${jobId}`);
        if (jr.ok) {
            const job = await jr.json();
            setProgress(job);
            if (job.status === 'completed' || job.status === 'failed') {
                setJobId(null);
                setRunning(false);
                setStartTime(null);
                if (job.status === 'completed') toast.success('Run completed');
                if (job.status === 'failed') toast.error(job.error || 'Run failed');
                fetchRecentRuns();
            }
        }
    }, [jobId, fetchRecentRuns]);

    const { stop: stopRunPoll } = usePolling(runPollFn, {
        interval: 1500,
        enabled: !!jobId,
    });

    useEffect(() => {
        if (!jobId) stopRunPoll();
    }, [jobId, stopRunPoll]);

    const startRun = useCallback(async () => {
        if (!selectedSpec || !selectedProvider) {
            setHighlightMissing(true);
            setTimeout(() => setHighlightMissing(false), 1000);
            return;
        }
        setRunning(true);
        setProgress(null);
        setStartTime(Date.now());
        try {
            const res = await fetch(`${API_BASE}/llm-testing/run`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_name: selectedSpec, provider_id: selectedProvider, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setJobId(data.job_id);
                toast.success('Run started');
            } else {
                toast.error('Failed to start run');
                setRunning(false);
                setStartTime(null);
            }
        } catch {
            toast.error('Failed to start run');
            setRunning(false);
            setStartTime(null);
        }
    }, [selectedSpec, selectedProvider, projectId]);

    const cancelRun = useCallback(() => {
        stopRunPoll();
        setRunning(false);
        setJobId(null);
        setProgress(null);
        setStartTime(null);
        toast.info('Run cancelled');
    }, [stopRunPoll]);

    const resetForm = useCallback(() => {
        setProgress(null);
        setSelectedSpec('');
        setSelectedProvider('');
        setStartTime(null);
        setTimeout(() => runButtonRef.current?.focus(), 100);
    }, []);

    const pct = progress && progress.progress_total > 0
        ? Math.round((progress.progress_current / progress.progress_total) * 100) : 0;

    const passed = progress?.passed || 0;
    const failed = progress?.failed || 0;
    const total = passed + failed;
    const passPercentage = total > 0 ? Math.round((passed / total) * 100) : 0;

    const formatElapsed = (s: number) => {
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60);
        const sec = s % 60;
        return `${m}m ${sec}s`;
    };

    const passRateColor = (rate: number) =>
        rate >= 80 ? 'var(--success)' : rate >= 50 ? 'var(--warning)' : 'var(--danger)';

    const completionBorderColor = progress?.status === 'completed'
        ? (passPercentage >= 50 ? 'var(--success)' : 'var(--danger)')
        : progress?.status === 'failed'
            ? 'var(--danger)'
            : 'var(--primary)';

    // Load recent run config
    const loadRunConfig = (run: Run) => {
        setSelectedSpec(run.spec_name);
        setSelectedProvider(run.provider_id);
        toast.info('Configuration loaded from recent run');
    };

    // Empty state checks
    if (providers.length === 0 && !running) {
        return (
            <div>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>Run Test Suite</h2>
                <EmptyState
                    icon={<Server size={32} />}
                    title="No providers configured"
                    description="Add an LLM provider in the Providers tab before running tests."
                />
            </div>
        );
    }
    if (specs.length === 0 && !running) {
        return (
            <div>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>Run Test Suite</h2>
                <EmptyState
                    icon={<FileText size={32} />}
                    title="No test specs found"
                    description="Create a test spec in the Specs tab before running tests."
                />
            </div>
        );
    }

    return (
        <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>Run Test Suite</h2>

            {/* Accessibility: status announcements */}
            <div ref={statusRef} aria-live="polite" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>
                {running && progress && `${progress.progress_current} of ${progress.progress_total} completed`}
                {!running && progress?.status === 'completed' && `Run completed: ${passed} of ${total} passed`}
                {!running && progress?.status === 'failed' && 'Run failed'}
            </div>

            {/* Section 1: Configuration Panel */}
            <div className="card-elevated animate-in stagger-1" style={{ padding: '1rem', marginBottom: '1rem' }}>
                <div style={{
                    display: 'flex',
                    gap: '1rem',
                    alignItems: 'flex-end',
                    flexWrap: 'wrap',
                }}>
                    <div style={{ flex: '1 1 200px' }}>
                        <label htmlFor="run-spec-select" style={labelStyle}>
                            Test Spec ({specs.length} available)
                        </label>
                        <select
                            id="run-spec-select"
                            value={selectedSpec}
                            onChange={e => setSelectedSpec(e.target.value)}
                            disabled={running}
                            style={{
                                ...inputStyle,
                                ...(running ? { opacity: 0.5, cursor: 'not-allowed' } : {}),
                                ...(highlightMissing && !selectedSpec ? {
                                    borderColor: 'var(--danger)',
                                    boxShadow: '0 0 0 1px var(--danger)',
                                } : {}),
                                transition: 'all 0.3s var(--ease-smooth)',
                            }}
                        >
                            <option value="">Select a spec...</option>
                            {specs.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                        </select>
                    </div>
                    <div style={{ flex: '1 1 200px' }}>
                        <label htmlFor="run-provider-select" style={labelStyle}>
                            Provider ({providers.length} configured)
                        </label>
                        <select
                            id="run-provider-select"
                            value={selectedProvider}
                            onChange={e => setSelectedProvider(e.target.value)}
                            disabled={running}
                            style={{
                                ...inputStyle,
                                ...(running ? { opacity: 0.5, cursor: 'not-allowed' } : {}),
                                ...(highlightMissing && !selectedProvider ? {
                                    borderColor: 'var(--danger)',
                                    boxShadow: '0 0 0 1px var(--danger)',
                                } : {}),
                                transition: 'all 0.3s var(--ease-smooth)',
                            }}
                        >
                            <option value="">Select a provider...</option>
                            {providers.map(p => <option key={p.id} value={p.id}>{p.name} ({p.model_id})</option>)}
                        </select>
                    </div>
                    <div style={{ flexShrink: 0 }}>
                        <button
                            ref={runButtonRef}
                            onClick={startRun}
                            disabled={running || !selectedSpec || !selectedProvider}
                            aria-busy={running}
                            aria-disabled={running || !selectedSpec || !selectedProvider}
                            style={{
                                ...btnPrimary,
                                ...(running || !selectedSpec || !selectedProvider ? {
                                    opacity: 0.5, cursor: 'not-allowed', pointerEvents: 'none' as const,
                                } : {}),
                            }}
                        >
                            {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                            {running ? 'Running...' : 'Run Suite'}
                        </button>
                    </div>
                </div>
            </div>

            {/* Section 2: Live Execution Area */}
            {(running || progress) && (
                <div
                    className="card-elevated animate-in stagger-2"
                    style={{
                        padding: '1rem',
                        marginBottom: '1rem',
                        borderLeft: `3px solid ${running ? 'var(--primary)' : completionBorderColor}`,
                    }}
                >
                    {/* Header row */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            {running && <Loader2 size={16} className="animate-spin" style={{ color: 'var(--primary)' }} />}
                            <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                                {running ? 'Running...' : progress?.status === 'completed' ? 'Completed' : progress?.status === 'failed' ? 'Failed' : 'Results'}
                            </span>
                            {(running || progress?.status !== 'completed') && elapsed > 0 && (
                                <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    <Clock size={12} /> {formatElapsed(elapsed)}
                                </span>
                            )}
                        </div>
                        {running && (
                            <button
                                onClick={cancelRun}
                                style={{ ...btnSecondary, color: 'var(--danger)', borderColor: 'var(--danger)', padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}
                            >
                                <StopCircle size={14} /> Cancel
                            </button>
                        )}
                    </div>

                    {/* Progress bar */}
                    {progress && progress.progress_total > 0 && (
                        <div style={{ marginBottom: '0.5rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                <span>{progress.progress_current}/{progress.progress_total}</span>
                                <span>{pct}%</span>
                            </div>
                            <Progress value={pct} className="h-2" aria-label="Test execution progress" />
                        </div>
                    )}

                    {/* Stats row */}
                    {progress && (
                        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.85rem', marginTop: '0.5rem' }}>
                            <span style={{ color: 'var(--success)', fontWeight: 500 }}>Passed: {passed}</span>
                            <span style={{ color: 'var(--danger)', fontWeight: 500 }}>Failed: {failed}</span>
                            {running && (
                                <span style={{ color: 'var(--text-secondary)' }}>
                                    Current: {progress.progress_current}/{progress.progress_total}
                                </span>
                            )}
                        </div>
                    )}

                    {/* Error message */}
                    {progress?.error && (
                        <div style={{
                            marginTop: '0.75rem',
                            padding: '0.5rem 0.75rem',
                            background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
                            border: '1px solid var(--danger)',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.85rem',
                            color: 'var(--danger)',
                        }}>
                            {progress.error}
                        </div>
                    )}

                    {/* Post-completion summary */}
                    {!running && progress?.status === 'completed' && (
                        <div style={{
                            marginTop: '0.75rem',
                            padding: '0.75rem',
                            background: 'var(--background-raised)',
                            borderRadius: 'var(--radius)',
                            border: '1px solid var(--border-subtle)',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                                <span style={{
                                    fontSize: '1.5rem',
                                    fontWeight: 700,
                                    color: passRateColor(passPercentage),
                                }}>
                                    {passPercentage}%
                                </span>
                                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    {passed}/{total} passed
                                    {elapsed > 0 && ` in ${formatElapsed(elapsed)}`}
                                </span>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button onClick={resetForm} style={btnSecondary}>
                                    <RotateCcw size={14} /> Run Again
                                </button>
                                <button
                                    onClick={() => toast.info('Check the History tab for detailed results')}
                                    style={btnSecondary}
                                >
                                    <Eye size={14} /> View Details
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Post-failure CTA */}
                    {!running && progress?.status === 'failed' && !progress?.error && (
                        <div style={{ marginTop: '0.75rem' }}>
                            <button onClick={resetForm} style={btnSecondary}>
                                <RotateCcw size={14} /> Try Again
                            </button>
                        </div>
                    )}
                    {!running && progress?.status === 'failed' && progress?.error && (
                        <div style={{ marginTop: '0.5rem' }}>
                            <button onClick={resetForm} style={btnSecondary}>
                                <RotateCcw size={14} /> Try Again
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Section 3: Recent Runs Quick-View */}
            <div className="card-elevated animate-in stagger-2" style={{ padding: '1rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.95rem', fontWeight: 600, margin: 0 }}>
                        <HistoryIcon size={16} style={{ color: 'var(--text-secondary)' }} />
                        Recent Runs
                    </h3>
                    <span style={{ color: 'var(--primary)', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        View All <ChevronRight size={14} />
                    </span>
                </div>

                {recentLoading ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {Array.from({ length: 3 }).map((_, i) => (
                            <Skeleton key={i} className={`stagger-${i + 1}`} style={{ height: 44, width: '100%' }} />
                        ))}
                    </div>
                ) : recentRuns.length === 0 ? (
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0', textAlign: 'center' }}>
                        No runs yet. Configure and run your first test above.
                    </p>
                ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto auto', columnGap: '0.75rem' }}>
                        {recentRuns.map((run, i) => (
                            <div
                                key={run.id}
                                role="button"
                                tabIndex={0}
                                onClick={() => loadRunConfig(run)}
                                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); loadRunConfig(run); } }}
                                style={{
                                    display: 'grid',
                                    gridColumn: '1 / -1',
                                    gridTemplateColumns: 'subgrid',
                                    alignItems: 'center',
                                    padding: '0.5rem 0.25rem',
                                    cursor: 'pointer',
                                    borderBottom: i < recentRuns.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                                    borderRadius: 'var(--radius-sm)',
                                    transition: 'background 0.2s var(--ease-smooth)',
                                }}
                                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--surface-hover)'; }}
                                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                            >
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {run.spec_name}
                                </span>
                                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {providerMap(run.provider_id)}
                                </span>
                                <span style={{
                                    fontSize: '0.85rem',
                                    fontWeight: 600,
                                    color: passRateColor(run.pass_rate),
                                    whiteSpace: 'nowrap',
                                }}>
                                    {run.pass_rate}%
                                </span>
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                    {timeAgo(run.created_at)}
                                </span>
                                <StatusBadge status={run.status} />
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Section 4: Idle State - only when no recent runs, not running, and no progress */}
            {!running && !progress && recentRuns.length === 0 && !recentLoading && (
                <div style={{ marginTop: '1rem' }}>
                    <EmptyState
                        icon={<FlaskConical size={32} />}
                        title="Ready to test"
                        description="Select a spec and provider above to start your first run."
                    />
                </div>
            )}
        </div>
    );
}
