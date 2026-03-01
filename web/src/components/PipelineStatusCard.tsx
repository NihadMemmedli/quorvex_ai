'use client';

import { ExternalLink, GitBranch, Clock, CheckCircle, XCircle, Loader2, AlertCircle, MinusCircle } from 'lucide-react';

interface Pipeline {
    provider: 'gitlab' | 'github';
    external_pipeline_id: string;
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

interface PipelineStatusCardProps {
    pipeline: Pipeline;
}

function getStatusColor(status: string): string {
    switch (status) {
        case 'success': case 'completed': return 'var(--success)';
        case 'failed': case 'failure': return 'var(--danger)';
        case 'running': case 'in_progress': return 'var(--primary)';
        case 'pending': case 'queued': case 'waiting': return 'var(--warning)';
        case 'cancelled': case 'canceled': case 'skipped': return 'var(--text-secondary)';
        default: return 'var(--text-secondary)';
    }
}

function getStatusIcon(status: string) {
    switch (status) {
        case 'success': case 'completed': return <CheckCircle size={16} />;
        case 'failed': case 'failure': return <XCircle size={16} />;
        case 'running': case 'in_progress': return <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />;
        case 'pending': case 'queued': case 'waiting': return <Clock size={16} />;
        case 'cancelled': case 'canceled': return <MinusCircle size={16} />;
        default: return <AlertCircle size={16} />;
    }
}

function formatDuration(startedAt?: string, completedAt?: string): string {
    if (!startedAt) return '-';
    const start = new Date(startedAt).getTime();
    const end = completedAt ? new Date(completedAt).getTime() : Date.now();
    const seconds = Math.floor((end - start) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const min = Math.floor(seconds / 60);
    const sec = seconds % 60;
    if (min < 60) return `${min}m ${sec}s`;
    const hrs = Math.floor(min / 60);
    return `${hrs}h ${min % 60}m`;
}

function getOriginLabel(triggeredFrom?: string): string | null {
    switch (triggeredFrom) {
        case 'sync': return 'synced';
        case 'dashboard': return 'triggered';
        case 'webhook': return 'webhook';
        case 'schedule': return 'scheduled';
        default: return null;
    }
}

export function PipelineStatusCard({ pipeline }: PipelineStatusCardProps) {
    const statusColor = getStatusColor(pipeline.status);
    const isGitLab = pipeline.provider === 'gitlab';
    const originLabel = getOriginLabel(pipeline.triggered_from);

    return (
        <div style={{
            padding: '1rem 1.25rem',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            display: 'flex',
            alignItems: 'center',
            gap: '1rem',
            transition: 'border-color 0.2s var(--ease-smooth), box-shadow 0.2s var(--ease-smooth)',
        }}>
            {/* Provider icon */}
            <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isGitLab ? 'rgba(252, 109, 38, 0.1)' : 'rgba(255, 255, 255, 0.1)',
                color: isGitLab ? '#fc6d26' : 'var(--text)',
                fontWeight: 700,
                fontSize: '0.75rem',
                flexShrink: 0,
            }}>
                {isGitLab ? 'GL' : 'GH'}
            </div>

            {/* Pipeline info */}
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                        #{pipeline.external_pipeline_id}
                    </span>
                    <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '999px',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: statusColor,
                        background: `color-mix(in srgb, ${statusColor} 12%, transparent)`,
                    }}>
                        {getStatusIcon(pipeline.status)}
                        {pipeline.status}
                    </span>
                    {originLabel && (
                        <span style={{
                            padding: '0.1rem 0.4rem',
                            borderRadius: '999px',
                            fontSize: '0.65rem',
                            fontWeight: 500,
                            color: 'var(--text-secondary)',
                            background: 'rgba(128, 128, 128, 0.1)',
                            border: '1px solid rgba(128, 128, 128, 0.15)',
                        }}>
                            {originLabel}
                        </span>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    {pipeline.ref && (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                            <GitBranch size={12} />
                            {pipeline.ref}
                        </span>
                    )}
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <Clock size={12} />
                        {formatDuration(pipeline.started_at, pipeline.completed_at)}
                    </span>
                    {pipeline.created_at && (
                        <span>{new Date(pipeline.created_at).toLocaleString()}</span>
                    )}
                </div>
            </div>

            {/* Test results */}
            {pipeline.total_tests != null && pipeline.total_tests > 0 && (
                <div style={{
                    textAlign: 'right',
                    fontSize: '0.8rem',
                    flexShrink: 0,
                }}>
                    <div style={{ fontWeight: 600 }}>
                        {pipeline.passed_tests ?? 0}/{pipeline.total_tests} passed
                    </div>
                    {(pipeline.failed_tests ?? 0) > 0 && (
                        <div style={{ color: 'var(--danger)' }}>
                            {pipeline.failed_tests} failed
                        </div>
                    )}
                </div>
            )}

            {/* External link */}
            {pipeline.external_url && (
                <a
                    href={pipeline.external_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                        color: 'var(--text-secondary)',
                        padding: '0.3rem',
                        borderRadius: 'var(--radius)',
                        display: 'flex',
                        flexShrink: 0,
                    }}
                    title="View in provider"
                >
                    <ExternalLink size={16} />
                </a>
            )}

            <style jsx>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
}
