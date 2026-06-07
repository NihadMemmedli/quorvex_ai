'use client';

import Link from 'next/link';
import { useState } from 'react';
import {
    AlertTriangle,
    ArrowRight,
    Bot,
    CheckCircle2,
    Clock,
    GitBranch,
    Loader2,
    PlayCircle,
    ShieldAlert,
    Sparkles,
    XCircle,
} from 'lucide-react';
import { PageHeader } from '@/components/ui/page-header';
import { PageLayout } from '@/components/ui/page-layout';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useCommandCenterData, type AgentQueueTaskSummary, type AutoPilotSessionSummary } from '@/hooks/useCommandCenterData';
import { API_BASE } from '@/lib/api';
import { useWorkflowProgress } from '@/hooks/useWorkflowProgress';

const statusMeta: Record<string, { label: string; color: string; bg: string; icon: typeof Clock }> = {
    pending: { label: 'Pending', color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.12)', icon: Clock },
    running: { label: 'Running', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.12)', icon: Loader2 },
    awaiting_input: { label: 'Needs review', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.13)', icon: AlertTriangle },
    paused: { label: 'Paused', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.13)', icon: AlertTriangle },
    completed: { label: 'Completed', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)', icon: CheckCircle2 },
    failed: { label: 'Failed', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)', icon: XCircle },
    cancelled: { label: 'Cancelled', color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.12)', icon: XCircle },
};

function formatPhase(phase: string | null | undefined): string {
    if (!phase) return 'Queued';
    return phase
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase());
}

function formatAge(iso: string | null | undefined): string {
    if (!iso) return 'Not started';
    const rawTimestamp = new Date(iso).getTime();
    const timestamp = Number.isFinite(rawTimestamp) ? rawTimestamp : new Date(`${iso}Z`).getTime();
    if (!Number.isFinite(timestamp)) return iso;
    const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function compactUrl(session: AutoPilotSessionSummary): string {
    const first = session.entry_urls?.[0];
    if (!first) return session.id;
    try {
        const url = new URL(first);
        return url.hostname + (url.pathname === '/' ? '' : url.pathname);
    } catch {
        return first.replace(/^https?:\/\//, '');
    }
}

function compactTaskId(id: string): string {
    return id.length > 18 ? `${id.slice(0, 18)}...` : id;
}

function taskDisplayLabel(task: AgentQueueTaskSummary): string {
    return (
        task.progress?.activity_label ||
        task.progress?.message ||
        task.operation_type ||
        task.agent_type ||
        compactTaskId(task.id)
    );
}

function taskDetail(task: AgentQueueTaskSummary): string {
    const parts = [
        task.progress?.phase || task.progress?.status || task.status || 'running',
        task.progress?.last_tool_label || task.progress?.last_tool,
        task.started_at ? formatAge(task.started_at) : null,
    ].filter(Boolean);
    return parts.join(' · ');
}

function qualityTeamLabel(task: AgentQueueTaskSummary): string {
    const text = [
        task.operation_type,
        task.agent_type,
        task.progress?.activity_label,
        task.progress?.phase,
        task.progress?.message,
    ].filter(Boolean).join(' ').toLowerCase();

    if (/coverage|rtm|requirement/.test(text)) return 'Coverage';
    if (/regression|test|run|browser|playwright/.test(text)) return 'Regression';
    if (/explor|discover|crawl|flow/.test(text)) return 'Exploration';
    if (/triage|heal|failure|jira|bug/.test(text)) return 'Triage';
    return 'QA automation';
}

function PrimaryButton({ href, children, tone = 'primary' }: { href: string; children: React.ReactNode; tone?: 'primary' | 'warning' | 'danger' }) {
    const color = tone === 'danger' ? '#ef4444' : tone === 'warning' ? '#f59e0b' : 'var(--primary)';
    return (
        <Link
            href={href}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                minHeight: 40,
                padding: '0.6rem 0.95rem',
                borderRadius: '8px',
                background: color,
                color: 'white',
                textDecoration: 'none',
                fontSize: '0.88rem',
                fontWeight: 700,
                boxShadow: `0 12px 30px ${color}26`,
                whiteSpace: 'nowrap',
            }}
        >
            {children}
        </Link>
    );
}

function StatusBadge({ status }: { status: string }) {
    const meta = statusMeta[status] || statusMeta.pending;
    const Icon = meta.icon;
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.35rem',
            minHeight: 26,
            padding: '0.25rem 0.55rem',
            borderRadius: '999px',
            background: meta.bg,
            color: meta.color,
            fontSize: '0.72rem',
            fontWeight: 700,
            whiteSpace: 'nowrap',
        }}>
            <Icon size={13} style={{ animation: status === 'running' ? 'spin 1s linear infinite' : undefined }} />
            {meta.label}
        </span>
    );
}

