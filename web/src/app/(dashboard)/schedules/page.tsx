'use client';

import { useState, useEffect, useCallback } from 'react';
import {
    Clock, Plus, Play, Pause, Trash2, Edit3, Loader2,
    CheckCircle, XCircle, AlertCircle, Calendar, RotateCw,
} from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { ScheduleModal } from '@/components/ScheduleModal';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface Schedule {
    id: string;
    name: string;
    description?: string;
    cron_expression: string;
    timezone: string;
    enabled: boolean;
    status: string;
    next_run_at?: string;
    last_run_at?: string;
    last_run_status?: string;
    successful_executions: number;
    failed_executions: number;
    total_executions: number;
    success_rate: number;
    tags?: string[];
    browser?: string;
    hybrid_mode?: boolean;
    automated_only?: boolean;
    created_at: string;
}

interface Execution {
    id: string;
    schedule_id: string;
    schedule_name?: string;
    trigger_type: string;
    started_at: string;
    completed_at?: string;
    status: string;
    batch_id?: string;
    duration_seconds?: number;
}

interface NextRun {
    schedule_id: string;
    schedule_name: string;
    fire_time: string;
}

const DAYS_OF_WEEK: Record<string, string> = {
    '*': 'every day',
    '0': 'Sun',
    '1': 'Mon',
    '2': 'Tue',
    '3': 'Wed',
    '4': 'Thu',
    '5': 'Fri',
    '6': 'Sat',
    '1-5': 'weekdays',
};

function formatInScheduleTimezone(isoString: string, timezone: string): string {
    const date = new Date(isoString);
    try {
        return date.toLocaleString(undefined, { timeZone: timezone }) + ` (${timezone})`;
    } catch {
        return date.toLocaleString() + ` (${timezone})`;
    }
}

