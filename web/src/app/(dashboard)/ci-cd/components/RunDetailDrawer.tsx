import { ExternalLink, Loader2, Play, RefreshCw, RotateCcw, ScrollText, Square, X } from 'lucide-react';
import type { ReactNode } from 'react';

export interface CiRun {
    id: string | number;
    provider: 'github' | 'gitlab';
    external_pipeline_id: string;
    external_project_id?: string;
    external_url?: string;
    ref?: string;
    status: string;
    triggered_from?: string;
    stages?: CiJob[];
    artifacts?: CiArtifact[];
    created_at?: string;
    started_at?: string;
    completed_at?: string;
    total_tests?: number;
    passed_tests?: number;
    failed_tests?: number;
    action_availability?: {
        can_open_details?: boolean;
        can_open_provider?: boolean;
        can_cancel?: boolean;
        can_rerun?: boolean;
        can_rerun_failed?: boolean;
        can_fetch_logs?: boolean;
        disabled_reason?: string | null;
    };
}

export interface CiJob {
    id?: string;
    name?: string;
    stage?: string;
    status?: string;
    conclusion?: string;
    html_url?: string;
    web_url?: string;
    started_at?: string;
    completed_at?: string;
    artifacts?: unknown[];
}

export interface CiArtifact {
    id?: string;
    name?: string;
    size_in_bytes?: number;
    expired?: boolean;
    archive_download_url?: string;
}

interface RunDetailDrawerProps {
    run: CiRun | null;
    jobs: CiJob[];
    artifacts: CiArtifact[];
    loading?: boolean;
    actionLoading?: string;
    error?: string;
    logs?: { type: string; url?: string; content?: string } | null;
    onClose: () => void;
    onRefresh: () => void;
    onCancel: () => void;
    onRerun: (failedOnly: boolean) => void;
    onLoadLogs: (jobId?: string) => void;
}

function DrawerButton({
    children,
    onClick,
    disabled,
    title,
    variant = 'secondary',
}: {
    children: ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    title?: string;
    variant?: 'primary' | 'danger' | 'secondary';
}) {
    const background = variant === 'primary' ? 'var(--primary)' : variant === 'danger' ? 'var(--danger)' : 'var(--background)';
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            title={title}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.55rem 0.75rem',
                border: variant === 'secondary' ? '1px solid var(--border)' : 'none',
                borderRadius: 'var(--radius)',
                background,
                color: variant === 'secondary' ? 'var(--text)' : '#fff',
                cursor: disabled ? 'default' : 'pointer',
                fontWeight: 700,
                fontSize: '0.82rem',
                opacity: disabled ? 0.65 : 1,
            }}
        >
            {children}
        </button>
    );
}