function CompactMetricItem({ label, value, detail, tone }: { label: string; value: string | number; detail: string; tone?: string }) {
    return (
        <div style={{
            minWidth: 0,
            padding: '0.85rem',
            borderRadius: '8px',
            background: 'rgba(255, 255, 255, 0.025)',
            border: '1px solid var(--border-subtle)',
        }}>
            <div style={{ color: 'var(--text-tertiary)', fontSize: '0.7rem', fontWeight: 750, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {label}
            </div>
            <div style={{ color: tone || 'var(--text)', fontSize: '1.25rem', lineHeight: 1.15, fontWeight: 850, marginTop: '0.25rem' }}>
                {value}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem', marginTop: '0.25rem', lineHeight: 1.35 }}>
                {detail}
            </div>
        </div>
    );
}

function EmptyState({ icon, title, detail, links }: { icon: React.ReactNode; title: string; detail: string; links?: React.ReactNode }) {
    return (
        <div style={{ padding: '2.25rem 1.25rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
            <div style={{ color: '#22c55e', marginBottom: '0.65rem' }}>{icon}</div>
            <div style={{ fontWeight: 750, color: 'var(--text)', marginBottom: '0.25rem' }}>{title}</div>
            <div style={{ fontSize: '0.85rem', lineHeight: 1.45 }}>{detail}</div>
            {links && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.8rem', flexWrap: 'wrap', marginTop: '0.85rem', fontSize: '0.8rem', fontWeight: 700 }}>
                    {links}
                </div>
            )}
        </div>
    );
}

function TopRiskRow({
    href,
    icon,
    title,
    detail,
    tone = '#f59e0b',
    action,
}: {
    href?: string;
    icon: React.ReactNode;
    title: string;
    detail: React.ReactNode;
    tone?: string;
    action?: React.ReactNode;
}) {
    const content = (
        <>
            <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: tone, fontSize: '0.82rem', fontWeight: 800 }}>
                    {icon}
                    {title}
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '0.3rem', lineHeight: 1.45 }}>
                    {detail}
                </div>
            </div>
            {action || (href ? <ArrowRight size={16} /> : null)}
        </>
    );

    const style = {
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) auto',
        alignItems: 'center',
        gap: '0.75rem',
        padding: '0.95rem 1rem',
        borderBottom: '1px solid var(--border-subtle)',
        color: 'inherit',
        textDecoration: 'none',
    };

    if (href) {
        return (
            <Link href={href} className="command-action-row" style={style}>
                {content}
            </Link>
        );
    }

    return <div className="command-action-row" style={style}>{content}</div>;
}

