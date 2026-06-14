'use client';

import Link from 'next/link';
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
import { useCommandCenterData, type AgentQueueTaskSummary, type AutoPilotSessionSummary } from '@/hooks/useCommandCenterData';
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

type SignalSeverity = 'healthy' | 'warning' | 'danger' | 'neutral';

type QualitySignal = {
    label: string;
    value: string | number;
    detail: string;
    icon: React.ReactNode;
    href: string;
    severity: SignalSeverity;
};

const signalSeverityMeta: Record<SignalSeverity, { label: string; color: string; background: string; border: string }> = {
    healthy: {
        label: 'Healthy',
        color: '#22c55e',
        background: 'rgba(34, 197, 94, 0.045)',
        border: 'rgba(34, 197, 94, 0.16)',
    },
    warning: {
        label: 'Watch',
        color: '#f59e0b',
        background: 'rgba(245, 158, 11, 0.075)',
        border: 'rgba(245, 158, 11, 0.22)',
    },
    danger: {
        label: 'At risk',
        color: '#ef4444',
        background: 'rgba(239, 68, 68, 0.08)',
        border: 'rgba(239, 68, 68, 0.24)',
    },
    neutral: {
        label: 'Pending',
        color: '#94a3b8',
        background: 'rgba(148, 163, 184, 0.045)',
        border: 'rgba(148, 163, 184, 0.16)',
    },
};