function cronToHuman(cron: string): string {
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return cron;
    const [minute, hour, , , dow] = parts;
    let time = '';
    if (hour === '*') {
        time = 'every hour';
    } else if (hour.startsWith('*/')) {
        time = `every ${hour.slice(2)}h`;
    } else {
        time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`;
    }
    const dayStr = DAYS_OF_WEEK[dow] || dow;
    if (dow === '*') return time;
    return `${dayStr} ${time}`;
}

function getStatusBadge(status: string) {
    let color = 'var(--text-secondary)';
    let bg = 'rgba(128,128,128,0.1)';
    if (status === 'active' || status === 'pass' || status === 'success') {
        color = 'var(--success)';
        bg = 'var(--success-muted)';
    } else if (status === 'paused') {
        color = 'var(--warning)';
        bg = 'var(--warning-muted)';
    } else if (status === 'error' || status === 'fail' || status === 'failed') {
        color = 'var(--danger)';
        bg = 'var(--danger-muted)';
    } else if (status === 'running') {
        color = 'var(--primary)';
        bg = 'var(--primary-glow)';
    }
    return { color, bg };
}

export default function SchedulesPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || (typeof window !== 'undefined' ? localStorage.getItem('selectedProjectId') : null) || 'default';

    const [schedules, setSchedules] = useState<Schedule[]>([]);
    const [executions, setExecutions] = useState<Execution[]>([]);
    const [upcomingRuns, setUpcomingRuns] = useState<NextRun[]>([]);
    const [loading, setLoading] = useState(true);
    const [modalOpen, setModalOpen] = useState(false);
    const [editingSchedule, setEditingSchedule] = useState<Schedule | undefined>(undefined);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [page, setPage] = useState(1);
    const pageSize = 15;

    const pid = encodeURIComponent(projectId);

    const fetchSchedules = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/scheduling/${pid}/schedules`);
            if (res.ok) {
                const data = await res.json();
                setSchedules(data);
            }
        } catch (error) { console.error('Failed to fetch schedules:', error); }
    }, [pid]);

    const fetchExecutions = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/scheduling/${pid}/executions?limit=${pageSize}&offset=${(page - 1) * pageSize}`);
            if (res.ok) {
                const data = await res.json();
                setExecutions(Array.isArray(data) ? data : data.executions ?? []);
            }
        } catch (error) { console.error('Failed to fetch executions:', error); }
    }, [pid, page]);

    const fetchUpcoming = useCallback(async () => {
        const runs: NextRun[] = [];
        for (const sched of schedules) {
            if (!sched.enabled) continue;
            try {
                const res = await fetch(`${API_BASE}/scheduling/${pid}/schedules/${sched.id}/next-runs?count=3`);
                if (res.ok) {
                    const data = await res.json();
                    for (const time of (data.next_runs || [])) {
                        runs.push({ schedule_id: sched.id, schedule_name: sched.name, fire_time: time });
                    }
                }
            } catch (error) { console.error('Failed to fetch upcoming runs:', error); }
        }
        runs.sort((a, b) => new Date(a.fire_time).getTime() - new Date(b.fire_time).getTime());
        setUpcomingRuns(runs);
    }, [schedules, pid]);

    useEffect(() => {
        setLoading(true);
        fetchSchedules().finally(() => setLoading(false));
    }, [fetchSchedules]);

    useEffect(() => {
        fetchExecutions();
    }, [fetchExecutions]);

    useEffect(() => {
        if (schedules.length > 0) {
            fetchUpcoming();
        }
    }, [schedules, fetchUpcoming]);

    const handleToggle = async (sched: Schedule) => {
        setActionLoading(sched.id);
        try {
            const res = await fetch(`${API_BASE}/scheduling/${pid}/schedules/${sched.id}/toggle`, {
                method: 'POST',
            });
            if (!res.ok) {
                console.error('Failed to toggle schedule:', await res.text());
            }
            await fetchSchedules();
        } catch (error) { console.error('Failed to toggle schedule:', error); }
        setActionLoading(null);
    };

    const handleRunNow = async (sched: Schedule) => {
        setActionLoading(sched.id);
        try {
            await fetch(`${API_BASE}/scheduling/${pid}/schedules/${sched.id}/run-now`, { method: 'POST' });
            await fetchSchedules();
            await fetchExecutions();
        } catch (error) { console.error('Failed to run schedule now:', error); }
        setActionLoading(null);
    };

    const handleDelete = async (sched: Schedule) => {
        if (!confirm(`Delete schedule "${sched.name}"?`)) return;
        setActionLoading(sched.id);
        try {
            await fetch(`${API_BASE}/scheduling/${pid}/schedules/${sched.id}`, { method: 'DELETE' });
            await fetchSchedules();
        } catch (error) { console.error('Failed to delete schedule:', error); }
        setActionLoading(null);
    };

    const handleSave = () => {
        fetchSchedules();
        fetchExecutions();
    };

    const successRate = (s: Schedule) => {
        if (s.total_executions === 0) return 0;
        return Math.round(s.success_rate ?? (s.successful_executions / s.total_executions) * 100);
    };

    if (loading) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={4} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="Schedules"
                subtitle="Automate recurring test executions"
                icon={<Clock size={20} />}
                actions={
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                            onClick={() => { fetchSchedules(); fetchExecutions(); }}
                            style={{
                                padding: '0.5rem 0.75rem',
                                background: 'transparent',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                cursor: 'pointer',
                                color: 'var(--text-secondary)',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                fontSize: '0.85rem',
                            }}
                        >
                            <RotateCw size={14} />
                            Refresh
                        </button>
                        <button
                            onClick={() => { setEditingSchedule(undefined); setModalOpen(true); }}
                            style={{
                                padding: '0.5rem 1rem',
                                background: 'var(--primary)',
                                color: 'white',
                                border: 'none',
                                borderRadius: 'var(--radius)',
                                cursor: 'pointer',
                                fontWeight: 600,
                                fontSize: '0.85rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                            }}
                        >
                            <Plus size={16} />
                            New Schedule
                        </button>
                    </div>
                }
            />

            {/* Schedule Cards Grid */}
            {schedules.length === 0 ? (
                <EmptyState
                    icon={<Clock size={32} />}
                    title="No schedules yet"
                    description="Create a schedule to automate recurring test executions."
                    action={
                        <button
                            onClick={() => { setEditingSchedule(undefined); setModalOpen(true); }}
                            className="btn btn-primary"
                        >
                            <Plus size={16} /> New Schedule
                        </button>
                    }
                />
            ) : (
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                    gap: '1rem',
                    marginBottom: '2rem',
                }}>
                    {schedules.map(sched => {
                        const badge = getStatusBadge(sched.enabled ? (sched.status || 'active') : 'paused');
                        const rate = successRate(sched);
                        return (
                            <div key={sched.id} style={{
                                padding: '1.25rem',
                                background: 'var(--surface)',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '0.75rem',
                            }}>
                                {/* Header row */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '0.15rem' }}>{sched.name}</div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{cronToHuman(sched.cron_expression)} {sched.timezone}</div>
                                    </div>
                                    <span style={{
                                        padding: '0.15rem 0.5rem',
                                        borderRadius: '999px',
                                        fontSize: '0.7rem',
                                        fontWeight: 600,
                                        color: badge.color,
                                        background: badge.bg,
                                        textTransform: 'capitalize',
                                        flexShrink: 0,
                                    }}>
                                        {sched.enabled ? (sched.status || 'active') : 'paused'}
                                    </span>
                                </div>

                                {/* Timing */}
                                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    <div>
                                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: '0.1rem' }}>Next Run</div>
                                        <div>{sched.next_run_at ? formatInScheduleTimezone(sched.next_run_at, sched.timezone) : '-'}</div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: '0.1rem' }}>Last Run</div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                            {sched.last_run_at ? new Date(sched.last_run_at).toLocaleString() + ' (local)' : '-'}
                                            {sched.last_run_status && (
                                                <span style={{ color: sched.last_run_status === 'pass' ? 'var(--success)' : 'var(--danger)' }}>
                                                    {sched.last_run_status === 'pass' ? <CheckCircle size={12} /> : <XCircle size={12} />}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Success rate bar */}
                                {sched.total_executions > 0 && (
                                    <div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                                            <span style={{ color: 'var(--text-secondary)' }}>Success Rate</span>
                                            <span style={{ fontWeight: 600, color: rate >= 80 ? 'var(--success)' : rate >= 50 ? 'var(--warning)' : 'var(--danger)' }}>{rate}%</span>
                                        </div>
                                        <div style={{
                                            height: '4px',
                                            borderRadius: '2px',
                                            background: 'rgba(128,128,128,0.15)',
                                            overflow: 'hidden',
                                        }}>
                                            <div style={{
                                                height: '100%',
                                                width: `${rate}%`,
                                                borderRadius: '2px',
                                                background: rate >= 80 ? 'var(--success)' : rate >= 50 ? 'var(--warning)' : 'var(--danger)',
                                                transition: 'width 0.3s',
                                            }} />
                                        </div>
                                        <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
                                            {sched.successful_executions} passed / {sched.total_executions} total
                                        </div>
                                    </div>
                                )}

                                {/* Actions */}
                                <div style={{
                                    display: 'flex',
                                    gap: '0.5rem',
                                    paddingTop: '0.5rem',
                                    borderTop: '1px solid var(--border)',
                                }}>
                                    <button
                                        onClick={() => { setEditingSchedule(sched); setModalOpen(true); }}
                                        disabled={actionLoading === sched.id}
                                        style={{
                                            padding: '0.3rem 0.5rem',
                                            background: 'none',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            cursor: 'pointer',
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.8rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.3rem',
                                        }}
                                        title="Edit"
                                    >
                                        <Edit3 size={13} />
                                    </button>
                                    <button
                                        onClick={() => handleToggle(sched)}
                                        disabled={actionLoading === sched.id}
                                        style={{
                                            padding: '0.3rem 0.5rem',
                                            background: 'none',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            cursor: 'pointer',
                                            color: sched.enabled ? 'var(--warning)' : 'var(--success)',
                                            fontSize: '0.8rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.3rem',
                                        }}
                                        title={sched.enabled ? 'Pause' : 'Enable'}
                                    >
                                        {sched.enabled ? <Pause size={13} /> : <Play size={13} />}
                                        {sched.enabled ? 'Pause' : 'Enable'}
                                    </button>
                                    <button
                                        onClick={() => handleRunNow(sched)}
                                        disabled={actionLoading === sched.id}
                                        style={{
                                            padding: '0.3rem 0.5rem',
                                            background: 'none',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            cursor: 'pointer',
                                            color: 'var(--primary)',
                                            fontSize: '0.8rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.3rem',
                                        }}
                                        title="Run now"
                                    >
                                        {actionLoading === sched.id
                                            ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                                            : <Play size={13} />
                                        }
                                        Run Now
                                    </button>
                                    <button
                                        onClick={() => handleDelete(sched)}
                                        disabled={actionLoading === sched.id}
                                        style={{
                                            padding: '0.3rem 0.5rem',
                                            background: 'none',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            cursor: 'pointer',
                                            color: 'var(--danger)',
                                            fontSize: '0.8rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.3rem',
                                            marginLeft: 'auto',
                                        }}
                                        title="Delete"
                                    >
                                        <Trash2 size={13} />
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Upcoming Runs Timeline */}
            {upcomingRuns.length > 0 && (
                <div style={{ marginBottom: '2rem' }}>
                    <h2 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Calendar size={20} />
                        Upcoming Runs
                    </h2>
                    <div style={{
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        overflow: 'hidden',
                    }}>
                        {upcomingRuns.slice(0, 10).map((run, i) => {
                            const isFirst = i === 0;
                            const sched = schedules.find(s => s.id === run.schedule_id);
                            const timezone = sched?.timezone || 'UTC';
                            const formatted = formatInScheduleTimezone(run.fire_time, timezone);
                            return (
                                <div key={`${run.schedule_id}-${i}`} style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '1rem',
                                    padding: '0.75rem 1rem',
                                    borderBottom: i < Math.min(upcomingRuns.length, 10) - 1 ? '1px solid var(--border)' : 'none',
                                    background: isFirst ? 'rgba(59, 130, 246, 0.04)' : 'transparent',
                                }}>
                                    <div style={{
                                        width: '8px',
                                        height: '8px',
                                        borderRadius: '50%',
                                        background: isFirst ? 'var(--primary)' : 'var(--border)',
                                        flexShrink: 0,
                                    }} />
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: '0.85rem', fontWeight: isFirst ? 600 : 400 }}>
                                            {run.schedule_name}
                                        </div>
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'right', flexShrink: 0 }}>
                                        <div>{formatted}</div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Recent Execution History */}
            <div>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <AlertCircle size={20} />
                    Recent Executions
                </h2>
                {executions.length === 0 ? (
                    <div style={{
                        padding: '2rem',
                        textAlign: 'center',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        color: 'var(--text-secondary)',
                        fontSize: '0.9rem',
                    }}>
                        No executions yet. Schedules will appear here when they run.
                    </div>
                ) : (
                    <>
                        <div style={{
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            overflow: 'auto',
                        }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr>
                                        {['Schedule', 'Trigger', 'Started', 'Duration', 'Status', 'Batch'].map(h => (
                                            <th key={h} style={{
                                                padding: '0.6rem 0.75rem',
                                                textAlign: 'left',
                                                borderBottom: '2px solid var(--border)',
                                                fontWeight: 600,
                                                fontSize: '0.8rem',
                                                color: 'var(--text-secondary)',
                                            }}>{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {executions.map(exec => {
                                        const badge = getStatusBadge(exec.status);
                                        const durationSec = exec.duration_seconds
                                            ?? (exec.completed_at && exec.started_at
                                                ? Math.round((new Date(exec.completed_at).getTime() - new Date(exec.started_at).getTime()) / 1000)
                                                : null);
                                        return (
                                            <tr key={exec.id}>
                                                <td style={{ padding: '0.6rem 0.75rem', borderBottom: '1px solid var(--border)', fontSize: '0.85rem' }}>
                                                    {exec.schedule_name || exec.schedule_id}
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', borderBottom: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                    <span style={{
                                                        padding: '0.1rem 0.4rem',
                                                        borderRadius: 'var(--radius)',
                                                        background: exec.trigger_type === 'manual' ? 'var(--primary-glow)' : 'rgba(128,128,128,0.1)',
                                                        fontSize: '0.75rem',
                                                    }}>
                                                        {exec.trigger_type}
                                                    </span>
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', borderBottom: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                    {new Date(exec.started_at).toLocaleString()} (local)
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', borderBottom: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                    {durationSec != null ? (durationSec < 60 ? `${durationSec}s` : `${Math.floor(durationSec / 60)}m ${durationSec % 60}s`) : '-'}
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', borderBottom: '1px solid var(--border)' }}>
                                                    <span style={{
                                                        display: 'inline-flex',
                                                        alignItems: 'center',
                                                        gap: '0.25rem',
                                                        padding: '0.1rem 0.5rem',
                                                        borderRadius: '999px',
                                                        fontSize: '0.75rem',
                                                        fontWeight: 600,
                                                        color: badge.color,
                                                        background: badge.bg,
                                                    }}>
                                                        {exec.status === 'pass' || exec.status === 'success' ? <CheckCircle size={12} /> : exec.status === 'fail' || exec.status === 'failed' ? <XCircle size={12} /> : exec.status === 'running' ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <AlertCircle size={12} />}
                                                        {exec.status}
                                                    </span>
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', borderBottom: '1px solid var(--border)', fontSize: '0.8rem' }}>
                                                    {exec.batch_id ? (
                                                        <a href={`/regression/batches/${exec.batch_id}`} style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                                                            View
                                                        </a>
                                                    ) : '-'}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>

                        {/* Pagination */}
                        <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem', marginTop: '1rem' }}>
                            <button
                                disabled={page <= 1}
                                onClick={() => setPage(p => Math.max(1, p - 1))}
                                style={{
                                    padding: '0.4rem 0.75rem',
                                    background: 'transparent',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    cursor: page <= 1 ? 'not-allowed' : 'pointer',
                                    color: page <= 1 ? 'var(--text-secondary)' : 'var(--text)',
                                    fontSize: '0.85rem',
                                    opacity: page <= 1 ? 0.5 : 1,
                                }}
                            >
                                Previous
                            </button>
                            <span style={{ padding: '0.4rem 0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                Page {page}
                            </span>
                            <button
                                disabled={executions.length < pageSize}
                                onClick={() => setPage(p => p + 1)}
                                style={{
                                    padding: '0.4rem 0.75rem',
                                    background: 'transparent',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    cursor: executions.length < pageSize ? 'not-allowed' : 'pointer',
                                    color: executions.length < pageSize ? 'var(--text-secondary)' : 'var(--text)',
                                    fontSize: '0.85rem',
                                    opacity: executions.length < pageSize ? 0.5 : 1,
                                }}
                            >
                                Next
                            </button>
                        </div>
                    </>
                )}
            </div>

            {/* Modal */}
            <ScheduleModal
                isOpen={modalOpen}
                onClose={() => { setModalOpen(false); setEditingSchedule(undefined); }}
                onSave={handleSave}
                schedule={editingSchedule}
                projectId={projectId}
            />

            <style jsx>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </PageLayout>
    );
}