function SessionRow({ session, compact = false }: { session: AutoPilotSessionSummary; compact?: boolean }) {
    const failed = session.status === 'failed';
    const needsInput = session.status === 'awaiting_input';
    const href = `/autopilot?sessionId=${encodeURIComponent(session.id)}`;

    return (
        <Link
            href={href}
            className="command-session-row"
            style={{
                display: 'grid',
                gridTemplateColumns: compact ? 'minmax(0, 1fr) auto' : 'minmax(0, 1fr) auto',
                gap: '0.9rem',
                padding: '0.95rem 1rem',
                borderBottom: '1px solid var(--border-subtle)',
                color: 'inherit',
                textDecoration: 'none',
                background: needsInput ? 'rgba(245, 158, 11, 0.035)' : failed ? 'rgba(239, 68, 68, 0.035)' : 'transparent',
            }}
        >
            <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', minWidth: 0 }}>
                    <div style={{ fontSize: '0.9rem', fontWeight: 750, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {compactUrl(session)}
                    </div>
                    <StatusBadge status={session.status} />
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.35rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {formatPhase(session.current_phase)} · {formatAge(session.started_at || session.created_at)}
                    {session.error_message ? ` · ${session.error_message}` : ''}
                </div>
                {!compact && (
                    <div style={{
                        height: 6,
                        borderRadius: 999,
                        background: 'var(--surface-hover)',
                        overflow: 'hidden',
                        marginTop: '0.75rem',
                    }}>
                        <div style={{
                            width: `${session.overall_progress}%`,
                            height: '100%',
                            borderRadius: 999,
                            background: failed ? '#ef4444' : needsInput ? '#f59e0b' : '#3b82f6',
                        }} />
                    </div>
                )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', color: 'var(--text-secondary)', fontSize: '0.82rem', fontWeight: 650 }}>
                {Math.round(session.overall_progress)}%
                <ArrowRight size={15} />
            </div>
        </Link>
    );
}

function AgentTaskRow({ task }: { task: AgentQueueTaskSummary }) {
    const isOrphaned = task.orphaned || task.owner_terminal || task.heartbeat_alive === false;
    const teamLabel = qualityTeamLabel(task);
    return (
        <div
            className="command-agent-row"
            style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) auto',
                gap: '0.9rem',
                padding: '0.95rem 1rem',
                borderTop: '1px solid var(--border-subtle)',
                color: 'inherit',
                background: 'rgba(59, 130, 246, 0.035)',
            }}
        >
            <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', minWidth: 0 }}>
                    <div style={{ fontSize: '0.9rem', fontWeight: 750, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {taskDisplayLabel(task)}
                    </div>
                    <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        minHeight: 24,
                        padding: '0.2rem 0.5rem',
                        borderRadius: '999px',
                        background: isOrphaned ? 'rgba(239, 68, 68, 0.12)' : 'rgba(59, 130, 246, 0.12)',
                        color: isOrphaned ? '#ef4444' : '#3b82f6',
                        fontSize: '0.7rem',
                        fontWeight: 750,
                        whiteSpace: 'nowrap',
                    }}>
                        {isOrphaned ? 'Orphaned task' : teamLabel}
                    </span>
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.35rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {taskDetail(task)}
                </div>
            </div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: '0.74rem', fontWeight: 700, alignSelf: 'center', whiteSpace: 'nowrap' }}>
                {compactTaskId(task.id)}
            </div>
        </div>
    );
}

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
    return (
        <section className="card-elevated" style={{ overflow: 'hidden' }}>
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '1rem',
                padding: '1rem 1.1rem',
                borderBottom: '1px solid var(--border-subtle)',
            }}>
                <h2 style={{ fontSize: '0.95rem', fontWeight: 800, margin: 0 }}>{title}</h2>
                {action}
            </div>
            {children}
        </section>
    );
}