export function RunDetailDrawer({
    run,
    jobs,
    artifacts,
    loading = false,
    actionLoading,
    error,
    logs,
    onClose,
    onRefresh,
    onCancel,
    onRerun,
    onLoadLogs,
}: RunDetailDrawerProps) {
    if (!run) return null;

    const active = ['pending', 'running', 'queued', 'waiting', 'in_progress'].includes(run.status);
    const availability = run.action_availability;
    const unavailableReason = availability?.disabled_reason || undefined;
    const canRerun = availability?.can_rerun ?? true;
    const canRerunFailed = availability?.can_rerun_failed ?? run.provider === 'github';
    const canCancel = availability?.can_cancel ?? active;
    const canFetchLogs = availability?.can_fetch_logs ?? true;

    return (
        <div style={{ position: 'fixed', inset: 0, zIndex: 70, pointerEvents: 'auto' }}>
            <button
                type="button"
                aria-label="Close run details"
                onClick={onClose}
                style={{ position: 'absolute', inset: 0, border: 'none', background: 'rgba(15, 23, 42, 0.46)' }}
            />
            <aside style={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: 'min(820px, 100vw)',
                height: '100%',
                background: 'var(--surface)',
                borderLeft: '1px solid var(--border)',
                boxShadow: 'var(--shadow-xl)',
                display: 'flex',
                flexDirection: 'column',
            }}>
                <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                    <div style={{ minWidth: 0 }}>
                        <h2 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 800 }}>
                            {run.provider.toUpperCase()} #{run.external_pipeline_id}
                        </h2>
                        <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                            {run.ref || 'unknown ref'} · {run.status}
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        style={{
                            border: '1px solid var(--border)',
                            background: 'var(--background)',
                            color: 'var(--text-secondary)',
                            borderRadius: 'var(--radius)',
                            width: 34,
                            height: 34,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            cursor: 'pointer',
                            flexShrink: 0,
                        }}
                    >
                        <X size={16} />
                    </button>
                </div>

                <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                    <DrawerButton onClick={onRefresh} disabled={loading || !!actionLoading}>
                        {loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
                        Refresh
                    </DrawerButton>
                    <DrawerButton onClick={() => onRerun(false)} disabled={!!actionLoading || !canRerun} title={!canRerun ? unavailableReason : undefined} variant="primary">
                        {actionLoading === 'rerun' ? <Loader2 size={15} className="spin" /> : <RotateCcw size={15} />}
                        Rerun
                    </DrawerButton>
                    <DrawerButton onClick={() => onRerun(true)} disabled={!!actionLoading || !canRerunFailed} title={!canRerunFailed ? unavailableReason || 'Failed-only rerun is available for failed GitHub Actions runs.' : undefined} variant="primary">
                        {actionLoading === 'rerun-failed' ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
                        Failed Only
                    </DrawerButton>
                    <DrawerButton onClick={onCancel} disabled={!!actionLoading || !canCancel} title={!canCancel ? unavailableReason || 'Cancel is only available while a run is active.' : undefined} variant="danger">
                        {actionLoading === 'cancel' ? <Loader2 size={15} className="spin" /> : <Square size={15} />}
                        Cancel
                    </DrawerButton>
                    <DrawerButton onClick={() => onLoadLogs(jobs[0]?.id)} disabled={!!actionLoading || !canFetchLogs} title={!canFetchLogs ? unavailableReason : undefined}>
                        {actionLoading === 'logs' ? <Loader2 size={15} className="spin" /> : <ScrollText size={15} />}
                        Logs
                    </DrawerButton>
                    {run.external_url && (
                        <a href={run.external_url} target="_blank" rel="noopener noreferrer" style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.4rem',
                            padding: '0.55rem 0.75rem',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            color: 'var(--primary)',
                            background: 'var(--background)',
                            textDecoration: 'none',
                            fontWeight: 700,
                            fontSize: '0.82rem',
                        }}>
                            <ExternalLink size={15} />
                            Provider
                        </a>
                    )}
                </div>
                {availability?.disabled_reason && (
                    <div style={{ padding: '0.55rem 1.25rem', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        Some controls are disabled: {availability.disabled_reason}
                    </div>
                )}

                <div style={{ overflow: 'auto', padding: '1rem 1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {error && (
                        <div style={{ padding: '0.7rem 0.8rem', border: '1px solid rgba(248, 113, 113, 0.25)', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }}>
                            {error}
                        </div>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(120px, 1fr))', gap: '0.75rem' }}>
                        {[
                            ['Provider', run.provider],
                            ['Status', run.status],
                            ['Tests', run.total_tests ? `${run.passed_tests ?? 0}/${run.total_tests}` : '-'],
                            ['Origin', run.triggered_from || '-'],
                        ].map(([label, value]) => (
                            <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.75rem', background: 'var(--background)' }}>
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{label}</div>
                                <div style={{ marginTop: '0.25rem', fontSize: '0.95rem', fontWeight: 800, textTransform: label === 'Provider' ? 'uppercase' : undefined }}>{value}</div>
                            </div>
                        ))}
                    </div>

                    <section>
                        <h3 style={{ margin: '0 0 0.65rem', fontSize: '0.95rem' }}>Jobs</h3>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
                            {(jobs.length ? jobs : run.stages || []).map((job, index) => (
                                <div key={job.id || `${job.name}-${index}`} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', padding: '0.75rem', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ fontWeight: 750 }}>{job.name || job.stage || `Job ${index + 1}`}</div>
                                        <div style={{ marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{job.stage || job.status || job.conclusion || 'unknown'}</div>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexShrink: 0 }}>
                                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{job.status || job.conclusion || '-'}</span>
                                        {run.provider === 'gitlab' && job.id && (
                                            <button type="button" onClick={() => onLoadLogs(job.id)} style={{ border: 'none', background: 'transparent', color: 'var(--primary)', cursor: 'pointer', fontWeight: 700 }}>
                                                Logs
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))}
                            {(jobs.length === 0 && (run.stages || []).length === 0) && (
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Refresh to load job details.</div>
                            )}
                        </div>
                    </section>

                    <section>
                        <h3 style={{ margin: '0 0 0.65rem', fontSize: '0.95rem' }}>Artifacts</h3>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
                            {(artifacts.length ? artifacts : run.artifacts || []).map((artifact, index) => (
                                <div key={artifact.id || `${artifact.name}-${index}`} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', padding: '0.75rem', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                    <span style={{ fontWeight: 700 }}>{artifact.name || `Artifact ${index + 1}`}</span>
                                    <span style={{ color: artifact.expired ? 'var(--danger)' : 'var(--text-secondary)', fontSize: '0.78rem' }}>
                                        {artifact.expired ? 'expired' : artifact.size_in_bytes ? `${Math.round(artifact.size_in_bytes / 1024)} KB` : 'available'}
                                    </span>
                                </div>
                            ))}
                            {(artifacts.length === 0 && (run.artifacts || []).length === 0) && (
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No artifacts loaded.</div>
                            )}
                        </div>
                    </section>

                    {logs && (
                        <section>
                            <h3 style={{ margin: '0 0 0.65rem', fontSize: '0.95rem' }}>Logs</h3>
                            {logs.url ? (
                                <a href={logs.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)', fontWeight: 700 }}>
                                    Open provider log archive
                                </a>
                            ) : (
                                <pre style={{ margin: 0, padding: '0.85rem', maxHeight: 320, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                                    {logs.content || 'No log content available.'}
                                </pre>
                            )}
                        </section>
                    )}
                </div>
            </aside>
            <style jsx>{`
                .spin {
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
}
