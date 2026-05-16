import Link from 'next/link';
import { CheckCircle2, ExternalLink, Loader2, Play, RefreshCw, Send, X } from 'lucide-react';
import type { ReactNode } from 'react';
import type { QualityGate } from './types';
import { QualityGateStatusBadge } from './QualityGateStatusBadge';

interface QualityGateDetailDrawerProps {
    gate: QualityGate | null;
    loading?: boolean;
    actionLoading?: string;
    error?: string;
    onClose: () => void;
    onRefresh: () => void;
    onRerun: () => void;
    onPublishFeedback: () => void;
}

function formatDuration(seconds?: number): string {
    if (!seconds) return 'Unknown';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function DetailButton({
    children,
    onClick,
    disabled,
    variant = 'secondary',
}: {
    children: ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    variant?: 'primary' | 'secondary';
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.55rem 0.75rem',
                border: variant === 'primary' ? 'none' : '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                background: variant === 'primary' ? 'var(--primary)' : 'var(--background)',
                color: variant === 'primary' ? '#fff' : 'var(--text)',
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

export function QualityGateDetailDrawer({
    gate,
    loading = false,
    actionLoading,
    error,
    onClose,
    onRefresh,
    onRerun,
    onPublishFeedback,
}: QualityGateDetailDrawerProps) {
    if (!gate) return null;

    const batch = gate.quality_gate?.batch;
    const feedbackErrors = gate.feedback?.errors || gate.quality_gate?.feedback_errors || [];
    const feedbackCommentUrl = gate.feedback?.comment?.url || gate.quality_gate?.feedback_comment_url;
    const commitStatusState = gate.feedback?.commit_status?.state || gate.quality_gate?.last_feedback_state;
    const commitStatusUrl = gate.feedback?.commit_status?.url || gate.quality_gate?.commit_status_url;

    return (
        <div style={{
            position: 'fixed',
            inset: 0,
            zIndex: 60,
            pointerEvents: 'auto',
        }}>
            <button
                type="button"
                aria-label="Close quality gate details"
                onClick={onClose}
                style={{
                    position: 'absolute',
                    inset: 0,
                    border: 'none',
                    background: 'rgba(15, 23, 42, 0.46)',
                    cursor: 'default',
                }}
            />
            <aside style={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: 'min(760px, 100vw)',
                height: '100%',
                background: 'var(--surface)',
                borderLeft: '1px solid var(--border)',
                boxShadow: 'var(--shadow-xl)',
                display: 'flex',
                flexDirection: 'column',
            }}>
                <div style={{
                    padding: '1rem 1.25rem',
                    borderBottom: '1px solid var(--border)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: '1rem',
                    alignItems: 'flex-start',
                }}>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <h2 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 800 }}>
                                PR #{gate.pr_number}: {gate.title || 'Untitled'}
                            </h2>
                            <QualityGateStatusBadge state={gate.quality_gate?.state || 'unknown'} />
                        </div>
                        <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                            {gate.owner}/{gate.repo} · {gate.head_ref || 'head'} → {gate.base_ref || 'base'}
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
                    <DetailButton onClick={onRefresh} disabled={loading || !!actionLoading}>
                        {loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
                        Refresh
                    </DetailButton>
                    <DetailButton onClick={onRerun} disabled={!!actionLoading} variant="primary">
                        {actionLoading === 'rerun' ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
                        Rerun
                    </DetailButton>
                    <DetailButton onClick={onPublishFeedback} disabled={!!actionLoading}>
                        {actionLoading === 'feedback' ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
                        Publish Feedback
                    </DetailButton>
                    {gate.batch_id && (
                        <Link href={`/regression/batches/${gate.batch_id}`} style={{
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
                            Open Batch
                        </Link>
                    )}
                    <Link href={`/pr-advisor?analysis=${encodeURIComponent(gate.id)}`} style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        padding: '0.55rem 0.75rem',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        color: 'var(--text)',
                        background: 'var(--background)',
                        textDecoration: 'none',
                        fontWeight: 700,
                        fontSize: '0.82rem',
                    }}>
                        <ExternalLink size={15} />
                        Open PR Advisor
                    </Link>
                </div>

                <div style={{ overflow: 'auto', padding: '1rem 1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {error && (
                        <div style={{ padding: '0.7rem 0.8rem', border: '1px solid rgba(248, 113, 113, 0.25)', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }}>
                            {error}
                        </div>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(120px, 1fr))', gap: '0.75rem' }}>
                        {[
                            ['Changed files', gate.changed_files_count],
                            ['Selected', `${gate.selected_tests_count}/${gate.total_candidate_tests}`],
                            ['Skipped', gate.saved_tests_count ?? 0],
                            ['Est. time', formatDuration(gate.estimated_duration_seconds)],
                        ].map(([label, value]) => (
                            <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.75rem', background: 'var(--background)' }}>
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{label}</div>
                                <div style={{ marginTop: '0.25rem', fontSize: '1.05rem', fontWeight: 800 }}>{value}</div>
                            </div>
                        ))}
                    </div>

                    <section style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', padding: '0.9rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                            <strong>Gate Result</strong>
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>{gate.quality_gate?.description}</span>
                        </div>
                        {batch && (
                            <div style={{ marginTop: '0.75rem', display: 'grid', gridTemplateColumns: 'repeat(5, minmax(80px, 1fr))', gap: '0.5rem', fontSize: '0.8rem' }}>
                                {[
                                    ['Total', batch.total_tests],
                                    ['Passed', batch.passed],
                                    ['Failed', batch.failed],
                                    ['Running', batch.running],
                                    ['Queued', batch.queued],
                                ].map(([label, value]) => (
                                    <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.55rem' }}>
                                        <div style={{ color: 'var(--text-secondary)' }}>{label}</div>
                                        <div style={{ marginTop: '0.15rem', fontWeight: 800 }}>{value}</div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </section>

                    {gate.fallback_reason && (
                        <div style={{ border: '1px solid rgba(245, 158, 11, 0.25)', background: 'rgba(245, 158, 11, 0.08)', color: '#f59e0b', padding: '0.8rem', borderRadius: 'var(--radius)', fontSize: '0.86rem' }}>
                            {gate.fallback_reason}
                        </div>
                    )}

                    {(feedbackCommentUrl || commitStatusState || commitStatusUrl || feedbackErrors.length > 0) && (
                        <section style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', padding: '0.9rem' }}>
                            <strong>Published Feedback</strong>
                            <div style={{ marginTop: '0.6rem', display: 'flex', flexDirection: 'column', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
                                {feedbackCommentUrl && (
                                    <a href={feedbackCommentUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none', display: 'inline-flex', gap: '0.35rem', alignItems: 'center' }}>
                                        <CheckCircle2 size={14} /> Comment {gate.feedback?.comment?.action || 'published'}
                                    </a>
                                )}
                                {commitStatusUrl ? (
                                    <a href={commitStatusUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                                        Commit status: {commitStatusState || 'updated'}
                                    </a>
                                ) : commitStatusState ? (
                                    <span>Commit status: {commitStatusState}</span>
                                ) : null}
                                {feedbackErrors.map(item => <span key={item} style={{ color: 'var(--danger)' }}>{item}</span>)}
                            </div>
                        </section>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.15fr)', gap: '1rem' }}>
                        <section style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', overflow: 'hidden' }}>
                            <div style={{ padding: '0.8rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 750 }}>Changed Files</div>
                            <div style={{ maxHeight: 360, overflow: 'auto' }}>
                                {(gate.changed_files || []).length === 0 ? (
                                    <div style={{ padding: '0.9rem', color: 'var(--text-secondary)', fontSize: '0.84rem' }}>Load details to view changed files.</div>
                                ) : gate.changed_files?.map(file => (
                                    <div key={file.path} style={{ padding: '0.75rem 0.9rem', borderBottom: '1px solid var(--border)' }}>
                                        <code style={{ fontSize: '0.76rem', wordBreak: 'break-word' }}>{file.path}</code>
                                        <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                                            {file.area.replaceAll('_', ' ')} · +{file.additions} -{file.deletions}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>

                        <section style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', overflow: 'hidden' }}>
                            <div style={{ padding: '0.8rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 750 }}>Selected Tests</div>
                            <div style={{ maxHeight: 360, overflow: 'auto' }}>
                                {(gate.selected_tests || []).length === 0 ? (
                                    <div style={{ padding: '0.9rem', color: 'var(--text-secondary)', fontSize: '0.84rem' }}>Load details to view selected tests.</div>
                                ) : gate.selected_tests?.map(test => (
                                    <div key={`${test.spec_name}-${test.test_path || ''}`} style={{ padding: '0.85rem 0.9rem', borderBottom: '1px solid var(--border)' }}>
                                        <div style={{ fontWeight: 750, fontSize: '0.86rem', wordBreak: 'break-word' }}>{test.spec_name}</div>
                                        {test.test_path && <code style={{ display: 'block', marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.72rem', wordBreak: 'break-word' }}>{test.test_path}</code>}
                                        <div style={{ marginTop: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.78rem', lineHeight: 1.45 }}>{test.reason}</div>
                                    </div>
                                ))}
                            </div>
                        </section>
                    </div>
                </div>
            </aside>
        </div>
    );
}