export default function Home() {
    const [isCleaningOrphans, setIsCleaningOrphans] = useState(false);
    const [cleanupError, setCleanupError] = useState<string | null>(null);
    const {
        dashboard,
        sessions,
        queue,
        loading,
        error,
        activeSessions,
        failedSessions,
        completedSessions,
        pendingQuestions,
        awaitingInput,
        hasAnySessions,
        reload,
    } = useCommandCenterData();
    const { progress: workflowProgress } = useWorkflowProgress();

    const passRate = Math.round(dashboard.pass_rate ?? dashboard.success_rate ?? 0);
    const rtmCoverage = workflowProgress?.rtmCoverage ?? 0;
    const totalFailures = sessions.reduce((sum, session) => sum + (session.total_tests_failed || 0), 0);
    const runningTasks = queue?.running_tasks ?? [];
    const activeSessionIds = new Set(activeSessions.map(session => session.id));
    const linkedTaskIds = new Set(
        activeSessions
            .map(session => session.config?.live_browser?.agent_task_id)
            .filter((id): id is string => Boolean(id))
    );
    const backgroundAgentTasks = runningTasks.filter(task => {
        if (task.orphaned || task.owner_terminal || task.heartbeat_alive === false) return true;
        if (linkedTaskIds.has(task.id)) return false;
        if (task.owner_type === 'autopilot' && task.owner_id && activeSessionIds.has(task.owner_id)) return false;
        return true;
    });
    const unlistedBackgroundTaskCount = Math.max(0, (queue?.active ?? 0) - linkedTaskIds.size - backgroundAgentTasks.length);
    const backgroundAgentTaskCount = backgroundAgentTasks.length + unlistedBackgroundTaskCount;
    const orphanedTaskCount = queue?.orphaned_tasks ?? runningTasks.filter(task => task.orphaned).length;
    const queueSourceLabel = queue?.mode === 'redis' ? 'Redis workers' : queue?.mode === 'temporal' ? 'Temporal activities' : queue?.mode === 'browser_pool' ? 'Browser pool' : 'Worker pool';
    const temporalWorkflowPollers = queue?.temporal?.worker_pollers?.workflow ?? queue?.temporal?.task_queue_status?.workflow_pollers ?? 0;
    const temporalActivityPollers = queue?.temporal?.worker_pollers?.activity ?? queue?.temporal?.task_queue_status?.activity_pollers ?? 0;
    const workersAlive = queue?.mode === 'temporal'
        ? Math.min(Number(temporalWorkflowPollers), Number(temporalActivityPollers))
        : queue?.workers_alive ?? 0;
    const staleRunningCount = queue?.stale_running ?? 0;
    const queueUnavailable = queue?.mode === 'temporal' && ((queue?.active ?? 0) > 0 || (queue?.queued ?? 0) > 0) && workersAlive === 0;
    const queueDegraded = orphanedTaskCount > 0 || staleRunningCount > 0 || queueUnavailable;
    const hasCoverageData = rtmCoverage > 0 || (workflowProgress?.requirements ?? 0) > 0;
    const coverageGap = hasCoverageData && rtmCoverage < 60;
    const hasRecentQualityData = dashboard.total_runs > 0 || hasAnySessions;
    const cleanOrphanedTasks = async () => {
        if (isCleaningOrphans) return;

        setIsCleaningOrphans(true);
        setCleanupError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/api/agents/queue-clean-orphans`, {
                method: 'POST',
            });
            const result = await response.json().catch(() => ({}));

            if (!response.ok || result.status === 'error') {
                throw new Error(result.message || 'Failed to clean orphaned tasks');
            }

            await reload({ silent: true });
        } catch (err) {
            setCleanupError(err instanceof Error ? err.message : 'Failed to clean orphaned tasks');
        } finally {
            setIsCleaningOrphans(false);
        }
    };
    const qualityHealth = (() => {
        const pendingQuestion = pendingQuestions[0];
        if (failedSessions.length > 0 || totalFailures > 0) {
            return {
                state: 'At Risk',
                detail: failedSessions[0]?.error_message || `${totalFailures} generated test failure${totalFailures === 1 ? '' : 's'} need review.`,
                href: failedSessions[0] ? `/autopilot?sessionId=${encodeURIComponent(failedSessions[0].id)}` : '/runs',
                actionLabel: 'Review failures',
                tone: 'danger' as const,
                icon: <XCircle size={20} />,
            };
        }
        if (dashboard.total_runs > 0 && passRate < 60) {
            return {
                state: 'At Risk',
                detail: `Pass rate is ${passRate}%, below the executive quality threshold.`,
                href: '/analytics',
                actionLabel: 'Inspect analytics',
                tone: 'danger' as const,
                icon: <ShieldAlert size={20} />,
            };
        }
        if (pendingQuestion) {
            return {
                state: 'Watch',
                detail: pendingQuestion.question_text,
                href: `/autopilot?sessionId=${encodeURIComponent(pendingQuestion.session_id)}`,
                actionLabel: 'Review gate',
                tone: 'warning' as const,
                icon: <AlertTriangle size={20} />,
            };
        }
        if (dashboard.flaky_test_count > 0) {
            return {
                state: 'Watch',
                detail: `${dashboard.flaky_test_count} flaky test${dashboard.flaky_test_count === 1 ? '' : 's'} reduce confidence in the current signal.`,
                href: '/analytics',
                actionLabel: 'Inspect analytics',
                tone: 'warning' as const,
                icon: <ShieldAlert size={20} />,
            };
        }
        if (coverageGap) {
            return {
                state: 'Watch',
                detail: `RTM coverage is ${Math.round(rtmCoverage)}%, so important requirements may still be untested.`,
                href: '/coverage',
                actionLabel: 'Close coverage gaps',
                tone: 'warning' as const,
                icon: <GitBranch size={20} />,
            };
        }
        if (queueDegraded) {
            return {
                state: 'Watch',
                detail: orphanedTaskCount > 0
                    ? `${orphanedTaskCount} automation task${orphanedTaskCount === 1 ? '' : 's'} need cleanup before queue data is fully trusted.`
                    : queueUnavailable
                    ? 'Automation workers are not polling, so fresh quality data may be delayed.'
                    : `${staleRunningCount} stale automation task${staleRunningCount === 1 ? '' : 's'} may affect confidence.`,
                href: '/workflow',
                actionLabel: 'Check workflow',
                tone: 'warning' as const,
                icon: <Bot size={20} />,
            };
        }
        if (!hasRecentQualityData) {
            return {
                state: 'Watch',
                detail: 'No recent run data is available yet. Start a QA run to establish baseline health.',
                href: '/autopilot',
                actionLabel: 'Start QA run',
                tone: 'warning' as const,
                icon: <PlayCircle size={20} />,
            };
        }
        if (activeSessions.length > 0) {
            return {
                state: 'Healthy',
                detail: `${formatPhase(activeSessions[0].current_phase)} is ${Math.round(activeSessions[0].overall_progress)}% complete, with no blocking quality risks surfaced.`,
                href: `/autopilot?sessionId=${encodeURIComponent(activeSessions[0].id)}`,
                actionLabel: 'View active run',
                tone: 'primary' as const,
                icon: <PlayCircle size={20} />,
            };
        }
        return {
            state: 'Healthy',
            detail: 'Recent quality signals are clear across failures, review gates, flakiness, and coverage.',
            href: '/runs',
            actionLabel: 'View runs',
            tone: 'primary' as const,
            icon: <CheckCircle2 size={20} />,
        };
    })();
    const qualitySignals = [
        {
            label: 'Failed generated tests',
            value: totalFailures,
            detail: totalFailures > 0 ? `${failedSessions.length} failed workflow${failedSessions.length === 1 ? '' : 's'} in recent automation` : 'No generated-test failures in recent sessions',
            icon: <XCircle size={16} />,
            href: failedSessions[0] ? `/autopilot?sessionId=${encodeURIComponent(failedSessions[0].id)}` : '/runs',
            tone: totalFailures > 0 ? 'danger' : 'healthy',
        },
        {
            label: 'Flaky tests',
            value: dashboard.flaky_test_count,
            detail: dashboard.flaky_test_count > 0 ? 'Intermittent outcomes need triage' : 'No flaky tests detected',
            icon: <ShieldAlert size={16} />,
            href: '/analytics',
            tone: dashboard.flaky_test_count > 0 ? 'warning' : 'healthy',
        },
        {
            label: 'Pending review gates',
            value: pendingQuestions.length,
            detail: pendingQuestions.length > 0 ? `${awaitingInput.length} blocked run${awaitingInput.length === 1 ? '' : 's'} awaiting decision` : 'No review gates blocking progress',
            icon: <AlertTriangle size={16} />,
            href: pendingQuestions[0] ? `/autopilot?sessionId=${encodeURIComponent(pendingQuestions[0].session_id)}` : '/workflow',
            tone: pendingQuestions.length > 0 ? 'warning' : 'healthy',
        },
        {
            label: 'Coverage gaps',
            value: hasCoverageData ? (coverageGap ? `${Math.max(0, Math.round(60 - rtmCoverage))} pts` : 'Clear') : '—',
            detail: hasCoverageData ? `RTM coverage is ${Math.round(rtmCoverage)}%` : 'RTM coverage has not been generated',
            icon: <GitBranch size={16} />,
            href: '/coverage',
            tone: coverageGap ? 'warning' : 'healthy',
        },
        {
            label: 'Automation confidence',
            value: queueDegraded ? 'Watch' : 'Stable',
            detail: queueDegraded
                ? `${orphanedTaskCount} orphaned, ${staleRunningCount} stale, ${queue?.queued ?? 0} queued`
                : `${queueSourceLabel}: ${queue?.active ?? 0} active, ${queue?.queued ?? 0} queued`,
            icon: <Bot size={16} />,
            href: '/workflow',
            tone: queueDegraded ? 'warning' : 'healthy',
        },
    ];
    const attentionQualitySignals = qualitySignals.filter(signal => signal.tone !== 'healthy');
    const openQualityRiskCount = attentionQualitySignals.length;
    const lastRunAge = (() => {
        if (!dashboard.last_run_at) return null;
        const age = formatAge(dashboard.last_run_at);
        return age === dashboard.last_run_at ? null : age;
    })();
    const activeAutomationCount = activeSessions.length + backgroundAgentTaskCount;
    const healthMetrics = [
        {
            label: 'Pass rate',
            value: hasRecentQualityData ? `${passRate}%` : '—',
            detail: dashboard.total_runs > 0 ? `${dashboard.total_runs} run${dashboard.total_runs === 1 ? '' : 's'}` : 'Baseline needed',
            tone: dashboard.total_runs > 0 && passRate < 60 ? '#ef4444' : dashboard.total_runs > 0 && passRate < 80 ? '#f59e0b' : undefined,
        },
        {
            label: 'RTM coverage',
            value: hasCoverageData ? `${Math.round(rtmCoverage)}%` : '—',
            detail: hasCoverageData ? `${workflowProgress?.requirements ?? 0} requirement${(workflowProgress?.requirements ?? 0) === 1 ? '' : 's'}` : 'Not generated',
            tone: coverageGap ? '#f59e0b' : undefined,
        },
        {
            label: 'Active automation',
            value: activeAutomationCount,
            detail: `${queue?.queued ?? 0} queued`,
            tone: queueDegraded ? '#f59e0b' : undefined,
        },
        {
            label: 'Recent run age',
            value: lastRunAge || '—',
            detail: lastRunAge ? 'Latest completed signal' : dashboard.total_runs > 0 ? 'Last run unavailable' : 'No recent runs',
        },
    ];
    const queueRiskItem = queueDegraded ? {
        key: 'queue-confidence',
        node: (
            <TopRiskRow
                icon={<Bot size={15} />}
                title="Queue confidence"
                detail={(
                    <>
                        {orphanedTaskCount} orphaned, {staleRunningCount} stale, {queue?.queued ?? 0} queued
                        {cleanupError && (
                            <div style={{ color: '#f87171', fontSize: '0.72rem', marginTop: '0.45rem', lineHeight: 1.35 }}>
                                {cleanupError}
                            </div>
                        )}
                    </>
                )}
                action={orphanedTaskCount > 0 ? (
                    <button
                        type="button"
                        onClick={cleanOrphanedTasks}
                        disabled={isCleaningOrphans}
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.4rem',
                            minHeight: 30,
                            padding: '0.35rem 0.65rem',
                            borderRadius: '8px',
                            border: '1px solid rgba(239, 68, 68, 0.28)',
                            background: isCleaningOrphans ? 'rgba(239, 68, 68, 0.08)' : 'rgba(239, 68, 68, 0.13)',
                            color: '#f87171',
                            fontSize: '0.74rem',
                            fontWeight: 750,
                            cursor: isCleaningOrphans ? 'wait' : 'pointer',
                            whiteSpace: 'nowrap',
                            opacity: isCleaningOrphans ? 0.75 : 1,
                        }}
                    >
                        {isCleaningOrphans && <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />}
                        {isCleaningOrphans ? 'Cleaning' : 'Clean up'}
                    </button>
                ) : (
                    <Link href="/workflow" style={{ color: 'var(--primary)', fontSize: '0.8rem', fontWeight: 750, textDecoration: 'none', whiteSpace: 'nowrap' }}>
                        Workflow
                    </Link>
                )}
            />
        ),
    } : null;
    const topQualityRisks = (() => {
        const items: { key: string; node: React.ReactNode }[] = [
            ...failedSessions.slice(0, 2).map(session => ({
                key: `failed-${session.id}`,
                node: <SessionRow session={session} compact />,
            })),
            ...pendingQuestions.slice(0, 2).map(question => ({
                key: `gate-${question.id}`,
                node: (
                    <TopRiskRow
                        href={`/autopilot?sessionId=${encodeURIComponent(question.session_id)}`}
                        icon={<AlertTriangle size={15} />}
                        title="Review gate"
                        detail={question.question_text}
                    />
                ),
            })),
            ...(totalFailures > 0 && failedSessions.length === 0 ? [{
                key: 'generated-failures',
                node: (
                    <TopRiskRow
                        href="/runs"
                        icon={<XCircle size={15} />}
                        title="Generated test failures"
                        detail={`${totalFailures} generated test failure${totalFailures === 1 ? '' : 's'} need review.`}
                        tone="#ef4444"
                    />
                ),
            }] : []),
            ...(dashboard.flaky_test_count > 0 ? [{
                key: 'flaky-tests',
                node: (
                    <TopRiskRow
                        href="/analytics"
                        icon={<ShieldAlert size={15} />}
                        title="Flaky test group"
                        detail={`${dashboard.flaky_test_count} spec${dashboard.flaky_test_count === 1 ? '' : 's'} need triage.`}
                    />
                ),
            }] : []),
            ...(coverageGap ? [{
                key: 'coverage-gap',
                node: (
                    <TopRiskRow
                        href="/coverage"
                        icon={<GitBranch size={15} />}
                        title="Coverage gap"
                        detail={`RTM coverage is ${Math.round(rtmCoverage)}%, below the 60% threshold.`}
                    />
                ),
            }] : []),
            ...(queueRiskItem ? [queueRiskItem] : []),
        ];
        const visible = items.slice(0, 5);
        if (queueRiskItem && orphanedTaskCount > 0 && !visible.some(item => item.key === queueRiskItem.key)) {
            if (visible.length >= 5) {
                visible[visible.length - 1] = queueRiskItem;
            } else {
                visible.push(queueRiskItem);
            }
        }
        return visible;
    })();

    return (
        <PageLayout tier="wide" className="command-center-page">
            <PageHeader
                title="Quality Overview"
                subtitle="Project quality health, coverage, risk, and automation activity."
                icon={<CheckCircle2 size={20} />}
            />

            {error && (
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    marginBottom: '1rem',
                    padding: '0.75rem 0.9rem',
                    borderRadius: '8px',
                    background: 'rgba(239, 68, 68, 0.08)',
                    border: '1px solid rgba(239, 68, 68, 0.18)',
                    color: '#ef4444',
                    fontSize: '0.85rem',
                    fontWeight: 650,
                }}>
                    <XCircle size={16} />
                    {error}
                </div>
            )}

            {loading ? (
                <div className="card-elevated" style={{ padding: '2rem', display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                    Loading quality overview...
                </div>
            ) : (
                <>
                    <section className="command-hero" style={{
                        marginBottom: '1rem',
                    }}>
                        <div className="card-elevated quality-health-card" style={{
                            padding: '1.2rem',
                            display: 'grid',
                            gridTemplateColumns: 'minmax(0, 1.3fr) minmax(320px, 0.9fr)',
                            gap: '1.1rem',
                            alignItems: 'stretch',
                            minHeight: 150,
                            borderColor: qualityHealth.tone === 'danger'
                                ? 'rgba(239, 68, 68, 0.32)'
                                : qualityHealth.tone === 'warning'
                                    ? 'rgba(245, 158, 11, 0.32)'
                                    : 'rgba(59, 130, 246, 0.24)',
                        }}>
                            <div style={{ minWidth: 0, display: 'grid', gridTemplateColumns: 'auto minmax(0, 1fr)', gap: '1rem', alignContent: 'start' }}>
                                <div style={{
                                    width: 54,
                                    height: 54,
                                    borderRadius: '10px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    background: qualityHealth.tone === 'danger'
                                        ? 'rgba(239, 68, 68, 0.13)'
                                        : qualityHealth.tone === 'warning'
                                            ? 'rgba(245, 158, 11, 0.13)'
                                            : 'rgba(59, 130, 246, 0.13)',
                                    color: qualityHealth.tone === 'danger' ? '#ef4444' : qualityHealth.tone === 'warning' ? '#f59e0b' : 'var(--primary)',
                                }}>
                                    {qualityHealth.icon}
                                </div>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', fontWeight: 750, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                                        Quality health
                                    </div>
                                    <h2 style={{ fontSize: '1.45rem', lineHeight: 1.15, margin: '0.3rem 0 0.35rem', fontWeight: 850 }}>
                                        {qualityHealth.state}
                                    </h2>
                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.45, margin: 0, maxWidth: 760 }}>
                                        {qualityHealth.detail}
                                    </p>
                                    <div style={{ marginTop: '0.9rem' }}>
                                        <PrimaryButton href={qualityHealth.href} tone={qualityHealth.tone}>
                                            {qualityHealth.actionLabel}
                                            <ArrowRight size={16} />
                                        </PrimaryButton>
                                    </div>
                                </div>
                            </div>
                            <div className="quality-health-metrics" style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                                gap: '0.75rem',
                            }}>
                                {healthMetrics.map(item => (
                                    <CompactMetricItem key={item.label} {...item} />
                                ))}
                            </div>
                        </div>
                    </section>

                    <section className="command-grid" style={{
                        display: 'grid',
                        gridTemplateColumns: 'minmax(0, 1.45fr) minmax(320px, 0.9fr)',
                        gap: '1rem',
                    }}>
                        <Panel
                            title="Quality Signals"
                            action={<Link href="/analytics" style={{ color: 'var(--primary)', fontSize: '0.84rem', fontWeight: 700, textDecoration: 'none' }}>Analytics</Link>}
                        >
                            <div>
                                {attentionQualitySignals.length === 0 ? (
                                    <EmptyState
                                        icon={<CheckCircle2 size={30} />}
                                        title="Quality signals are clear"
                                        detail={hasRecentQualityData ? 'Failures, review gates, flakiness, coverage, and queue confidence are all within expected bounds.' : 'Start a QA run to establish the first quality baseline.'}
                                        links={(
                                            <>
                                                <Link href="/analytics" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Analytics</Link>
                                                <Link href="/coverage" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Coverage</Link>
                                                <Link href="/workflow" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Workflow</Link>
                                                <Link href="/autopilot" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Autopilot</Link>
                                            </>
                                        )}
                                    />
                                ) : (
                                    attentionQualitySignals.map(signal => {
                                        const signalColor = signal.tone === 'danger' ? '#ef4444' : '#f59e0b';
                                        return (
                                            <Link key={signal.label} href={signal.href} className="command-action-row" style={{
                                                display: 'grid',
                                                gridTemplateColumns: 'minmax(0, 1fr) auto',
                                                gap: '0.9rem',
                                                alignItems: 'center',
                                                padding: '0.95rem 1rem',
                                                borderBottom: '1px solid var(--border-subtle)',
                                                color: 'inherit',
                                                textDecoration: 'none',
                                            }}>
                                                <div style={{ minWidth: 0 }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: signalColor, fontSize: '0.84rem', fontWeight: 800 }}>
                                                        {signal.icon}
                                                        {signal.label}
                                                    </div>
                                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginTop: '0.25rem', lineHeight: 1.45 }}>
                                                        {signal.detail}
                                                    </div>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', color: signalColor, fontSize: '0.95rem', fontWeight: 850, whiteSpace: 'nowrap' }}>
                                                    {signal.value}
                                                    <ArrowRight size={15} />
                                                </div>
                                            </Link>
                                        );
                                    })
                                )}
                            </div>
                        </Panel>

                        <Panel title="Top Risks">
                            {topQualityRisks.length === 0 ? (
                                <EmptyState
                                    icon={<CheckCircle2 size={30} />}
                                    title="No open quality risks"
                                    detail={hasRecentQualityData ? 'There are no concrete failed sessions, blocked gates, flaky groups, coverage gaps, or queue confidence issues.' : 'Run data has not been collected yet; risks will appear here after the first baseline run.'}
                                />
                            ) : (
                                <div>
                                    {topQualityRisks.map(item => (
                                        <div key={item.key}>
                                            {item.node}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </Panel>

                        <Panel
                            title="Automation Activity"
                            action={<Link href="/autopilot" style={{ color: 'var(--primary)', fontSize: '0.84rem', fontWeight: 700, textDecoration: 'none' }}>View runs</Link>}
                        >
                            {activeSessions.length === 0 && backgroundAgentTaskCount === 0 ? (
                                <div style={{ padding: '2.25rem 1.25rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                    <Sparkles size={28} style={{ color: 'var(--primary)', marginBottom: '0.65rem' }} />
                                    <div style={{ fontWeight: 750, color: 'var(--text)', marginBottom: '0.25rem' }}>No automation runs are active</div>
                                    <div style={{ fontSize: '0.85rem' }}>Start a QA run to collect fresh quality evidence.</div>
                                </div>
                            ) : (
                                <div>
                                    <div style={{ padding: '0.85rem 1rem 0.65rem', color: 'var(--text-tertiary)', fontSize: '0.74rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                                        Agent team activity
                                    </div>
                                    {activeSessions.slice(0, 5).map(session => (
                                        <SessionRow key={session.id} session={session} />
                                    ))}
                                    {backgroundAgentTasks.slice(0, 3).map(task => (
                                        <AgentTaskRow key={task.id} task={task} />
                                    ))}
                                    {unlistedBackgroundTaskCount > 0 && (
                                        <div style={{ padding: '0.8rem 1rem', color: 'var(--text-secondary)', fontSize: '0.8rem', borderTop: '1px solid var(--border-subtle)' }}>
                                            {unlistedBackgroundTaskCount} running task{unlistedBackgroundTaskCount === 1 ? '' : 's'} reported by the queue without detail.
                                        </div>
                                    )}
                                </div>
                            )}
                        </Panel>

                        <Panel
                            title="Recent Quality Outcomes"
                            action={<Link href="/workflow" style={{ color: 'var(--primary)', fontSize: '0.84rem', fontWeight: 700, textDecoration: 'none' }}>Workflow monitor</Link>}
                        >
                            {completedSessions.length === 0 ? (
                                <div style={{ padding: '1.5rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.88rem' }}>
                                    Completed QA runs will appear here with generated specs, passing tests, and coverage outcomes.
                                </div>
                            ) : (
                                <div>
                                    {completedSessions.slice(0, 4).map(session => (
                                        <SessionRow key={session.id} session={session} compact />
                                    ))}
                                </div>
                            )}
                        </Panel>
                    </section>
                </>
            )}

            <style jsx>{`
                .command-session-row:hover,
                .command-action-row:hover,
                .command-agent-row:hover {
                    background: var(--surface-hover) !important;
                }
                @media (max-width: 1180px) {
                    .quality-health-card,
                    .command-grid {
                        grid-template-columns: 1fr !important;
                    }
                }
                @media (max-width: 720px) {
                    .quality-health-card > div:first-child {
                        grid-template-columns: 1fr !important;
                    }
                    .quality-health-metrics {
                        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                    }
                }
                @media (max-width: 360px) {
                    .quality-health-metrics {
                        grid-template-columns: 1fr !important;
                    }
                }
            `}</style>
        </PageLayout>
    );
}