function QualitySignalCard({ signal }: { signal: QualitySignal }) {
    const meta = signalSeverityMeta[signal.severity];
    return (
        <Link
            href={signal.href}
            className="quality-signal-card command-action-row"
            style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) auto',
                alignItems: 'start',
                gap: '0.85rem',
                minWidth: 0,
                minHeight: 132,
                padding: '0.95rem',
                borderRadius: '8px',
                border: `1px solid ${meta.border}`,
                background: meta.background,
                color: 'inherit',
                textDecoration: 'none',
            }}
        >
            <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: meta.color, fontSize: '0.78rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {signal.icon}
                    <span>{meta.label}</span>
                </div>
                <div style={{ marginTop: '0.7rem', color: 'var(--text-tertiary)', fontSize: '0.72rem', fontWeight: 750 }}>
                    {signal.label}
                </div>
                <div style={{ marginTop: '0.25rem', color: 'var(--text)', fontSize: '1.35rem', lineHeight: 1.1, fontWeight: 850, overflowWrap: 'anywhere' }}>
                    {signal.value}
                </div>
                <div style={{ marginTop: '0.4rem', color: 'var(--text-secondary)', fontSize: '0.8rem', lineHeight: 1.4 }}>
                    {signal.detail}
                </div>
            </div>
            <ArrowRight size={15} style={{ color: meta.color, marginTop: '0.15rem', flexShrink: 0 }} />
        </Link>
    );
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
        <section aria-label={title} className="card-elevated" style={{ overflow: 'hidden' }}>
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
    const qualityHealth = (() => {
        const pendingQuestion = pendingQuestions[0];
        if (failedSessions.length > 0 || totalFailures > 0) {
            return {
                state: 'At Risk',
                detail: 'The current quality baseline has a blocking signal that needs review.',
                href: failedSessions[0] ? `/autopilot?sessionId=${encodeURIComponent(failedSessions[0].id)}` : '/runs',
                actionLabel: 'Review failures',
                tone: 'danger' as const,
                icon: <XCircle size={20} />,
            };
        }
        if (dashboard.total_runs > 0 && passRate < 60) {
            return {
                state: 'At Risk',
                detail: 'The current execution baseline is below the executive quality threshold.',
                href: '/analytics',
                actionLabel: 'Inspect analytics',
                tone: 'danger' as const,
                icon: <ShieldAlert size={20} />,
            };
        }
        if (pendingQuestion) {
            return {
                state: 'Watch',
                detail: 'A review gate is blocking automation progress.',
                href: `/autopilot?sessionId=${encodeURIComponent(pendingQuestion.session_id)}`,
                actionLabel: 'Review gate',
                tone: 'warning' as const,
                icon: <AlertTriangle size={20} />,
            };
        }
        if (dashboard.flaky_test_count > 0) {
            return {
                state: 'Watch',
                detail: 'Intermittent outcomes are reducing confidence in the current baseline.',
                href: '/analytics',
                actionLabel: 'Inspect analytics',
                tone: 'warning' as const,
                icon: <ShieldAlert size={20} />,
            };
        }
        if (coverageGap) {
            return {
                state: 'Watch',
                detail: 'Traceability coverage needs attention before requirements can be trusted.',
                href: '/rtm?coverage_status=uncovered',
                actionLabel: 'Close coverage gaps',
                tone: 'warning' as const,
                icon: <GitBranch size={20} />,
            };
        }
        if (queueDegraded) {
            return {
                state: 'Watch',
                detail: 'Automation confidence needs attention before fresh quality data is trusted.',
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
                detail: 'An automation run is in progress with no blocking quality risks surfaced.',
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
    const lastRunAge = (() => {
        if (!dashboard.last_run_at) return null;
        const age = formatAge(dashboard.last_run_at);
        return age === dashboard.last_run_at ? null : age;
    })();
    const lastRunAgeDays = (() => {
        if (!dashboard.last_run_at) return null;
        const timestamp = new Date(dashboard.last_run_at).getTime();
        if (!Number.isFinite(timestamp)) return null;
        return Math.floor(Math.max(0, Date.now() - timestamp) / 86400000);
    })();
    const qualitySignals: QualitySignal[] = [
        {
            label: 'Failed generated tests',
            value: totalFailures,
            detail: totalFailures > 0 ? `${failedSessions.length} failed workflow${failedSessions.length === 1 ? '' : 's'} in recent automation` : 'No generated-test failures in recent sessions',
            icon: <XCircle size={15} />,
            href: failedSessions[0] ? `/autopilot?sessionId=${encodeURIComponent(failedSessions[0].id)}` : '/runs',
            severity: totalFailures > 0 ? 'danger' : hasRecentQualityData ? 'healthy' : 'neutral',
        },
        {
            label: 'Pass rate',
            value: hasRecentQualityData ? `${passRate}%` : '—',
            detail: dashboard.total_runs > 0 ? `${dashboard.total_runs} completed run${dashboard.total_runs === 1 ? '' : 's'} in the current baseline` : 'Run baseline has not been established',
            icon: <CheckCircle2 size={15} />,
            href: '/analytics',
            severity: dashboard.total_runs === 0 ? 'neutral' : passRate < 60 ? 'danger' : passRate < 80 ? 'warning' : 'healthy',
        },
        {
            label: 'Flaky tests',
            value: dashboard.flaky_test_count,
            detail: dashboard.flaky_test_count > 0 ? 'Intermittent outcomes need triage' : 'No flaky tests detected',
            icon: <ShieldAlert size={15} />,
            href: '/analytics',
            severity: dashboard.flaky_test_count > 0 ? 'warning' : hasRecentQualityData ? 'healthy' : 'neutral',
        },
        {
            label: 'Pending review gates',
            value: pendingQuestions.length,
            detail: pendingQuestions.length > 0 ? `${awaitingInput.length} blocked run${awaitingInput.length === 1 ? '' : 's'} awaiting decision` : 'No review gates blocking progress',
            icon: <AlertTriangle size={15} />,
            href: pendingQuestions[0] ? `/autopilot?sessionId=${encodeURIComponent(pendingQuestions[0].session_id)}` : '/workflow',
            severity: pendingQuestions.length > 0 ? 'warning' : hasRecentQualityData ? 'healthy' : 'neutral',
        },
        {
            label: 'RTM coverage',
            value: hasCoverageData ? `${Math.round(rtmCoverage)}%` : '—',
            detail: hasCoverageData ? `${workflowProgress?.requirements ?? 0} requirement${(workflowProgress?.requirements ?? 0) === 1 ? '' : 's'} traced` : 'RTM coverage has not been generated',
            icon: <GitBranch size={15} />,
            href: '/rtm?coverage_status=uncovered',
            severity: hasCoverageData ? (coverageGap ? 'warning' : 'healthy') : 'neutral',
        },
        {
            label: 'Automation confidence',
            value: queueUnavailable ? 'Blocked' : queueDegraded ? 'Watch' : queue ? 'Stable' : '—',
            detail: queueDegraded
                ? `${orphanedTaskCount} orphaned, ${staleRunningCount} stale, ${queue?.queued ?? 0} queued`
                : queue ? `${queueSourceLabel}: ${queue?.active ?? 0} active, ${queue?.queued ?? 0} queued` : 'Queue status has not loaded',
            icon: <Bot size={15} />,
            href: '/workflow',
            severity: queueUnavailable ? 'danger' : queueDegraded ? 'warning' : queue ? 'healthy' : 'neutral',
        },
        {
            label: 'Recent run age',
            value: lastRunAge || '—',
            detail: lastRunAge ? 'Latest completed signal' : dashboard.total_runs > 0 ? 'Last run timestamp unavailable' : 'No recent runs',
            icon: <Clock size={15} />,
            href: '/runs',
            severity: !lastRunAge ? 'neutral' : (lastRunAgeDays ?? 0) > 7 ? 'warning' : 'healthy',
        },
    ];
    const hasQualityBaseline = hasRecentQualityData || hasCoverageData || Boolean(queue);

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
                            padding: '1.35rem',
                            display: 'grid',
                            gridTemplateColumns: 'minmax(0, 1fr)',
                            gap: '1.1rem',
                            alignItems: 'stretch',
                            minHeight: 180,
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
                        </div>
                    </section>

                    <Panel
                        title="Quality Signals"
                        action={<Link href="/analytics" style={{ color: 'var(--primary)', fontSize: '0.84rem', fontWeight: 700, textDecoration: 'none' }}>Analytics</Link>}
                    >
                        {hasQualityBaseline ? (
                            <div className="quality-signal-grid" style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                                gap: '0.85rem',
                                padding: '1rem',
                            }}>
                                {qualitySignals.map(signal => (
                                    <QualitySignalCard key={signal.label} signal={signal} />
                                ))}
                            </div>
                        ) : (
                            <EmptyState
                                icon={<CheckCircle2 size={30} />}
                                title="No quality baseline yet"
                                detail="Start a QA run to establish the first quality baseline."
                                links={(
                                    <>
                                        <Link href="/analytics" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Analytics</Link>
                                        <Link href="/coverage" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Coverage</Link>
                                        <Link href="/workflow" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Workflow</Link>
                                        <Link href="/autopilot" style={{ color: 'var(--primary)', textDecoration: 'none' }}>Autopilot</Link>
                                    </>
                                )}
                            />
                        )}
                    </Panel>

                    <section className="command-grid" style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                        gap: '1rem',
                        marginTop: '1rem',
                    }}>
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
                }
            `}</style>
        </PageLayout>
    );
}
