'use client';

import Link from 'next/link';
import {
    AlertTriangle,
    ArrowRight,
    Bot,
    CheckCircle2,
    Clock,
    FileText,
    GitBranch,
    Loader2,
    PlayCircle,
    Rocket,
    ShieldAlert,
    Sparkles,
    TrendingUp,
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
    const normalized = iso.endsWith('Z') ? iso : `${iso}Z`;
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(normalized).getTime()) / 1000));
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

function MetricCard({ label, value, detail, icon, tone }: { label: string; value: string | number; detail: string; icon: React.ReactNode; tone: string }) {
    return (
        <div className="card-elevated command-metric" style={{
            padding: '1rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.85rem',
            minHeight: 104,
        }}>
            <div style={{
                width: 42,
                height: 42,
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: `${tone}18`,
                color: tone,
                flexShrink: 0,
            }}>
                {icon}
            </div>
            <div style={{ minWidth: 0 }}>
                <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {label}
                </div>
                <div style={{ color: 'var(--text)', fontSize: '1.55rem', lineHeight: 1.1, fontWeight: 850, marginTop: '0.2rem' }}>
                    {value}
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.2rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {detail}
                </div>
            </div>
        </div>
    );
}

function SessionRow({ session, compact = false }: { session: AutoPilotSessionSummary; compact?: boolean }) {
    const failed = session.status === 'failed';
    const needsInput = session.status === 'awaiting_input';
    const href = `/autopilot?session=${encodeURIComponent(session.id)}`;

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
                        {isOrphaned ? 'Orphaned task' : task.owner_label || 'Worker task'}
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
    const browserSlotsRunning = queue?.browser_pool?.running ?? 0;
    const orphanedTaskCount = queue?.orphaned_tasks ?? runningTasks.filter(task => task.orphaned).length;
    const queueSourceLabel = queue?.mode === 'redis' ? 'Redis workers' : queue?.mode === 'browser_pool' ? 'Browser pool' : 'Worker pool';
    const nextAction = (() => {
        const pendingQuestion = pendingQuestions[0];
        if (pendingQuestion) {
            return {
                label: 'Review Pending Gate',
                href: `/autopilot?session=${encodeURIComponent(pendingQuestion.session_id)}`,
                detail: pendingQuestion.question_text,
                tone: 'warning' as const,
                icon: <AlertTriangle size={18} />,
            };
        }
        if (failedSessions.length > 0) {
            return {
                label: 'Investigate AutoPilot Failure',
                href: `/autopilot?session=${encodeURIComponent(failedSessions[0].id)}`,
                detail: failedSessions[0].error_message || 'A recent autonomous workflow failed.',
                tone: 'danger' as const,
                icon: <XCircle size={18} />,
            };
        }
        if (activeSessions.length > 0) {
            return {
                label: 'Monitor Active AutoPilot',
                href: `/autopilot?session=${encodeURIComponent(activeSessions[0].id)}`,
                detail: `${formatPhase(activeSessions[0].current_phase)} is ${Math.round(activeSessions[0].overall_progress)}% complete.`,
                tone: 'primary' as const,
                icon: <PlayCircle size={18} />,
            };
        }
        if (!hasAnySessions) {
            return {
                label: 'Start AutoPilot',
                href: '/autopilot',
                detail: 'Discover flows, generate requirements, create specs, run tests, and report from one guided workflow.',
                tone: 'primary' as const,
                icon: <Rocket size={18} />,
            };
        }
        if (dashboard.flaky_test_count > 0) {
            return {
                label: 'Review Flaky Tests',
                href: '/analytics',
                detail: `${dashboard.flaky_test_count} flaky test${dashboard.flaky_test_count === 1 ? '' : 's'} need attention.`,
                tone: 'warning' as const,
                icon: <ShieldAlert size={18} />,
            };
        }
        if (rtmCoverage > 0 && rtmCoverage < 60) {
            return {
                label: 'Close Coverage Gaps',
                href: '/coverage',
                detail: `RTM coverage is ${Math.round(rtmCoverage)}%.`,
                tone: 'warning' as const,
                icon: <GitBranch size={18} />,
            };
        }
        return {
            label: 'Start AutoPilot',
            href: '/autopilot',
            detail: 'Run another guided pass when you are ready to expand coverage.',
            tone: 'primary' as const,
            icon: <Rocket size={18} />,
        };
    })();

    return (
        <PageLayout tier="wide" className="command-center-page">
            <PageHeader
                title="Command Center"
                subtitle="AutoPilot-first quality operations for QA leads."
                icon={<Rocket size={20} />}
                actions={(
                    <PrimaryButton href={nextAction.href} tone={nextAction.tone}>
                        {nextAction.icon}
                        {nextAction.label}
                    </PrimaryButton>
                )}
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
                    Loading command center...
                </div>
            ) : (
                <>
                    <section className="command-hero" style={{
                        display: 'grid',
                        gridTemplateColumns: 'minmax(0, 1.45fr) minmax(320px, 0.9fr)',
                        gap: '1rem',
                        marginBottom: '1rem',
                    }}>
                        <div className="card-elevated" style={{
                            padding: '1.25rem',
                            display: 'grid',
                            gridTemplateColumns: 'auto minmax(0, 1fr) auto',
                            gap: '1rem',
                            alignItems: 'center',
                            minHeight: 150,
                            borderColor: nextAction.tone === 'danger'
                                ? 'rgba(239, 68, 68, 0.32)'
                                : nextAction.tone === 'warning'
                                    ? 'rgba(245, 158, 11, 0.32)'
                                    : 'rgba(59, 130, 246, 0.24)',
                        }}>
                            <div style={{
                                width: 54,
                                height: 54,
                                borderRadius: '10px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                background: nextAction.tone === 'danger'
                                    ? 'rgba(239, 68, 68, 0.13)'
                                    : nextAction.tone === 'warning'
                                        ? 'rgba(245, 158, 11, 0.13)'
                                        : 'rgba(59, 130, 246, 0.13)',
                                color: nextAction.tone === 'danger' ? '#ef4444' : nextAction.tone === 'warning' ? '#f59e0b' : 'var(--primary)',
                            }}>
                                {nextAction.icon}
                            </div>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', fontWeight: 750, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                                    Next action
                                </div>
                                <h2 style={{ fontSize: '1.45rem', lineHeight: 1.15, margin: '0.3rem 0 0.35rem', fontWeight: 850 }}>
                                    {nextAction.label}
                                </h2>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0, maxWidth: 720 }}>
                                    {nextAction.detail}
                                </p>
                            </div>
                            <PrimaryButton href={nextAction.href} tone={nextAction.tone}>
                                Open
                                <ArrowRight size={16} />
                            </PrimaryButton>
                        </div>

                        <div className="card-elevated" style={{ padding: '1.15rem', minHeight: 150 }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.9rem' }}>
                                <div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', fontWeight: 750, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                                        Automation load
                                    </div>
                                    <div style={{ fontSize: '1rem', fontWeight: 800, marginTop: '0.2rem' }}>Agent capacity</div>
                                </div>
                                <Bot size={22} style={{ color: 'var(--primary)' }} />
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.65rem' }}>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Agent tasks</div>
                                    <div style={{ fontSize: '1.45rem', fontWeight: 850 }}>{queue?.active ?? 0}</div>
                                </div>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Browser slots</div>
                                    <div style={{ fontSize: '1.45rem', fontWeight: 850 }}>{browserSlotsRunning}</div>
                                </div>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Queued</div>
                                    <div style={{ fontSize: '1.45rem', fontWeight: 850 }}>{queue?.queued ?? 0}</div>
                                </div>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Workers</div>
                                    <div style={{ fontSize: '1.45rem', fontWeight: 850 }}>{queue?.workers_alive ?? 0}</div>
                                </div>
                            </div>
                            <div style={{ color: orphanedTaskCount > 0 ? '#ef4444' : backgroundAgentTaskCount > 0 ? '#f59e0b' : 'var(--text-secondary)', fontSize: '0.76rem', marginTop: '0.75rem', lineHeight: 1.35 }}>
                                {orphanedTaskCount > 0
                                    ? `${orphanedTaskCount} orphaned task${orphanedTaskCount === 1 ? '' : 's'} need cleanup.`
                                    : backgroundAgentTaskCount > 0
                                    ? `${backgroundAgentTaskCount} running task${backgroundAgentTaskCount === 1 ? ' is' : 's are'} not tied to visible AutoPilot work.`
                                    : `${queueSourceLabel}: ${queue?.active ?? 0} task${(queue?.active ?? 0) === 1 ? '' : 's'}, ${browserSlotsRunning} browser slot${browserSlotsRunning === 1 ? '' : 's'} active.`}
                                {(queue?.stale_running ?? 0) > 0 ? ` ${queue?.stale_running} stale.` : ''}
                            </div>
                        </div>
                    </section>

                    <section className="command-metrics" style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
                        gap: '1rem',
                        marginBottom: '1rem',
                    }}>
                        <MetricCard label="Pending Reviews" value={pendingQuestions.length} detail={awaitingInput.length ? `${awaitingInput.length} session gate${awaitingInput.length === 1 ? '' : 's'}` : 'No blocked reviews'} icon={<AlertTriangle size={20} />} tone={pendingQuestions.length ? '#f59e0b' : '#22c55e'} />
                        <MetricCard label="Active AutoPilot" value={activeSessions.length} detail={activeSessions.length ? 'Work in progress' : 'No active sessions'} icon={<Rocket size={20} />} tone="#3b82f6" />
                        <MetricCard label="Pass Rate" value={`${passRate}%`} detail={`${dashboard.total_runs} total runs`} icon={<TrendingUp size={20} />} tone={passRate >= 80 ? '#22c55e' : passRate >= 60 ? '#f59e0b' : '#ef4444'} />
                        <MetricCard label="Coverage" value={rtmCoverage ? `${Math.round(rtmCoverage)}%` : '—'} detail={`${workflowProgress?.requirements ?? 0} requirements`} icon={<GitBranch size={20} />} tone={rtmCoverage >= 60 ? '#22c55e' : rtmCoverage > 0 ? '#f59e0b' : '#94a3b8'} />
                    </section>

                    <section className="command-grid" style={{
                        display: 'grid',
                        gridTemplateColumns: 'minmax(0, 1.45fr) minmax(320px, 0.9fr)',
                        gap: '1rem',
                    }}>
                        <Panel
                            title="Active AutoPilot Work"
                            action={<Link href="/autopilot" style={{ color: 'var(--primary)', fontSize: '0.84rem', fontWeight: 700, textDecoration: 'none' }}>View all</Link>}
                        >
                            {activeSessions.length === 0 ? (
                                <div style={{ padding: '2.25rem 1.25rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                    <Sparkles size={28} style={{ color: 'var(--primary)', marginBottom: '0.65rem' }} />
                                    <div style={{ fontWeight: 750, color: 'var(--text)', marginBottom: '0.25rem' }}>No autonomous workflow is running</div>
                                    <div style={{ fontSize: '0.85rem' }}>Start AutoPilot to discover flows, generate tests, run them, and report coverage.</div>
                                </div>
                            ) : (
                                <div>
                                    {activeSessions.slice(0, 5).map(session => (
                                        <SessionRow key={session.id} session={session} />
                                    ))}
                                </div>
                            )}
                            {backgroundAgentTaskCount > 0 && (
                                <div>
                                    <div style={{ padding: '0.85rem 1rem 0.65rem', color: '#f59e0b', fontSize: '0.78rem', fontWeight: 800 }}>
                                        Background agent work
                                    </div>
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

                        <Panel title="Action Required">
                            {pendingQuestions.length === 0 && failedSessions.length === 0 && dashboard.flaky_test_count === 0 && totalFailures === 0 ? (
                                <div style={{ padding: '2.25rem 1.25rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                    <CheckCircle2 size={30} style={{ color: '#22c55e', marginBottom: '0.65rem' }} />
                                    <div style={{ fontWeight: 750, color: 'var(--text)', marginBottom: '0.25rem' }}>Nothing needs intervention</div>
                                    <div style={{ fontSize: '0.85rem' }}>Reviews, failures, and flaky tests are clear.</div>
                                </div>
                            ) : (
                                <div>
                                    {pendingQuestions.slice(0, 3).map(question => (
                                        <Link key={question.id} href={`/autopilot?session=${encodeURIComponent(question.session_id)}`} className="command-action-row" style={{
                                            display: 'block',
                                            padding: '0.95rem 1rem',
                                            borderBottom: '1px solid var(--border-subtle)',
                                            color: 'inherit',
                                            textDecoration: 'none',
                                        }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#f59e0b', fontSize: '0.82rem', fontWeight: 800 }}>
                                                <AlertTriangle size={15} />
                                                Review gate
                                            </div>
                                            <div style={{ marginTop: '0.35rem', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
                                                {question.question_text}
                                            </div>
                                        </Link>
                                    ))}
                                    {failedSessions.slice(0, 2).map(session => (
                                        <SessionRow key={session.id} session={session} compact />
                                    ))}
                                    {dashboard.flaky_test_count > 0 && (
                                        <Link href="/analytics" className="command-action-row" style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            gap: '0.75rem',
                                            padding: '0.95rem 1rem',
                                            color: 'inherit',
                                            textDecoration: 'none',
                                        }}>
                                            <div>
                                                <div style={{ color: '#f59e0b', fontSize: '0.82rem', fontWeight: 800 }}>Flaky tests</div>
                                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '0.25rem' }}>{dashboard.flaky_test_count} spec{dashboard.flaky_test_count === 1 ? '' : 's'} need triage</div>
                                            </div>
                                            <ArrowRight size={16} />
                                        </Link>
                                    )}
                                </div>
                            )}
                        </Panel>

                        <Panel
                            title="Recent AutoPilot Results"
                            action={<Link href="/workflow" style={{ color: 'var(--primary)', fontSize: '0.84rem', fontWeight: 700, textDecoration: 'none' }}>Workflow monitor</Link>}
                        >
                            {completedSessions.length === 0 ? (
                                <div style={{ padding: '1.5rem 1.25rem', color: 'var(--text-secondary)', fontSize: '0.88rem' }}>
                                    Completed AutoPilot sessions will appear here with generated specs, passing tests, and coverage outcomes.
                                </div>
                            ) : (
                                <div>
                                    {completedSessions.slice(0, 4).map(session => (
                                        <SessionRow key={session.id} session={session} compact />
                                    ))}
                                </div>
                            )}
                        </Panel>

                        <Panel title="Quality Snapshot">
                            <div style={{ padding: '1rem', display: 'grid', gap: '0.8rem' }}>
                                {[
                                    { label: 'Specs', value: dashboard.total_specs, icon: <FileText size={16} />, href: '/specs' },
                                    { label: 'Runs', value: dashboard.total_runs, icon: <PlayCircle size={16} />, href: '/runs' },
                                    { label: 'Flaky tests', value: dashboard.flaky_test_count, icon: <AlertTriangle size={16} />, href: '/analytics' },
                                    { label: 'Failed generated tests', value: totalFailures, icon: <XCircle size={16} />, href: '/autopilot' },
                                ].map(item => (
                                    <Link key={item.label} href={item.href} style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        gap: '0.85rem',
                                        minHeight: 44,
                                        padding: '0.65rem 0.75rem',
                                        borderRadius: '8px',
                                        background: 'var(--surface)',
                                        color: 'inherit',
                                        textDecoration: 'none',
                                    }}>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', color: 'var(--text-secondary)', fontSize: '0.85rem', fontWeight: 650 }}>
                                            {item.icon}
                                            {item.label}
                                        </span>
                                        <span style={{ fontSize: '1rem', fontWeight: 850 }}>{item.value}</span>
                                    </Link>
                                ))}
                            </div>
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
                    .command-hero,
                    .command-grid {
                        grid-template-columns: 1fr !important;
                    }
                    .command-metrics {
                        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                    }
                }
                @media (max-width: 720px) {
                    .command-metrics {
                        grid-template-columns: 1fr !important;
                    }
                    .command-hero > div:first-child {
                        grid-template-columns: 1fr !important;
                    }
                }
            `}</style>
        </PageLayout>
    );
}
